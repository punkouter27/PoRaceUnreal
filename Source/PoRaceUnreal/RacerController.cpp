// URacerController: the race (or the parity testbed) on URLab's physics thread. Every step here has a twin in
// training/race.py (race) or training/parity_check.py (testbed); change both or the checks fail.

#include "RacerController.h"

#include "Async/Async.h"
#include "EngineUtils.h"
#include "Misc/CommandLine.h"
#include "Misc/Parse.h"
#include "NNEModelData.h"
#include "RaceContract.gen.h"
#include "RaceHUD.h"
#include "RaceModel.h"
#include "RacerGo2.h"
#include "RacerHuman.h"
#include "RaceNames.h"

DEFINE_LOG_CATEGORY(LogRace);

using namespace RaceContract;

static_assert(mjVERSION_HEADER == RaceContract::MuJoCoVersionHeader, "URLab's MuJoCo is not the version the brains are gated on (training/contract.py)");

std::atomic<int32> URacerController::CheckFailures = 0;

ARaceGameMode::ARaceGameMode()
{
	DefaultPawnClass = nullptr;
	HUDClass = ARaceHUD::StaticClass();
	PlayerControllerClass = ARacePlayerController::StaticClass();
}

namespace
{
	FString JsonRow(const double* X, int32 N)
	{
		FString Out = TEXT("[");
		for (int32 i = 0; i < N; ++i) Out += FString::Printf(TEXT("%s%.17g"), i ? TEXT(", ") : TEXT(""), X[i]);
		return Out + TEXT("]");
	}

	FString JsonRow(const float* X, int32 N)
	{
		FString Out = TEXT("[");
		for (int32 i = 0; i < N; ++i) Out += FString::Printf(TEXT("%s%.9g"), i ? TEXT(", ") : TEXT(""), X[i]);
		return Out + TEXT("]");
	}

	FLinearColor Color(const FJsonObject& O, const TCHAR* Key)
	{
		const TArray<TSharedPtr<FJsonValue>>* A;
		if (!O.TryGetArrayField(Key, A) || A->Num() < 3) return FLinearColor::White;
		return FLinearColor((float)(*A)[0]->AsNumber(), (float)(*A)[1]->AsNumber(), (float)(*A)[2]->AsNumber());
	}
}

URacerController* URacerController::Find(const UWorld* World)
{
	if (!World) return nullptr;
	for (TActorIterator<AActor> It(World); It; ++It)
		if (URacerController* C = It->FindComponentByClass<URacerController>()) return C;
	return nullptr;
}

UNNEModelData* URacerController::LoadBrainFile(const FString& Path)
{
	TArray<uint8> Bytes;
	const FString Full = FPaths::IsRelative(Path) ? FPaths::Combine(FPaths::ProjectDir(), Path) : Path;
	if (!FFileHelper::LoadFileToArray(Bytes, *Full))
	{
		UE_LOG(LogRace, Error, TEXT("brain %s: no such file"), *Full);
		return nullptr;
	}
	UNNEModelData* Data = NewObject<UNNEModelData>(this, FName(*FPaths::GetBaseFilename(Path)));
	Data->Init(TEXT("onnx"), Bytes);
	LoadedBrains.Add(Data);
	return Data;
}

void URacerController::Bind(mjModel* m, mjData* d, const TMap<int32, UMjActuator*>& ActuatorIdMap)
{
	Super::Bind(m, d, ActuatorIdMap);
	StepCount = 0;
	bReady = bStarted = bReported = bDumped = false;
	Racers.Reset();
	bRace = !TrackFingerprint.IsEmpty();
	bReady = bRace ? BindRace(m, d) : BindTestbed(m, d);
}

// --- race ---------------------------------------------------------------------------------------------------------------

