#include "RaceRules.h"

#include "RaceNames.h"
#include "RaceRng.h"
#include <cmath>

namespace
{
	constexpr double Pi = 3.14159265358979323846;

	double MoveTowards(double Cur, double Target, double Delta)	// Unity Mathf.MoveTowards
	{
		return std::abs(Target - Cur) <= Delta ? Target : Cur + std::copysign(Delta, Target - Cur);
	}

	bool Approx(double A, double B)	// Unity Mathf.Approximately, in doubles
	{
		return std::abs(B - A) < std::max(1e-6 * std::max(std::abs(A), std::abs(B)), 1e-300);
	}

	const TCHAR* AuditNames[FContactAudit::Count] = { TEXT("foot-floor"), TEXT("body-floor"), TEXT("robot-robot"), TEXT("self"), TEXT("other") };
}

// --- yellow flag --------------------------------------------------------------------------------------------------------

void FYellowFlag::Update(int64 Step, bool bRacing, int32 NumLive, int32 NumDown)
{
	const bool bWant = bEnabled && bRacing && NumLive >= 3 && NumDown >= 2;
	if (!bOut && bWant && Step - End > CooldownSteps) { bOut = true; Since = Step; ++Count; }
	else if (bOut && (NumDown < 2 || Step - Since > YellowSteps || !bRacing)) { bOut = false; End = Step; }
}

// --- contact audit ------------------------------------------------------------------------------------------------------

void FContactAudit::Bind(const mjModel* m, const TArray<FRaceEntry>& Entries)
{
	Roots.Reset();
	Feet.Reset();
	for (const FRaceEntry& E : Entries)
	{
		Roots.Add(m->body_rootid[E.Racer->BaseBody()]);
		for (const FString& F : E.Feet)
		{
			const int32 G = Race::Find(m, mjOBJ_GEOM, m->ngeom, F);	// URLab's names carry an "{Actor}_" prefix
			if (G >= 0) Feet.Add(G);
		}
	}
}

void FContactAudit::Step(const mjModel* m, const mjData* d)
{
	++Steps;
	double Deep[Count] = {};
	for (int32 i = 0; i < d->ncon; ++i)
	{
		const mjContact& C = d->contact[i];
		if (C.dist >= 0.0) continue;
		const int32 G1 = C.geom[0], G2 = C.geom[1];
		const int32 R1 = m->body_rootid[m->geom_bodyid[G1]], R2 = m->body_rootid[m->geom_bodyid[G2]];
		const bool A = Roots.Contains(R1), B = Roots.Contains(R2);
		int32 K;
		if (A && B) K = R1 == R2 ? Self : RobotRobot;
		else if (A || B)
		{
			const int32 OtherRoot = A ? R2 : R1, Mine = A ? G1 : G2;
			K = OtherRoot != 0 ? Other : Feet.Contains(Mine) ? FootFloor : BodyFloor;
		}
		else continue;
		const double Depth = -C.dist;
		++Contacts[K];
		Deep[K] = std::max(Deep[K], Depth);
		Max[K] = std::max(Max[K], Depth);
	}
	for (int32 k = 0; k < Count; ++k)
	{
		const double Lim = k == FootFloor ? FootLimit : OtherLimit;
		Run[k] = Deep[k] > Lim ? Run[k] + 1 : 0;
		Worst[k] = std::max(Worst[k], Run[k]);
	}
}

FString FContactAudit::Line() const
{
	FString Out;
	for (int32 k = 0; k < Count; ++k)
		Out += FString::Printf(TEXT("%s%s max %.2f cm (limit %.1f, longest over %.2f s, %lld contacts)"), k ? TEXT(" | ") : TEXT(""), AuditNames[k],
			Max[k] * 100.0, (k == FootFloor ? FootLimit : OtherLimit) * 100.0, (double)Worst[k] * FRaceRules::Dt, Contacts[k]);
	return Out + FString::Printf(TEXT(" | %lld steps"), Steps);
}

