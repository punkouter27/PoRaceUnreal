#pragma once

#include "CoreMinimal.h"
#include <atomic>
#include "GameFramework/GameModeBase.h"
#include "MuJoCo/Components/Controllers/MjArticulationController.h"
#include "RaceRules.h"
#include "RacerController.generated.h"

class UNNEModelData;

UENUM(BlueprintType)
enum class ERaceControlMode : uint8
{
	Policy,	// brains drive the racers (a race, or the testbed's single Go2)
	Replay	// testbed: a recorded control stream played back, qpos dumped every step (the parity gate)
};

/** One racer as the HUD and the camera see it (copied from the physics thread under a lock). */
struct FRaceHudRow
{
	FString Name;
	FLinearColor Color = FLinearColor::White;
	double Distance = 0.0, FinishTime = -1.0, Speed = 0.0;
	int32 Lap = 0, Place = 0, BaseBody = -1;
	ERacerState State = ERacerState::Racing;
	bool bGettingUp = false;
	FString Intent;							// tactics: "PASS L" / "PASS R" / "AVOID" / "BLOCK" / ""
	double HeadStart = 0.0;					// the handicap's head start (m)
	FVector PosUE = FVector::ZeroVector;	// base body, Unreal cm
};

struct FRaceHud
{
	bool bRace = false;
	FString Track;
	int32 Laps = 1;
	uint64 Seed = 0;
	double Total = 0.0;
	ERacePhase Phase = ERacePhase::Countdown;
	double CountdownLeft = 0.0, RaceTime = 0.0;
	double IntroLeft = 0.0, IntroSeconds = 0.0;	// the racer intro before the countdown
	bool bCalled = false;						// the race was called (finish window / limit): the rest are DNF
	bool bYellow = false;						// the yellow flag is out: everyone at 80 % pace
	bool bHandicap = false;						// head starts this race
	FString TrackId;
	int64 Steps = 0;
	int32 NanInfCount = 0;
	FVector TangentUE = FVector::ForwardVector;	// track direction at the pack's mean distance
	TArray<FRaceHudRow> Rows;					// standings order
	FString Result;								// the result line once the race is over
};

/**
 * The controller of a URLab articulation, on the physics thread. Two jobs:
 *  - a track model (TrackFingerprint set): every racer of the roster and the race rules (RaceRules.h), one step
 *    before each mj_step, exactly as training/race.py steps them;
 *  - the parity testbed (TrackFingerprint empty): one Go2, replayed or driven by its brain, recorded for
 *    training/parity_check.py.
 *
 * Command line:
 *   race     -RaceTest  -Seed=<n>  -Laps=<n>  -Racers=<a,b>  -RaceFlipAt=<s> [-RaceFlipCount=<n>]  -RaceLimit=<s>
 *            -NoTactics  -Handicap  -YellowFlag  -ContactGate  -RaceSelfTest
 *   testbed  -RaceMode=Replay|Policy  -RaceReplay=<json>  -RaceDump=<json>  -RaceBrain=<onnx>  -RaceCommand=vx,vy,wz
 *            -RaceRecord=<seconds>  -RaceQuit
 */
UCLASS(ClassGroup = (PoRace), meta = (BlueprintSpawnableComponent))
class PORACEUNREAL_API URacerController : public UMjArticulationController
{
	GENERATED_BODY()

public:
	UPROPERTY(EditAnywhere, Category = "PoRace")
	ERaceControlMode Mode = ERaceControlMode::Policy;

	/** A track's fingerprint (training/build_track_model.py): options, the world's numbers and the racer roster. */
	UPROPERTY(EditAnywhere, Category = "PoRace|Race")
	FString TrackFingerprint;

	/** Testbed: the creature's fingerprint (training/contract.py). */
	UPROPERTY(EditAnywhere, Category = "PoRace|Testbed")
	FString Fingerprint = TEXT("training/models/go2_fingerprint.json");

	/** Testbed: the locomotion brain (an imported .onnx). `-RaceBrain=<.onnx>` loads a file instead. */
	UPROPERTY(EditAnywhere, Category = "PoRace|Testbed")
	TObjectPtr<UNNEModelData> Brain;

	/** Testbed: the commanded velocity (vx m/s, vy m/s, yaw rate rad/s). `-RaceCommand=` overrides. */
	UPROPERTY(EditAnywhere, Category = "PoRace|Testbed")
	FVector Command = FVector(0.5, 0.0, 0.0);

