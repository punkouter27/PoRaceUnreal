#include "RaceRules.h"

#include "RaceRng.h"
#include <cmath>

void FRaceRules::Setup(const mjModel* m, mjData* d, int32 RequestedLaps)
{
	Laps = Track.bClosed ? FMath::Clamp(RequestedLaps > 0 ? RequestedLaps : Track.DefaultLaps, 1, 5) : 1;
	Total = Track.Length * Laps;
	Phase = ERacePhase::Countdown;
	Step = 0;
	RaceStart = -1;
	Finished = Flips = 0;
	mj_resetData(m, d);	// a fresh start, as race.py's fresh MjData

	FRaceRng Rng(Seed);
	TArray<double> Lanes = Track.LaneOffsets(Entries.Num());
	if (bRandomizeGrid) Rng.Shuffle(Lanes);
	for (int32 i = 0; i < Entries.Num(); ++i)
	{
		Entries[i].Lane = Lanes[i];
		Entries[i].Speed = Entries[i].Cruise * (1.0 - SpeedSpread * Rng.Uniform());
	}
	for (FRaceEntry& E : Entries)
	{
		E.Aggression = Rng.Uniform();
		Spawn(E, 0.0);
		E.Racer->ResetToSpawn(m, d);
	}
	mj_forward(m, d);
}

void FRaceRules::Spawn(FRaceEntry& E, double S) const
{
	FVector2D T, T0;
	const FVector2D P = Track.LanePoint(S, E.Lane, T);
	const FVector2D C = Track.PointAt(S, T0);
	const FVector2D L = FRaceTrack::Left(T);
	const double Lat = (P.X - C.X) * L.X + (P.Y - C.Y) * L.Y;
	const double Bank = std::abs(Track.BankAt(S)) * (3.14159265358979323846 / 180.0);
	E.Racer->Spawn[0] = P.X;
	E.Racer->Spawn[1] = P.Y;
	E.Racer->Spawn[2] = E.Racer->HomeHeight + Track.SurfaceHeight(S, Lat) + 0.2 * std::tan(Bank);
	E.Racer->SpawnYaw = std::atan2(T.Y, T.X);
}

double FRaceRules::Progress(FRaceEntry& E, const FVector2D& Pos, double& OutLateral) const
{
	double T = 0.0, Ln = 1.0;
	FVector2D A(0.0, 0.0), D(1.0, 0.0);
	for (int32 Guard = 0; Guard < Track.N + 1; ++Guard)
	{
		A = Track.P(E.Segment);
		const FVector2D B = Track.P(E.Segment + 1);
		const double Dx = B.X - A.X, Dy = B.Y - A.Y;
		Ln = std::sqrt(Dx * Dx + Dy * Dy);
		D = FVector2D(Dx / Ln, Dy / Ln);
		T = (Pos.X - A.X) * D.X + (Pos.Y - A.Y) * D.Y;
		if (T <= Ln) break;
		if (E.Segment + 1 < Track.N) ++E.Segment;
		else if (Track.bClosed) { E.Segment = 0; ++E.Lap; }
		else break;
	}
	const FVector2D L = FRaceTrack::Left(D);
	OutLateral = (Pos.X - A.X) * L.X + (Pos.Y - A.Y) * L.Y;
	const double Along = Track.bClosed ? std::min(std::max(T, 0.0), Ln) : std::max(0.0, T);
	return E.Lap * Track.Length + Track.Cum[E.Segment] + Along;
}

TArray<int32> FRaceRules::Standings() const
{
	TArray<int32> Order;
	for (int32 i = 0; i < Entries.Num(); ++i) Order.Add(i);
	auto Key = [this](int32 i) { const FRaceEntry& E = Entries[i]; return E.FinishTime >= 0.0 ? 1e6 - E.FinishTime : E.Distance; };
	Algo::StableSort(Order, [&](int32 A, int32 B) { return Key(A) > Key(B); });
	return Order;
}

int32 FRaceRules::Leader() const
{
	const TArray<int32> Order = Standings();
	for (const int32 i : Order) if (Entries[i].FinishTime < 0.0) return i;
	return Order.Num() ? Order[0] : -1;
}

