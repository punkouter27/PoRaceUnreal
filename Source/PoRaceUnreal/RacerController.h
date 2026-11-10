#pragma once

#include "CoreMinimal.h"
#include <atomic>
#include "GameFramework/GameModeBase.h"
#include "MuJoCo/Components/Controllers/MjArticulationController.h"
#include "RacerController.generated.h"

class UNNEModelData;
namespace UE::NNE { class IModelInstanceCPU; }

UENUM(BlueprintType)
enum class ERaceControlMode : uint8
{
	Policy,	// the ONNX brain through NNE, every 5th physics step (training/go2/sim.py)
	Replay	// a recorded control stream played back, qpos dumped every step (the parity gate)
};

/**
 * Drives the Go2 in a URLab articulation, on the physics thread. It mirrors training/go2/sim.py line for line:
 * the same observation, action map and timing, so a brain behaves here as it did in training.
 *
 * Command line (parity checks, training/parity_check.py drives these):
 *   -RaceMode=Replay|Policy   -RaceReplay=<json>   -RaceDump=<json>   -RaceBrain=<onnx>
 *   -RaceCommand=vx,vy,wz     -RaceRecord=<seconds>   -RaceQuit   -RaceBasicCpu
 */
UCLASS(ClassGroup = (PoRace), meta = (BlueprintSpawnableComponent))
class PORACEUNREAL_API URacerController : public UMjArticulationController
{
	GENERATED_BODY()

public:
	UPROPERTY(EditAnywhere, Category = "PoRace")
	ERaceControlMode Mode = ERaceControlMode::Policy;

	/** The model as training built it: solver options, names, home pose (training/contract.py writes it). */
	UPROPERTY(EditAnywhere, Category = "PoRace")
	FString Fingerprint = TEXT("training/models/go2_fingerprint.json");

	/** Policy: the brain (an imported .onnx). `-RaceBrain=<.onnx>` loads a file instead. */
	UPROPERTY(EditAnywhere, Category = "PoRace")
	TObjectPtr<UNNEModelData> Brain;

	/** Policy: the commanded velocity (vx m/s, vy m/s, yaw rate rad/s), slewed as in training. `-RaceCommand=` overrides. */
	UPROPERTY(EditAnywhere, Category = "PoRace")
	FVector Command = FVector(0.5, 0.0, 0.0);

	/** Replay: the control stream from training/parity_check.py, relative to the project dir. */
	UPROPERTY(EditAnywhere, Category = "PoRace")
	FString ReplayFile;

	/** Where the recorded qpos goes (replay, or policy with -RaceRecord). */
	UPROPERTY(EditAnywhere, Category = "PoRace")
	FString DumpFile = TEXT("Saved/PoRace/parity_ue.json");

	virtual void Bind(mjModel* m, mjData* d, const TMap<int32, UMjActuator*>& ActuatorIdMap) override;
	virtual void ComputeAndApply(mjModel* m, mjData* d, uint8 Source) override;
	virtual FString GetKindName() const override { return TEXT("porace"); }

	/** Physics steps since the level bound (the HUD's step counter). */
	int64 Steps() const { return StepCount.load(std::memory_order_relaxed); }

private:
	// --- the model, resolved once in Bind
	TArray<int32> Act, Qadr, Vadr;		// the 12 motors and their joints, contract order
	int32 ImuSite = -1, AdrLinvel = -1, AdrGyro = -1;
	TArray<TPair<int32, double>> Home;	// (qpos address, value): the start pose
	TArray<int32> DumpSlots;			// qpos addresses in the fingerprint's order: the dump's column order
	bool bReady = false;

	// --- brain
	TSharedPtr<UE::NNE::IModelInstanceCPU> Net;
	int32 NumIn = 0;
	UPROPERTY(Transient)
	TArray<TObjectPtr<UNNEModelData>> LoadedBrains;	// brains loaded from files, kept alive here
	TArray<float> LastAction, Action, Obs;
	float Cmd[3] = {};					// the slewed command
	bool MakeNet(UNNEModelData* Data);
	void Decide(const mjModel* m, mjData* d);

	// --- replay and recording
	TArray<int32> ReplayAct;
	TArray<double> ReplayCtrl;			// control steps x ReplayAct.Num()
	int64 RecordSteps = 0;				// physics steps to record (0 = not recording)
	TArray<double> Recorded;			// qpos before each step, DumpSlots order
	TArray<float> RecordedObs, RecordedAct;	// per decision (policy)
	bool bQuitWhenDone = false, bDumped = false;
	void StartPose(const mjModel* m, mjData* d) const;
	void WriteDump(const mjModel* m);

	std::atomic<int64> StepCount = 0;
};

/** Nothing to possess: MuJoCo owns the racers, the cameras are placed by the level. */
UCLASS()
class PORACEUNREAL_API ARaceGameMode : public AGameModeBase
{
	GENERATED_BODY()

public:
	ARaceGameMode() { DefaultPawnClass = nullptr; }
};