TArray<FString> FContactAudit::Failures() const
{
	TArray<FString> Out;
	for (int32 k = 0; k < Count; ++k)
		if (Worst[k] > SustainSteps)
			Out.Add(FString::Printf(TEXT("%s penetration over %.1f cm for %.2f s"), AuditNames[k], (k == FootFloor ? FootLimit : OtherLimit) * 100.0, (double)Worst[k] * FRaceRules::Dt));
	return Out;
}

// --- the race -----------------------------------------------------------------------------------------------------------

void FRaceRules::Setup(const mjModel* m, mjData* d, int32 RequestedLaps)
{
	Laps = Track.bClosed ? FMath::Clamp(RequestedLaps > 0 ? RequestedLaps : Track.DefaultLaps, 1, 5) : 1;
	Total = Track.Length * Laps;
	Phase = ERacePhase::Countdown;
	Step = 0;
	RaceStart = -1;
	Finished = Flips = 0;
	bCalled = false;
	FirstFinish = -1;
	Bumps = 0;
	BumpSteps = 0;
	bInBump = false;
	YellowSteps = 0;
	Ahead.Reset();
	Events.Reset();
	const bool bYellow = Yellow.bEnabled;
	Yellow = FYellowFlag();
	Yellow.bEnabled = bYellow;
	mj_resetData(m, d);	// a fresh start, as race.py's fresh MjData
	ImpRatio = Entries.Num() ? Entries[0].ImpRatio : 100.0;
	for (const FRaceEntry& E : Entries) ImpRatio = std::min(ImpRatio, E.ImpRatio);
	const_cast<mjModel*>(m)->opt.impratio = ImpRatio;	// the grid's lowest (racelib/race.py draw)
	RootBodies.Reset();
	for (const FRaceEntry& E : Entries) RootBodies.Add(m->body_rootid[E.Racer->BaseBody()]);
	Audit = FContactAudit();
	if (bAudit) Audit.Bind(m, Entries);

	FRaceRng Rng(Seed);
	TArray<double> Lanes = Track.LaneOffsets(Entries.Num());
	if (bRandomizeGrid) Rng.Shuffle(Lanes);
	double Fastest = 0.0;
	for (int32 i = 0; i < Entries.Num(); ++i)
	{
		Entries[i].Lane = Lanes[i];
		Entries[i].Speed = Entries[i].Cruise * (1.0 - SpeedSpread * Rng.Uniform());
		Fastest = std::max(Fastest, Entries[i].Speed * Entries[i].Pace);
	}
	for (FRaceEntry& E : Entries)
	{
		E.Aggression = Rng.Uniform();
		// a head start that makes every expected finish time equal (Unity's, with the speed it actually holds); at most
		// half the race
		E.HeadStart = bHandicap ? std::min(0.5 * Total, Total * (1.0 - E.Speed * E.Pace / Fastest)) : 0.0;
		E.Distance = E.HeadStart;
		E.Lap = Track.bClosed ? (int32)(E.HeadStart / Track.Length) : 0;
		E.Lateral = E.Lane;
		Spawn(E, E.HeadStart);
		E.Racer->ResetToSpawn(m, d);
	}
	double X0 = Track.Points[0].X, Y0 = Track.Points[0].Y;
	for (const FVector2D& P : Track.Points) { X0 = std::min(X0, P.X); Y0 = std::min(Y0, P.Y); }
	for (int32 k = 0; k < Parked.Num(); ++k)
	{
		FRacer& R = *Parked[k];
		R.Spawn[0] = X0 - 40.0;
		R.Spawn[1] = Y0 - 40.0 + 3.0 * k;
		R.Spawn[2] = R.HomeHeight + 5.0;
		R.SpawnYaw = 0.0;
		R.ResetToSpawn(m, d);
	}
	mj_forward(m, d);
}

void FRaceRules::HoldParked(mjData* d) const
{
	for (const FRacer* R : Parked) R->Hold(d);
}