void FRaceRules::PreStep(const mjModel* m, mjData* d)
{
	if (Phase == ERacePhase::Countdown && Step >= CountdownSteps)
	{
		Phase = ERacePhase::Racing;
		RaceStart = Step;
	}
	const double Rt = RaceTime();
	if (Phase == ERacePhase::Racing && FlipAt >= 0.0 && FlipAt <= Rt)
	{
		FlipAt = -1.0;
		const int32 L = Leader();
		if (L >= 0) Entries[L].Racer->KnockOver(m, d);
		++Flips;
	}

	for (FRaceEntry& E : Entries)
	{
		FGo2Racer& R = *E.Racer;
		const ERacerState Was = E.State;
		R.UpdateState(m, d);
		E.State = R.State;
		if (Phase == ERacePhase::Racing && E.FinishTime < 0.0)
		{
			if (E.State == ERacerState::Fallen && Was != ERacerState::Fallen) { ++E.Falls; E.bDown = true; }
			if (E.State == ERacerState::Racing && E.bDown) E.bDown = false;
		}
		if (Phase != ERacePhase::Racing || E.FinishTime >= 0.0)
		{
			R.Target[0] = R.Target[1] = R.Target[2] = 0.0;
			continue;
		}

		const FVector2D Pos = R.Pos(d);
		double Lateral = 0.0;
		const double Dist = Progress(E, Pos, Lateral);
		E.Distance = std::min(Dist, Total);
		E.Lateral = Lateral;
		if (Dist >= Total)
		{
			E.FinishTime = Rt;
			E.Place = ++Finished;
			R.Target[0] = R.Target[1] = R.Target[2] = 0.0;
			continue;
		}
		const int32 Cp = (int32)std::floor(Dist / Track.CheckpointSpacing);
		if (Cp > E.Checkpoint)
		{
			E.Checkpoint = Cp;
			Spawn(E, Cp * Track.CheckpointSpacing);
		}

		FVector2D Tan;
		const FVector2D Tp = Track.LanePoint(Dist + Track.LookAhead, E.Lane, Tan);
		const double Err = std::remainder(std::atan2(Tp.Y - Pos.Y, Tp.X - Pos.X) - R.Yaw(d), 2.0 * 3.14159265358979323846);
		const double YawRate = std::min(std::max(SteerGain * Err, -E.MaxYaw), E.MaxYaw);
		double Vx = E.Speed * std::max(0.3, std::cos(Err)), Vy = 0.0;
		const bool bStuck = E.bUsesUnstick && R.Locomoting() && (double)R.Cmd[0] > 1.0 && R.PlanarSpeed2(d) < StuckSpeed * StuckSpeed;
		E.StuckSteps = bStuck ? E.StuckSteps + 1 : 0;
		if (E.StuckSteps > StuckSteps)
		{
			R.RestartCommandRamp();
			E.StuckSteps = 0;
			++E.Unsticks;
			E.UnstickChain = Dist - E.UnstickDist < 0.3 ? E.UnstickChain + 1 : 1;
			E.UnstickDist = Dist;
			if (E.UnstickChain >= 6) { E.BackoffSteps = BackoffSteps; E.UnstickChain = 0; ++E.Backoffs; }
		}
		if (E.BackoffSteps > 0) { --E.BackoffSteps; Vx = -0.5; Vy = 0.0; }
		R.Target[0] = Vx;
		R.Target[1] = Vy;
		R.Target[2] = YawRate;
		if (std::abs(Lateral) > Track.HalfWidth + OffTrack)
		{
			R.ResetToSpawn(m, d);
			++E.OffTrack;
		}
	}
	if (Phase == ERacePhase::Racing && Finished == Entries.Num()) Phase = ERacePhase::Finished;
}

void FRaceRules::Control(const mjModel* m, mjData* d)
{
	for (FRaceEntry& E : Entries) E.Racer->Control(m, d);
	++Step;
}

FString FRaceRules::ResultLine() const
{
	FString Out = FString::Printf(TEXT("%s map=%s laps=%d length=%.1fm seed=%llu"),
		Phase == ERacePhase::Finished ? TEXT("FINISHED") : TEXT("DNF"), *Track.Name, Laps, Total, Seed);
	for (const int32 i : Standings())
	{
		const FRaceEntry& E = Entries[i];
		const FString T = E.FinishTime >= 0.0 ? FString::Printf(TEXT("%.2fs"), E.FinishTime) : FString::Printf(TEXT("DNF@%.0fm"), E.Distance);
		Out += FString::Printf(TEXT(" | %s %s lane=%.1f v=%.2f resets=%d offtrack=%d unstuck=%d%s falls=%d passes=%d"),
			*E.Name, *T, E.Lane, E.Speed, E.Racer->Resets, E.OffTrack, E.Unsticks,
			E.Backoffs ? *FString::Printf(TEXT(" backoffs=%d"), E.Backoffs) : TEXT(""), E.Falls, E.Passes);
	}
	return Out + FString::Printf(TEXT(" | flips=%d"), Flips);
}
