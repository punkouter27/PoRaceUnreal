#pragma once

// One Go2 in a shared race model: its two brains, the get-up switch and the auto-reset.
// training/racelib/go2racer.py is the same class line for line; the brain loop is training/go2/sim.py's, which the
// parity gate proved equal to training (docs/20261110/slice1.md).

#include "CoreMinimal.h"
#include <mujoco/mujoco.h>
#include "RaceContract.gen.h"

class UNNEModelData;
namespace UE::NNE { class IModelInstanceCPU; }

/** An ONNX brain on NNE's ORT CPU runtime: float32 observation in, float32 action out. */
struct FRaceBrain
{
	TSharedPtr<UE::NNE::IModelInstanceCPU> Net;
	int32 NumIn = 0;
	FString Label;

	bool Load(UNNEModelData* Data);
	bool IsValid() const { return Net.IsValid(); }
	bool Run(const float* Obs, float* Action, int32 NumAction) const;
};

enum class ERacerState : uint8 { Racing, Stumble, Fallen };
enum class ERacerMode : uint8 { Loco, Getup };

class FGo2Racer
{
public:
	static constexpr int32 Nu = RaceContract::Go2::Nu;
	// Timers in physics steps (go2racer.py)
	static constexpr int32 FallenSteps = 1250;		// 5 s down -> reset to the last checkpoint
	static constexpr int32 StallSteps = 2500;		// 10 s barely moving while asked to move -> reset
	static constexpr double StallSpeed = 0.05;		// m/s
	static constexpr int32 UprightDecisions = 25;	// the get-up hands back after 25 straight decisions with up z > 0.9
	static constexpr double UprightZ = 0.9, StumbleZ = 0.7;

	FString Prefix;
	double HomeHeight = 0.27;
	FRaceBrain Loco, Getup;

	// the race's side
	double Target[3] = {};			// command (vx m/s, vy m/s, yaw rate rad/s); slewed into Cmd
	double Spawn[3] = { 0.0, 0.0, 0.27 };
	double SpawnYaw = 0.0;
	int32 Resets = 0;
	ERacerState State = ERacerState::Racing;
	ERacerMode Mode = ERacerMode::Loco;

	// the brain's side
	float Cmd[3] = {};
	float LastAction[Nu] = {};
	float Obs[RaceContract::Go2::ObsJoystick] = {};	// the last decision's observation (loco: 48, get-up: the first 42)
	bool bDecided = false;						// this step made a decision (the parity recorder reads Obs and LastAction)

	/** Resolves this racer's model addresses (Prefix + training names). False when any is missing. */
	bool Bind(const mjModel* m, const FString& InPrefix, double InHomeHeight);

	/** Race state from the up vector; resets after 5 s down or 10 s stalled. True = it reset. */
	bool UpdateState(const mjModel* m, mjData* d);
	/** A brain decision every Decimation physics steps, counted from the last reset. */
	void Control(const mjModel* m, mjData* d);

	void ResetToSpawn(const mjModel* m, mjData* d);
	void KnockOver(const mjModel* m, mjData* d);
	void RestartCommandRamp() { Cmd[0] = Cmd[1] = Cmd[2] = 0.f; }

	double UpZ(const mjData* d) const { return d->sensordata[AdrUp + 2]; }
	FVector2D Pos(const mjData* d) const { return FVector2D(d->qpos[RootQ], d->qpos[RootQ + 1]); }
	double Yaw(const mjData* d) const;
	double PlanarSpeed2(const mjData* d) const;
	bool Locomoting() const { return Mode == ERacerMode::Loco; }
	int32 BaseBody() const { return Base; }
	int32 RootQpos() const { return RootQ; }

private:
	int32 Act[Nu] = {}, Qadr[Nu] = {}, Vadr[Nu] = {};
	int32 Base = -1, RootQ = -1, RootV = -1, Imu = -1, AdrLinvel = -1, AdrGyro = -1, AdrUp = -1;
	int64 Phase = 0;			// physics steps since the last reset
	int32 UprightCount = 0, FallenFor = 0, StalledFor = 0;

	void Clear();
	void Decide(const mjModel* m, mjData* d);
};