bool URacerController::BindRace(mjModel* m, mjData* d)
{
	// Options: the level URL the menu opened (?Racers=blue,matt?Laps=2?Seed=7), then the command line (tests) over it
	const TCHAR* Cmd = FCommandLine::Get();
	const FURL* Url = GetWorld() ? &GetWorld()->URL : nullptr;
	auto Opt = [&](const TCHAR* Key, FString& Out) -> bool	// Key without '=': "Racers"
	{
		bool bFound = false;
		if (Url && Url->HasOption(Key)) { Out = Url->GetOption(*(FString(Key) + TEXT("=")), TEXT("")); bFound = true; }
		FString V;
		if (FParse::Value(Cmd, *(FString(Key) + TEXT("=")), V, false)) { Out = V; bFound = true; }
		return bFound;
	};
	bTest = FParse::Param(Cmd, TEXT("RaceTest"));
	FString S;
	uint64 Seed = (uint64)(FDateTime::Now().GetTicks() & 0xFFFF);
	if (Opt(TEXT("Seed"), S) && FCString::Atoi64(*S) >= 0) Seed = (uint64)FCString::Atoi64(*S);
	RequestedLaps = Opt(TEXT("Laps"), S) ? FCString::Atoi(*S) : 0;
	const double FlipAt = Opt(TEXT("RaceFlipAt"), S) ? FCString::Atod(*S) : -1.0;
	TArray<FString> Want;	// Racers=blue,matt: who is on the grid (default every racer of the track model)
	if (Opt(TEXT("Racers"), S)) S.ToLower().ParseIntoArray(Want, TEXT(","));
	// interactive defaults: a racer intro of 2.5 s per racer and the race called 60 s after the winner; a race test has
	// neither unless asked (the reference races and their results stay as they were)
	IntroSeconds = Opt(TEXT("Intro"), S) ? FCString::Atod(*S) : -1.0;	// < 0: 2.5 s per racer, or 0 in a test
	const double Window = Opt(TEXT("FinishWindow"), S) ? FCString::Atod(*S) : bTest ? 0.0 : 60.0;
	bExplicitLimit = Opt(TEXT("RaceLimit"), S);
	const double Limit = bExplicitLimit ? FCString::Atod(*S) : 600.0;
	Rules.FinishWindowSteps = FMath::RoundToInt64(Window / FRaceRules::Dt);
	Rules.LimitSteps = FMath::RoundToInt64(Limit / FRaceRules::Dt);

	const TSharedPtr<FJsonObject> Fp = Race::LoadJson(TrackFingerprint);
	if (!Fp) return false;
	const FString TrackId = Fp->GetStringField(TEXT("track"));
	const TSharedPtr<FJsonObject> TrackJson = Race::LoadJson(FString::Printf(TEXT("training/tracks/%s.json"), *TrackId));
	if (!TrackJson || !Rules.Track.Load(*TrackJson)) { UE_LOG(LogRace, Error, TEXT("track %s: could not load"), *TrackId); return false; }

	// the training numbers over URLab's rebuild: options, the world, then every racer's body (RaceModel.h)
	RaceModel::ApplyOptions(m, *Fp->GetObjectField(TEXT("option")));
	int32 Missing = RaceModel::ApplyNumbers(m, *Fp->GetObjectField(TEXT("world")), FString());
	TMap<FString, TSharedPtr<FJsonObject>> Creatures;
	Rules.Entries.Reset();
	Rules.Parked.Reset();
	ParkedPrefixes.Reset();
	ParkedRootBodies.Reset();
	bool bOk = true;
	for (const TSharedPtr<FJsonValue>& V : Fp->GetArrayField(TEXT("racers")))
	{
		const FJsonObject& R = *V->AsObject();
		const FString Prefix = R.GetStringField(TEXT("prefix"));
		const FString CardFp = R.GetStringField(TEXT("fingerprint"));
		if (!Creatures.Contains(CardFp)) Creatures.Add(CardFp, Race::LoadJson(CardFp));
		const TSharedPtr<FJsonObject> Creature = Creatures[CardFp];
		if (!Creature) { bOk = false; continue; }
		Missing += RaceModel::ApplyNumbers(m, *Creature->GetObjectField(TEXT("model")), Prefix);

		const FString CardName = R.GetStringField(TEXT("card"));
		const TSharedPtr<FJsonObject> Card = Race::LoadJson(FString::Printf(TEXT("training/characters/%s.json"), *CardName));
		if (!Card) { bOk = false; continue; }
		const FString LocoName = R.GetStringField(TEXT("brain"));
		FString GetupName;
		R.TryGetStringField(TEXT("getupBrain"), GetupName);
		auto BrainFile = [&](const FString& Name) { return LoadBrainFile(FString::Printf(TEXT("training/models/brains/%s.onnx"), *Name)); };
		TUniquePtr<FRacer> Racer;
		if (Card->GetStringField(TEXT("kind")) == TEXT("human"))
		{
			TUniquePtr<FHumanRacer> H = MakeUnique<FHumanRacer>();
			bOk &= H->Bind(m, Prefix, *Card, *Creature);
			bOk &= H->Loco.Load(BrainFile(LocoName));
			Racer = MoveTemp(H);
		}
		else
		{
			TUniquePtr<FGo2Racer> G = MakeUnique<FGo2Racer>();
			bOk &= G->Bind(m, Prefix, R.GetNumberField(TEXT("homeHeight")));
			bOk &= G->Loco.Load(BrainFile(LocoName));
			bOk &= G->Getup.Load(BrainFile(GetupName));
			Racer = MoveTemp(G);
		}
		const FString Name = R.GetStringField(TEXT("name"));
		if (Want.Num() && !Want.Contains(Name.ToLower()))
		{
			UE_LOG(LogRace, Log, TEXT("racer %s (%s): parked (not on the grid)"), *Name, *Prefix);
			Rules.Parked.Add(Racer.Get());
			ParkedPrefixes.Add(Prefix);
			ParkedRootBodies.Add(m->body_rootid[Racer->BaseBody()]);
			Racers.Add(MoveTemp(Racer));
			continue;
		}
		FRaceEntry& E = Rules.Entries.AddDefaulted_GetRef();
		E.Name = Name;
		E.Color = Color(R, TEXT("color"));
		E.Cruise = R.GetNumberField(TEXT("cruise"));
		E.MaxYaw = R.GetNumberField(TEXT("maxYawRate"));
		E.bUsesUnstick = R.GetBoolField(TEXT("usesUnstick"));
		Card->TryGetBoolField(TEXT("holdsHeadingAtRest"), E.bHoldsHeading);
		Card->TryGetNumberField(TEXT("impratio"), E.ImpRatio);
		E.Racer = Racer.Get();
		UE_LOG(LogRace, Log, TEXT("racer %s (%s, %s): brains %s%s%s, cruise %.2f m/s, impratio %g"), *E.Name, *Prefix, *Card->GetStringField(TEXT("kind")),
			*LocoName, GetupName.IsEmpty() ? TEXT("") : TEXT(" + "), *GetupName, E.Cruise, E.ImpRatio);
		Racers.Add(MoveTemp(Racer));
	}
	mj_setConst(m, d);
	const FString Bound = RaceModel::Save(m, *FString::Printf(TEXT("model_bound_%s.mjb"), *TrackId));	// per track: parallel race tests
	Rules.Seed = Seed;
	Rules.FlipAt = FlipAt;
	const double Intro = IntroSeconds >= 0.0 ? IntroSeconds : bTest ? 0.0 : 2.5 * Rules.Entries.Num();
	Rules.IntroSteps = FMath::RoundToInt64(Intro / FRaceRules::Dt);
	UE_LOG(LogRace, Log, TEXT("MuJoCo %s, track %s (%.1f m, %s), %d racers, seed %llu, %d names missing; bound model %s"),
		UTF8_TO_TCHAR(mj_versionString()), *Rules.Track.Name, Rules.Track.Length, *Rules.Track.Terrain, Rules.Entries.Num(), Seed, Missing, *Bound);
	return bOk && Missing == 0 && Rules.Entries.Num() > 0;
}