void FRaceRules::Spawn(FRaceEntry& E, double S) const
{
	FVector2D T, T0;
	const FVector2D P = Track.LanePoint(S, E.Lane, T);
	const FVector2D C = Track.PointAt(S, T0);
	const FVector2D L = FRaceTrack::Left(T);
	const double Lat = (P.X - C.X) * L.X + (P.Y - C.Y) * L.Y;
	const double Bank = std::abs(Track.BankAt(S)) * (Pi / 180.0);
	E.SpawnS = S;
	E.Racer->Spawn[0] = P.X;
	E.Racer->Spawn[1] = P.Y;
	E.Racer->Spawn[2] = E.Racer->HomeHeight + Track.SurfaceHeight(S, Lat) + 0.2 * std::tan(Bank);
	E.Racer->SpawnYaw = std::atan2(T.Y, T.X);
}

void FRaceRules::Resync(FRaceEntry& E) const
{
	// after a reset the progress walk restarts at the spawn's segment: it only walks forward, so from the segment the
	// racer had reached it measured a racer put back on a curve as off the track, and reset it every step (race.py)
	E.Segment = Track.SegmentAt(E.SpawnS);
	E.Lap = Track.bClosed ? (int32)(E.SpawnS / Track.Length) : 0;
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

// --- tactics ------------------------------------------------------------------------------------------------------------

double FRaceRules::Room(int32 i, double Lat) const
{
	const FRaceEntry& R = Entries[i];
	double Best = 5.0;
	for (int32 k = 0; k < Entries.Num(); ++k)
	{
		const FRaceEntry& O = Entries[k];
		if (k != i && O.FinishTime < 0.0 && std::abs(O.Distance - R.Distance) < 3.0) Best = std::min(Best, std::abs(O.Lateral - Lat));
	}
	return Best;
}

double FRaceRules::Tactic(int32 i, double Line)
{
	FRaceEntry& R = Entries[i];
	const double Edge = Track.HalfWidth - Margin, Me = Line + R.Offset;
	if (R.State != ERacerState::Racing) { R.Intent.Reset(); R.Passing = -1; return Me; }	// no manoeuvres while stumbling
	int32 Block = -1;
	double BestGap = std::numeric_limits<double>::infinity();
	for (int32 k = 0; k < Entries.Num(); ++k)
	{
		const FRaceEntry& O = Entries[k];
		if (k == i || O.FinishTime >= 0.0) continue;
		const double Ds = O.Distance - R.Distance;
		const bool bDown = O.State != ERacerState::Racing;
		// a pass under way holds until the passer is PassClear ahead, with the side window widened by the gap (race.py)
		const bool bHeld = k == R.Passing;
		const double Window = bDown ? 0.8 : std::max(0.55, 0.5 * (R.Width + O.Width) + 0.1);	// "in the way": Unity's 0.55, wider for wide bodies
		if (Ds <= (bHeld ? -PassClear : 0.0) || Ds > (bDown ? 5.0 : 2.5) || std::abs(O.Lateral - Me) > Window + (bHeld ? SideGap(R, O, PassGap) : 0.0)) continue;
		if ((bDown || O.Speed * O.Pace < R.Speed * R.Pace - 0.01) && Ds < BestGap) { BestGap = Ds; Block = k; }	// slower: at the pace it holds
	}
	if (Block >= 0)
	{
		const FRaceEntry& B = Entries[Block];
		const double Gap = SideGap(R, B, B.State != ERacerState::Racing ? AvoidGap : PassGap);
		const double Lft = B.Lateral + Gap, Rgt = B.Lateral - Gap;
		const double RoomL = Lft <= Edge ? Room(i, Lft) : -1.0;
		const double RoomR = Rgt >= -Edge ? Room(i, Rgt) : -1.0;
		if (RoomL >= 0.0 || RoomR >= 0.0)
		{
			const bool bLeft = RoomL > RoomR || (Approx(RoomL, RoomR) && Me >= B.Lateral);
			R.Passing = Block;
			R.Intent = B.State != ERacerState::Racing ? TEXT("AVOID") : bLeft ? TEXT("PASS L") : TEXT("PASS R");
			return bLeft ? Lft : Rgt;
		}
	}
	R.Passing = -1;
	if (R.Aggression > 0.5)
	{
		for (int32 k = 0; k < Entries.Num(); ++k)
		{
			const FRaceEntry& P = Entries[k];
			if (k == i || P.Passing != i) continue;
			const double Behind = R.Distance - P.Distance;
			if (Behind > 0.0 && Behind < 1.5)
			{
				R.Intent = TEXT("BLOCK");
				// Unity: 40 % of the way to the attacker's lateral; never closer than the side gap (race.py)
				double T = Line + (P.Lateral - Line) * 0.4;
				const double G = SideGap(R, P, PassGap);
				if (std::abs(T - P.Lateral) < G) T = P.Lateral + std::copysign(G, Me - P.Lateral);
				return std::min(std::max(T, -Edge), Edge);
			}
		}
	}
	// side by side: keep the gap on its own side rather than follow a lane squeeze into the other racer (race.py)
	for (int32 k = 0; k < Entries.Num(); ++k)
	{
		const FRaceEntry& O = Entries[k];
		if (k == i || O.FinishTime >= 0.0 || O.State != ERacerState::Racing || std::abs(O.Distance - R.Distance) >= Alongside) continue;
		const double G = SideGap(R, O, PassGap);
		if (std::abs(Line - O.Lateral) < G)
		{
			R.Intent = TEXT("ALONGSIDE");
			return std::min(std::max(O.Lateral + std::copysign(G, Me - O.Lateral), -Edge), Edge);
		}
	}
	R.Intent.Reset();
	return Line;
}

void FRaceRules::DetectOvertakes()
{
	for (int32 i = 0; i < Entries.Num(); ++i)
		for (int32 j = i + 1; j < Entries.Num(); ++j)
		{
			FRaceEntry& A = Entries[i];
			FRaceEntry& B = Entries[j];
			if (A.FinishTime >= 0.0 || B.FinishTime >= 0.0) continue;
			const double Dd = A.Distance - B.Distance;
			const int32 Now = Dd > OvertakeHyst ? 1 : Dd < -OvertakeHyst ? -1 : 0;
			if (Now == 0) continue;
			const int64 Key = ((int64)i << 32) | j;
			if (const int32* Before = Ahead.Find(Key); Before && *Before != Now)
			{
				FRaceEntry& Passer = Now > 0 ? A : B;
				const FRaceEntry& Passed = Now > 0 ? B : A;
				++Passer.Passes;
				Events.Add(FString::Printf(TEXT("%.2fs pass %s %s"), RaceTime(), *Passer.Name, *Passed.Name));
			}
			Ahead.Add(Key, Now);
		}
}

void FRaceRules::CountBumps(const mjModel* m, const mjData* d)
{
	bool bHit = false;
	for (int32 i = 0; i < d->ncon && !bHit; ++i)
	{
		const int32 R1 = m->body_rootid[m->geom_bodyid[d->contact[i].geom[0]]], R2 = m->body_rootid[m->geom_bodyid[d->contact[i].geom[1]]];
		bHit = R1 != R2 && RootBodies.Contains(R1) && RootBodies.Contains(R2);
	}
	if (bHit) { ++BumpSteps; if (!bInBump) { ++Bumps; bInBump = true; } }
	else bInBump = false;
}

// --- one physics step ---------------------------------------------------------------------------------------------------

void FRaceRules::PreStep(const mjModel* m, mjData* d)
{
	if (Phase == ERacePhase::Countdown && Step >= IntroSteps + CountdownSteps)
	{
		Phase = ERacePhase::Racing;
		RaceStart = Step;
	}
	const double Rt = RaceTime();
	if (Phase == ERacePhase::Racing && FlipAt >= 0.0 && FlipAt <= Rt)
	{
		FlipAt = -1.0;
		int32 Left = FlipCount;
		for (const int32 i : Standings())
		{
			if (Left <= 0) break;
			if (Entries[i].FinishTime >= 0.0) continue;
			Entries[i].Racer->KnockOver(m, d);
			++Flips;
			--Left;
		}
	}
	if (bAudit && Phase == ERacePhase::Racing) Audit.Step(m, d);

	HoldParked(d);
	for (int32 i = 0; i < Entries.Num(); ++i)
	{
		FRaceEntry& E = Entries[i];
		FRacer& R = *E.Racer;
		const ERacerState Was = E.State;
		if (R.UpdateState(m, d)) Resync(E);
		E.State = R.State;
		if (Phase == ERacePhase::Racing && E.FinishTime < 0.0)
		{
			if (E.State == ERacerState::Fallen && Was != ERacerState::Fallen) { ++E.Falls; E.bDown = true; }
			if (E.State == ERacerState::Racing && E.bDown) E.bDown = false;
		}
		if (Phase == ERacePhase::Countdown && E.bHoldsHeading)
		{
			FVector2D T0;
			Track.PointAt(E.HeadStart, T0);
			const double E0 = std::remainder(std::atan2(T0.Y, T0.X) - R.Yaw(d), 2.0 * Pi);
			R.Target[0] = 0.0;
			R.Target[1] = 0.0;
			R.Target[2] = std::min(std::max(SteerGain * E0, -E.MaxYaw), E.MaxYaw);
			continue;
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
			if (FirstFinish < 0) FirstFinish = Step;
			R.Target[0] = R.Target[1] = R.Target[2] = 0.0;
			continue;
		}
		const int32 Cp = (int32)std::floor(Dist / Track.CheckpointSpacing);
		if (Cp > E.Checkpoint)
		{
			E.Checkpoint = Cp;
			Spawn(E, Cp * Track.CheckpointSpacing);
		}

		// Lane choice: the racing line (lane x the lap's squeeze) plus the tactical offset, slewed at 0.6 m/s. Banks
		// are a no-manoeuvre zone (sideways moves on the bank stalled the slope brain uphill: Unity F.8).
		const double Line = E.Lane * Track.LaneScale(Dist);
		const bool bBanked = std::abs(Track.BankAt(Dist)) > 0.5 || std::abs(Track.BankAt(Dist + Track.LookAhead)) > 0.5;
		if (bTactics) E.Offset = MoveTowards(E.Offset, bBanked ? 0.0 : Tactic(i, Line) - Line, OffsetSlew);
		if (bBanked) { E.Intent.Reset(); E.Passing = -1; }
		FVector2D Tan;
		const FVector2D Tp = Track.LanePoint(Dist + Track.LookAhead, E.Lane, Tan);
		const FVector2D Lt = FRaceTrack::Left(Tan);
		const double Tx = Tp.X + Lt.X * E.Offset, Ty = Tp.Y + Lt.Y * E.Offset;
		const double Err = std::remainder(std::atan2(Ty - Pos.Y, Tx - Pos.X) - R.Yaw(d), 2.0 * Pi);
		const double YawRate = std::min(std::max(SteerGain * Err, -E.MaxYaw), E.MaxYaw);
		const double LatErr = Line + E.Offset - Lateral;
		double Vy = bTactics && !bBanked && std::abs(LatErr) > 0.1 && std::abs(Err) < 0.5 ? std::min(std::max(LatErr, -MaxLateral), MaxLateral) : 0.0;
		double Vx = E.Speed * (Yellow.bOut ? FYellowFlag::Scale : 1.0) * std::max(0.3, std::cos(Err));
		const bool bStuck = E.bUsesUnstick && R.Locomoting() && R.CmdX() > 1.0 && R.PlanarSpeed2(d) < StuckSpeed * StuckSpeed;
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
			Resync(E);
			++E.OffTrack;
		}
	}

	if (Phase == ERacePhase::Racing) DetectOvertakes();
	const bool bWasOut = Yellow.bOut;
	int32 Down = 0;
	for (const FRaceEntry& E : Entries) if (E.bDown && E.FinishTime < 0.0) ++Down;
	Yellow.Update(Step, Phase == ERacePhase::Racing, Entries.Num(), Down);
	if (Yellow.bOut != bWasOut) Events.Add(FString::Printf(TEXT("%.2fs %s"), RaceTime(), Yellow.bOut ? TEXT("yellow") : TEXT("green")));
	if (Yellow.bOut) ++YellowSteps;
	if (Phase == ERacePhase::Racing && Finished == Entries.Num()) Phase = ERacePhase::Finished;
	else if (Phase == ERacePhase::Racing && ((FinishWindowSteps > 0 && FirstFinish >= 0 && Step - FirstFinish >= FinishWindowSteps) || Step - RaceStart >= LimitSteps))
	{
		Phase = ERacePhase::Finished;
		bCalled = true;
	}
	if (Phase == ERacePhase::Racing) CountBumps(m, d);
}