	UPROPERTY(EditAnywhere, Category = "PoRace|Testbed")
	FString ReplayFile;

	UPROPERTY(EditAnywhere, Category = "PoRace|Testbed")
	FString DumpFile = TEXT("Saved/PoRace/parity_ue.json");

	virtual void Bind(mjModel* m, mjData* d, const TMap<int32, UMjActuator*>& ActuatorIdMap) override;
	virtual void ComputeAndApply(mjModel* m, mjData* d, uint8 Source) override;
	virtual FString GetKindName() const override { return TEXT("porace"); }

	/** Thread-safe copy of the race for the HUD and the camera. */
	void GetHud(FRaceHud& Out) const { FScopeLock L(&HudLock); Out = Hud; }

	/** -RaceTest: checks outside the controller (ARaceDirector) that failed; the test then exits 3. */
	static std::atomic<int32> CheckFailures;

	/** Game thread (ARaceDirector's first tick): frames are being drawn, so the race may start. Until then the
	 *  controller leaves the model alone; the race's first step resets it completely (FRaceRules::Setup), so the
	 *  wait changes nothing. Without it, a slow first frame (the editor binary scans its asset registry for a minute
	 *  before drawing) ran the countdown, and most of the race, before anyone could see it. */
	void MarkGameReady() { bGameReady.store(true, std::memory_order_release); }

	/** Racers of the track model that are not on this race's grid (fixed once bound). */
	bool IsParked(const FString& Prefix) const { return ParkedPrefixes.Contains(Prefix); }
	const TArray<int32>& ParkedRoots() const { return ParkedRootBodies; }

	/** The level's race controller: the one on a live actor of World (never a stale Blueprint copy). */
	static URacerController* Find(const UWorld* World);

	/** Request an immediate race/episode reset on the next physics step (R key). */
	void RequestRestart() { bRestartRequested.store(true, std::memory_order_release); }

	/** Cycle active policy preset index (F4 key). */
	int32 CyclePolicyOverride()
	{
		const int32 Next = (PolicyOverrideIndex.load(std::memory_order_relaxed) + 1) % 3;
		PolicyOverrideIndex.store(Next, std::memory_order_release);
		return Next;
	}
	int32 GetPolicyOverride() const { return PolicyOverrideIndex.load(std::memory_order_acquire); }

private:
	bool bReady = false, bRace = false, bTest = false, bStarted = false, bReported = false;
	std::atomic<bool> bGameReady = false;
	double IntroSeconds = -1.0;
	bool bExplicitLimit = false;
	bool bContactGate = false;
	double WaitLogAt = 0.0;
	TArray<TUniquePtr<FRacer>> Racers;	// every racer of the model, on the grid or parked
	TArray<FString> ParkedPrefixes;
	TArray<int32> ParkedRootBodies;
	class FGo2Racer* Testbed = nullptr;
	FRaceRules Rules;
	int32 RequestedLaps = 0;

	UPROPERTY(Transient)
	TArray<TObjectPtr<UNNEModelData>> LoadedBrains;	// brains loaded from files, kept alive here
	UNNEModelData* LoadBrainFile(const FString& Path);

	bool BindRace(mjModel* m, mjData* d);
	bool BindTestbed(mjModel* m, mjData* d);

	// testbed: replay and recording
	TArray<TPair<int32, double>> Home;
	TArray<int32> DumpSlots, ReplayAct;
	TArray<double> ReplayCtrl, Recorded;
	TArray<float> RecordedObs, RecordedAct;
	int64 RecordSteps = 0;
	bool bQuitWhenDone = false, bDumped = false;
	void StartPose(const mjModel* m, mjData* d) const;
	void WriteDump(const mjModel* m);

	mutable FCriticalSection HudLock;
	FRaceHud Hud;
	void PublishHud(const mjData* d);
	void Finish();

	std::atomic<int64> StepCount = 0;
	std::atomic<bool> bRestartRequested = false;
	std::atomic<int32> PolicyOverrideIndex = 0;
};

/** Nothing to possess: MuJoCo owns the racers; the HUD draws the race and ARaceDirector moves the camera. */
UCLASS()
class PORACEUNREAL_API ARaceGameMode : public AGameModeBase
{
	GENERATED_BODY()

public:
	ARaceGameMode();
};