void URacerController::PublishHud(const mjData* d)
{
	FScopeLock L(&HudLock);
	Hud.bRace = true;
	Hud.Track = Rules.Track.Name;
	Hud.Laps = Rules.Laps;
	Hud.Seed = Rules.Seed;
	Hud.Total = Rules.Total;
	Hud.Phase = Rules.Phase;
	Hud.CountdownLeft = Rules.CountdownLeft();
	Hud.IntroLeft = Rules.IntroLeft();
	Hud.IntroSeconds = (double)Rules.IntroSteps * FRaceRules::Dt;
	Hud.bCalled = Rules.bCalled;
	Hud.TrackId = Rules.Track.Id;
	Hud.RaceTime = Rules.RaceTime();
	Hud.Steps = StepCount.load(std::memory_order_relaxed);
	Hud.Rows.SetNum(Rules.Entries.Num());
	double Mean = 0.0;
	int32 Running = 0;
	const TArray<int32> Order = Rules.Standings();
	for (int32 k = 0; k < Order.Num(); ++k)
	{
		const FRaceEntry& E = Rules.Entries[Order[k]];
		FRaceHudRow& Row = Hud.Rows[k];
		Row.Name = E.Name;
		Row.Color = E.Color;
		Row.Distance = E.Distance;
		Row.FinishTime = E.FinishTime;
		Row.Speed = E.Speed;
		Row.Lap = E.Lap;
		Row.Place = E.Place;
		Row.State = E.State;
		Row.bGettingUp = E.Racer->Recovering();
		Row.BaseBody = E.Racer->BaseBody();
		Row.PosUE = MjUtils::MjToUEPosition(d->qpos + E.Racer->RootQpos());
		if (E.FinishTime < 0.0) { Mean += E.Distance; ++Running; }
	}
	FVector2D T;
	Rules.Track.PointAt(Running ? Mean / Running : (Order.Num() ? Rules.Entries[Order[0]].Distance : 0.0), T);
	Hud.TangentUE = FVector(T.X, -T.Y, 0.0);
}