void FRaceRules::Control(const mjModel* m, mjData* d)
{
	for (FRaceEntry& E : Entries) E.Racer->Control(m, d);
	++Step;
}

FString FRaceRules::ResultLine() const
{
	FString Out = FString::Printf(TEXT("%s map=%s laps=%d length=%.1fm seed=%llu"),
		Phase == ERacePhase::Finished && !bCalled ? TEXT("FINISHED") : bCalled && Finished ? TEXT("CALLED") : TEXT("DNF"), *Track.Name, Laps, Total, Seed);
	for (const int32 i : Standings())
	{
		const FRaceEntry& E = Entries[i];
		const FString T = E.FinishTime >= 0.0 ? FString::Printf(TEXT("%.2fs"), E.FinishTime) : FString::Printf(TEXT("DNF@%.0fm"), E.Distance);
		Out += FString::Printf(TEXT(" | %s %s lane=%.1f v=%.2f%s resets=%d offtrack=%d unstuck=%d%s falls=%d passes=%d"),
			*E.Name, *T, E.Lane, E.Speed, E.HeadStart > 0.0 ? *FString::Printf(TEXT(" head=%.1fm"), E.HeadStart) : TEXT(""),
			E.Racer->Resets, E.OffTrack, E.Unsticks, E.Backoffs ? *FString::Printf(TEXT(" backoffs=%d"), E.Backoffs) : TEXT(""), E.Falls, E.Passes);
	}
	Out += FString::Printf(TEXT(" | flips=%d bumps=%d bumpTime=%.2fs"), Flips, Bumps, (double)BumpSteps * Dt);
	if (Yellow.Count) Out += FString::Printf(TEXT(" yellows=%d yellowTime=%.2fs"), Yellow.Count, (double)YellowSteps * Dt);
	return Out;
}

