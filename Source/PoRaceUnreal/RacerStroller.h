#pragma once

// The stroller, a wheeled racer, in a shared race model. training/racelib/stroller.py is the same class line for line:
// one rolling brain (training/stroller/env.py) that steers the front wheel and drives the two rear wheels; no get-up
// (a tipped stroller lies there until the 5 s reset).

#include "CoreMinimal.h"
#include "Racer.h"

class FJsonObject;

class FStrollerRacer : public FRacer
{
public:
	static constexpr int32 Decimation = 5;
	static constexpr int32 NumObs = 20, NumAct = 3;
	static constexpr double TipUpZ = 0.5;			// chassis up z below this = tipped (training ended the episode)
	static constexpr double WheelObsScale = 0.1;

	FRaceBrain Loco;
	float Cmd[3] = {}, LastAction[NumAct] = {}, Obs[NumObs] = {};

	/** Card (training/characters/stroller.json): root body, home height, steer and torque scales. */
	bool Bind(const mjModel* m, const FString& InPrefix, const FJsonObject& Card);

	virtual bool UpdateState(const mjModel* m, mjData* d) override;
	virtual void Control(const mjModel* m, mjData* d) override;
	virtual void ResetToSpawn(const mjModel* m, mjData* d) override;
	virtual void KnockOver(const mjModel* m, mjData* d) override;
	virtual void RestartCommandRamp() override { Cmd[0] = Cmd[1] = Cmd[2] = 0.f; }
	virtual double CmdX() const override { return (double)Cmd[0]; }
	virtual bool Locomoting() const override { return true; }
	virtual bool Recovering() const override { return State == ERacerState::Fallen; }

	double UpZ(const mjData* d) const { return d->sensordata[AdrUp + 2]; }
	/** Joint angles for the skin: steer, front, rear left, rear right (rad). */
	void WheelAngles(const mjData* d, double Out[4]) const { for (int32 k = 0; k < 4; ++k) Out[k] = d->qpos[Qadr[k]]; }

private:
	int32 Act[NumAct] = { -1, -1, -1 };
	float ActScale[NumAct] = {};
	int32 Qadr[4] = { -1, -1, -1, -1 };	// steer, wheel_front, wheel_rear_l, wheel_rear_r
	int32 Vadr[4] = { -1, -1, -1, -1 };
	int32 Imu = -1, AdrLinvel = -1, AdrGyro = -1, AdrUp = -1;
	int64 StepPhase = 0;

	void Clear();
	void Decide(const mjModel* m, mjData* d);
};