void URacerController::Finish()
{
	bReported = true;
	const FString Line = Rules.ResultLine();
	UE_LOG(LogRace, Display, TEXT("[Race] %s"), *Line);
	{
		FScopeLock L(&HudLock);
		Hud.Result = Line;
	}
	if (!bTest) return;
	// 1: not everyone finished (unless the test asked for a short race with -RaceLimit); 3: a check failed
	const bool bAllHome = Rules.Finished == Rules.Entries.Num();
	const int32 Code = CheckFailures.load() > 0 ? 3 : (!bAllHome && !bExplicitLimit) ? 1 : 0;
	UE_LOG(LogRace, Display, TEXT("[RaceTest] exit %d (%d check failures)"), Code, CheckFailures.load());
	AsyncTask(ENamedThreads::GameThread, [Code] { FPlatformMisc::RequestExitWithStatus(false, (uint8)Code); });
}

// --- testbed ------------------------------------------------------------------------------------------------------------

bool URacerController::BindTestbed(mjModel* m, mjData* d)
{
	const TCHAR* Cmdline = FCommandLine::Get();
	Home.Reset(); DumpSlots.Reset(); ReplayAct.Reset(); ReplayCtrl.Reset(); Recorded.Reset(); RecordedObs.Reset(); RecordedAct.Reset();
	RecordSteps = 0;
	FString S;
	if (FParse::Value(Cmdline, TEXT("RaceMode="), S)) Mode = S == TEXT("Replay") ? ERaceControlMode::Replay : ERaceControlMode::Policy;
	FParse::Value(Cmdline, TEXT("RaceReplay="), ReplayFile);
	FParse::Value(Cmdline, TEXT("RaceDump="), DumpFile);
	bQuitWhenDone = FParse::Param(Cmdline, TEXT("RaceQuit"));
	if (FParse::Value(Cmdline, TEXT("RaceCommand="), S, false))
	{
		TArray<FString> P;
		S.ParseIntoArray(P, TEXT(","));
		if (P.Num() == 3) Command = FVector(FCString::Atod(*P[0]), FCString::Atod(*P[1]), FCString::Atod(*P[2]));
	}

	const TSharedPtr<FJsonObject> Fp = Race::LoadJson(Fingerprint);
	if (!Fp) return false;
	RaceModel::ApplyOptions(m, *Fp->GetObjectField(TEXT("option")));
	const int32 Missing = RaceModel::ApplyNumbers(m, *Fp->GetObjectField(TEXT("model")), FString());
	mj_setConst(m, d);
	const FString Bound = RaceModel::Save(m, TEXT("model_bound.mjb"));
	UE_LOG(LogRace, Log, TEXT("MuJoCo %s testbed, options from %s: timestep %.17g, impratio %g, iterations %d/%d; %d names missing; bound model %s"),
		UTF8_TO_TCHAR(mj_versionString()), *Fingerprint, m->opt.timestep, m->opt.impratio, m->opt.iterations, m->opt.ls_iterations, Missing, *Bound);

	TUniquePtr<FGo2Racer> Racer = MakeUnique<FGo2Racer>();
	bool bOk = Racer->Bind(m, FString(), 0.27) && Missing == 0;
	Testbed = Racer.Get();

	TArray<double> Q0 = Race::Numbers(Fp->GetArrayField(TEXT("qpos_home")));
	if (Mode == ERaceControlMode::Replay)
	{
		const TSharedPtr<FJsonObject> Ref = Race::LoadJson(ReplayFile);
		if (!Ref) return false;
		for (const TSharedPtr<FJsonValue>& V : Ref->GetArrayField(TEXT("actuators")))
		{
			const int32 A = Race::Find(m, mjOBJ_ACTUATOR, m->nu, V->AsString());
			bOk &= A >= 0;
			ReplayAct.Add(A);
		}
		for (const TSharedPtr<FJsonValue>& Row : Ref->GetArrayField(TEXT("ctrl")))
			for (const TSharedPtr<FJsonValue>& V : Row->AsArray()) ReplayCtrl.Add(V->AsNumber());
		Q0 = Race::Numbers(Ref->GetArrayField(TEXT("qpos0")));
		RecordSteps = (int64)(ReplayCtrl.Num() / FMath::Max(1, ReplayAct.Num())) * Go2::Decimation;
		UE_LOG(LogRace, Log, TEXT("replay %s: %d actuators, %lld physics steps"), *ReplayFile, ReplayAct.Num(), RecordSteps);
	}
	else
	{
		double Seconds = 0.0;
		if (FParse::Value(Cmdline, TEXT("RaceRecord="), Seconds)) RecordSteps = FMath::RoundToInt64(Seconds / m->opt.timestep);
		FString Path;
		UNNEModelData* Data = FParse::Value(Cmdline, TEXT("RaceBrain="), Path) ? LoadBrainFile(Path) : Brain.Get();
		if (!Racer->Loco.Load(Data)) { UE_LOG(LogRace, Warning, TEXT("no brain: the Go2 holds its home pose")); }
		else { UE_LOG(LogRace, Log, TEXT("brain %s: %d inputs"), *Racer->Loco.Label, Racer->Loco.NumIn); }
	}

	const TArray<TSharedPtr<FJsonValue>>& Names = Fp->GetArrayField(TEXT("qpos_names"));
	for (int32 i = 0; i < Names.Num() && i < Q0.Num(); ++i)
	{
		const int32 Slot = Race::QposSlot(m, Names[i]->AsString());
		UE_CLOG(Slot < 0, LogRace, Error, TEXT("no qpos slot %s"), *Names[i]->AsString());
		bOk &= Slot >= 0;
		DumpSlots.Add(Slot);
		if (Slot >= 0) Home.Emplace(Slot, Q0[i]);
	}
	Racers.Add(MoveTemp(Racer));
	UE_LOG(LogRace, Log, TEXT("racer bound: %s, nq %d nv %d nu %d nbody %d, mode %s, command (%.2f, %.2f, %.2f), record %lld steps"),
		bOk ? TEXT("ok") : TEXT("FAILED"), m->nq, m->nv, m->nu, m->nbody,
		Mode == ERaceControlMode::Replay ? TEXT("Replay") : TEXT("Policy"), Command.X, Command.Y, Command.Z, RecordSteps);
	return bOk;
}