// --- self test (training/selftest.py prints the same lines) -------------------------------------------------------------

TArray<FString> FRaceRules::SelfTest()
{
	TArray<FString> Out;
	struct FRow { const TCHAR* Name; double Distance, Lateral, Speed, Aggression; ERacerState State; int32 Passing; double Width = 0.35; };
	struct FCase { const TCHAR* Name; double HalfWidth; int32 Who; double Line; TArray<FRow> Rows; };
	const ERacerState Ok = ERacerState::Racing;
	const TArray<FCase> Cases = {
		{ TEXT("pass"), 1.5, 0, 0.0, { { TEXT("A"), 10.0, 0.0, 1.5, 0.2, Ok, -1 }, { TEXT("B"), 11.5, 0.1, 1.2, 0.2, Ok, -1 } } },
		{ TEXT("pass-left"), 1.5, 0, 0.0, { { TEXT("A"), 10.0, 0.0, 1.5, 0.2, Ok, -1 }, { TEXT("B"), 11.0, -0.3, 1.2, 0.2, Ok, -1 }, { TEXT("C"), 9.0, -0.9, 1.4, 0.2, Ok, -1 } } },
		{ TEXT("avoid"), 1.5, 0, 0.0, { { TEXT("A"), 10.0, 0.0, 1.5, 0.2, Ok, -1 }, { TEXT("B"), 14.0, 0.5, 1.6, 0.2, ERacerState::Fallen, -1 } } },
		{ TEXT("pass-hold"), 2.0, 0, 0.4, { { TEXT("A"), 10.3, 0.55, 1.5, 0.2, Ok, 1 }, { TEXT("B"), 10.0, -0.05, 1.3, 0.2, Ok, -1 } } },
		{ TEXT("pass-done"), 2.0, 0, 0.4, { { TEXT("A"), 11.1, 0.55, 1.5, 0.2, Ok, 1 }, { TEXT("B"), 10.0, -0.05, 1.3, 0.2, Ok, -1 } } },
		{ TEXT("pass-wide"), 1.5, 0, 0.0, { { TEXT("S"), 10.0, 0.0, 1.5, 0.2, Ok, -1, 0.65 }, { TEXT("B"), 11.5, 0.1, 1.2, 0.2, Ok, -1, 0.35 } } },
		{ TEXT("alongside"), 1.5, 0, 0.0, { { TEXT("S"), 10.0, 0.1, 1.45, 0.2, Ok, -1, 0.65 }, { TEXT("B"), 10.3, -0.1, 1.45, 0.2, Ok, -1, 0.35 } } },
		{ TEXT("faster-ahead"), 1.5, 0, 0.0, { { TEXT("A"), 10.0, 0.0, 1.2, 0.2, Ok, -1 }, { TEXT("B"), 11.0, 0.0, 1.5, 0.2, Ok, -1 } } },
		{ TEXT("block"), 1.5, 0, 0.3, { { TEXT("C"), 20.0, 0.3, 1.2, 0.8, Ok, -1 }, { TEXT("D"), 19.0, -0.2, 1.5, 0.2, Ok, 0 } } },
		{ TEXT("no-block-timid"), 1.5, 0, 0.3, { { TEXT("C"), 20.0, 0.3, 1.2, 0.3, Ok, -1 }, { TEXT("D"), 19.0, -0.2, 1.5, 0.2, Ok, 0 } } },
		{ TEXT("boxed-in"), 0.9, 0, 0.0, { { TEXT("A"), 0.0, 0.0, 1.5, 0.2, Ok, -1 }, { TEXT("B"), 1.0, 0.0, 1.2, 0.2, Ok, -1 } } },
		{ TEXT("stumbling"), 1.5, 0, 0.2, { { TEXT("A"), 10.0, 0.0, 1.5, 0.2, ERacerState::Stumble, -1 }, { TEXT("B"), 11.0, 0.0, 1.2, 0.2, Ok, -1 } } },
	};
	for (const FCase& C : Cases)
	{
		FRaceRules R;
		R.Track.HalfWidth = C.HalfWidth;
		for (const FRow& W : C.Rows)
		{
			FRaceEntry& E = R.Entries.AddDefaulted_GetRef();
			E.Name = W.Name; E.Distance = W.Distance; E.Lateral = W.Lateral; E.Speed = W.Speed; E.Aggression = W.Aggression;
			E.State = W.State; E.Passing = W.Passing; E.Width = W.Width;
		}
		const double V = R.Tactic(C.Who, C.Line);
		const FRaceEntry& E = R.Entries[C.Who];
		Out.Add(FString::Printf(TEXT("tactic %s: target=%.4f intent=%s passing=%s"), C.Name, V, E.Intent.IsEmpty() ? TEXT("-") : *E.Intent,
			E.Passing >= 0 ? *R.Entries[E.Passing].Name : TEXT("-")));
	}
	// yellow: 3 racers, 2 down over steps [100, 2000) and [3000, 9000)
	for (const int32 Live : { 3, 2 })
	{
		FYellowFlag Y;
		Y.bEnabled = true;
		FString Log;
		for (int64 s = 0; s < 10000; ++s)
		{
			const bool bWas = Y.bOut;
			Y.Update(s, true, Live, (s >= 100 && s < 2000) || (s >= 3000 && s < 9000) ? 2 : 0);
			if (Y.bOut != bWas) Log += FString::Printf(TEXT(" %s@%lld"), Y.bOut ? TEXT("out") : TEXT("in"), s);
		}
		Out.Add(FString::Printf(TEXT("yellow live=%d:%s count=%d"), Live, Log.IsEmpty() ? TEXT(" none") : *Log, Y.Count));
	}
	return Out;
}
