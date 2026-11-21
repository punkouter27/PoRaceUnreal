#pragma once

// What the race needs from any racing body in the shared model (FGo2Racer, FHumanRacer). training/racelib's racers
// have the same members (Python duck typing). Call order per physics step, before mj_step: UpdateState (the race,
// which may then reset or re-command the racer), then Control.

#include "CoreMinimal.h"
#include <atomic>
#include <mujoco/mujoco.h>

class UNNEModelData;
namespace UE::NNE { class IModelInstanceCPU; }

/** An ONNX brain on NNE's ORT CPU runtime: float32 observation in, float32 action out. */
struct FRaceBrain
{
	TSharedPtr<UE::NNE::IModelInstanceCPU> Net;
	int32 NumIn = 0;
	FString Label;
	static std::atomic<int32> NanInfCount;
	/** Inference time summed over Run() calls since the HUD last read it (physics thread -> game thread). */
	static std::atomic<uint64> InferenceCycles;
	static std::atomic<int32> InferenceCalls;

	bool Load(UNNEModelData* Data);
	bool IsValid() const { return Net.IsValid(); }
	bool Run(const float* Obs, float* Action, int32 NumAction) const;
	/** Appends zero-initialized observation inputs at the tail without reordering existing slots. */
	static void AppendZeroInitInputs(TArray<float>& Obs, int32 ExtraCount);
};

enum class ERacerState : uint8 { Racing, Stumble, Fallen };

class FRacer
{
public:
	// timers in physics steps (racelib/go2racer.py)
	static constexpr int32 FallenSteps = 1250;		// 5 s down -> reset to the last checkpoint
	static constexpr int32 StallSteps = 2500;		// 10 s barely moving while asked to move -> reset
	static constexpr double StallSpeed = 0.05;		// m/s
	static constexpr double StumbleZ = 0.7;

	virtual ~FRacer() = default;

	FString Prefix;
	double HomeHeight = 0.3;
	double Target[3] = {};			// command (vx m/s, vy m/s, yaw rate rad/s); the racer slews it
	double Spawn[3] = {};
	double SpawnYaw = 0.0;
	int32 Resets = 0;
	ERacerState State = ERacerState::Racing;
	bool bDecided = false;			// this step made a brain decision

	virtual bool UpdateState(const mjModel* m, mjData* d) = 0;	// true = it reset
	virtual void Control(const mjModel* m, mjData* d) = 0;
	virtual void ResetToSpawn(const mjModel* m, mjData* d) = 0;
	virtual void KnockOver(const mjModel* m, mjData* d) = 0;
	virtual void RestartCommandRamp() = 0;
	virtual double CmdX() const = 0;		// the slewed forward command the brain sees
	virtual bool Locomoting() const = 0;
	virtual bool Recovering() const = 0;	// HUD: getting up (Go2) or limp on the ground (human)

	/** Parked (not on the grid): floating still at Spawn, never a contact, never a brain (racelib/race.py hold_parked). */
	void Hold(mjData* d) const;

	FVector2D Pos(const mjData* d) const { return FVector2D(d->qpos[RootQ], d->qpos[RootQ + 1]); }
	double Yaw(const mjData* d) const;
	double PlanarSpeed2(const mjData* d) const;
	int32 BaseBody() const { return Base; }
	int32 RootQpos() const { return RootQ; }

protected:
	int32 Base = -1, RootQ = -1, RootV = -1;
	TArray<int32> JointDofs;	// for Hold
	/** Shared by every racer's UpdateState: fallen / stalled timers and the reset. */
	bool AutoReset(const mjModel* m, mjData* d, bool bFallen);
	int32 FallenFor = 0, StalledFor = 0;
	bool ResolveRoot(const mjModel* m, const FString& RootBody);
};