void URacerController::StartPose(const mjModel* m, mjData* d) const
{
	// sim.py reset(): the home keyframe, zero velocity, ctrl at the default pose, then forward
	mj_resetData(m, d);
	for (const TPair<int32, double>& Q : Home) d->qpos[Q.Key] = Q.Value;
	static const TCHAR* Names[] = { TEXT("FL_hip"), TEXT("FL_thigh"), TEXT("FL_calf"), TEXT("FR_hip"), TEXT("FR_thigh"), TEXT("FR_calf"),
		TEXT("RL_hip"), TEXT("RL_thigh"), TEXT("RL_calf"), TEXT("RR_hip"), TEXT("RR_thigh"), TEXT("RR_calf") };
	for (int32 j = 0; j < Go2::Nu; ++j)
	{
		const int32 A = Race::Find(m, mjOBJ_ACTUATOR, m->nu, Names[j]);
		if (A >= 0) d->ctrl[A] = Go2::DefaultPose[j];
	}
	mj_forward(m, d);
}

// --- the step -----------------------------------------------------------------------------------------------------------

void URacerController::ComputeAndApply(mjModel* m, mjData* d, uint8 Source)
{
	if (!bReady) return;
	const int64 Step = StepCount.load(std::memory_order_relaxed);

	if (bRace)
	{
		if (!bStarted && !bGameReady.load(std::memory_order_acquire))
		{
			const double Now = FPlatformTime::Seconds();
			if (Now > WaitLogAt) { WaitLogAt = Now + 10.0; UE_LOG(LogRace, Log, TEXT("race: waiting for the first drawn frame")); }
			return;	// the model runs uncontrolled meanwhile; Setup resets it completely
		}
		if (!bStarted)
		{
			Rules.Setup(m, d, RequestedLaps);
			bStarted = true;
			UE_LOG(LogRace, Log, TEXT("race: %s, %d laps, %.1f m, seed %llu"), *Rules.Track.Name, Rules.Laps, Rules.Total, Rules.Seed);
		}
		if (!Rules.Over())
		{
			Rules.PreStep(m, d);
			Rules.Control(m, d);
		}
		else
		{
			for (FRaceEntry& E : Rules.Entries) { E.Racer->Target[0] = E.Racer->Target[1] = E.Racer->Target[2] = 0.0; E.Racer->Control(m, d); }
			if (!bReported) Finish();
		}
		++StepCount;
		if (Step % 5 == 0 || Rules.Over()) PublishHud(d);
		return;
	}

	// testbed
	if (Step == 0) StartPose(m, d);
	if (RecordSteps > 0 && !bDumped && Step <= RecordSteps)	// qpos before this step; sample RecordSteps is the final state
	{
		for (const int32 Slot : DumpSlots) Recorded.Add(Slot >= 0 ? d->qpos[Slot] : 0.0);
		if (Step == RecordSteps) WriteDump(m);
	}
	if (Mode == ERaceControlMode::Replay)
	{
		const int64 C = Step / Go2::Decimation;
		const int32 N = ReplayAct.Num();
		if (N > 0 && (C + 1) * N <= ReplayCtrl.Num())
			for (int32 a = 0; a < N; ++a) d->ctrl[ReplayAct[a]] = ReplayCtrl[C * N + a];
	}
	else
	{
		FGo2Racer& R = *Testbed;
		R.Target[0] = Command.X;
		R.Target[1] = Command.Y;
		R.Target[2] = Command.Z;
		R.Control(m, d);
		if (R.bDecided && RecordSteps > 0 && !bDumped)
		{
			RecordedObs.Append(R.Obs, Go2::ObsJoystick);
			RecordedAct.Append(R.LastAction, Go2::Nu);
		}
	}
	++StepCount;
}

void URacerController::WriteDump(const mjModel* m)
{
	bDumped = true;
	const int32 Nq = DumpSlots.Num();
	const int32 Steps = Recorded.Num() / FMath::Max(1, Nq);
	FString Out = FString::Printf(TEXT("{\"mujoco\": \"%s\", \"timestep\": %.17g, \"mode\": \"%s\", \"command\": [%.9g, %.9g, %.9g],\n\"qpos\": ["),
		UTF8_TO_TCHAR(mj_versionString()), m->opt.timestep, Mode == ERaceControlMode::Replay ? TEXT("replay") : TEXT("policy"),
		Command.X, Command.Y, Command.Z);
	for (int32 s = 0; s < Steps; ++s) Out += (s ? TEXT(",\n") : TEXT("\n")) + JsonRow(Recorded.GetData() + s * Nq, Nq);
	Out += TEXT("],\n\"obs\": [");
	for (int32 k = 0; k < RecordedObs.Num() / Go2::ObsJoystick; ++k) Out += (k ? TEXT(",\n") : TEXT("\n")) + JsonRow(RecordedObs.GetData() + k * Go2::ObsJoystick, Go2::ObsJoystick);
	Out += TEXT("],\n\"action\": [");
	for (int32 k = 0; k < RecordedAct.Num() / Go2::Nu; ++k) Out += (k ? TEXT(",\n") : TEXT("\n")) + JsonRow(RecordedAct.GetData() + k * Go2::Nu, Go2::Nu);
	Out += TEXT("]}\n");
	const FString Path = FPaths::IsRelative(DumpFile) ? FPaths::Combine(FPaths::ProjectDir(), DumpFile) : DumpFile;
	const bool bSaved = FFileHelper::SaveStringToFile(Out, *Path);
	UE_LOG(LogRace, Log, TEXT("parity dump: %d steps -> %s (%s)"), Steps, *Path, bSaved ? TEXT("saved") : TEXT("SAVE FAILED"));
	if (bQuitWhenDone) AsyncTask(ENamedThreads::GameThread, [] { FPlatformMisc::RequestExit(false); });
}
