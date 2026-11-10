#pragma once

// A human racer (Matt; later Grandma) in a shared race model. training/racelib/human.py is the same class line for line:
// the G1-layout walking brain with its two-foot gait clock (training/g1/sim.py control_step), and the Unity race's
// handling of a fall (down -> limp until the 5 s reset; there is no get-up brain).

#include "CoreMinimal.h"
#include "Racer.h"

class FJsonObject;

class FHumanRacer : public FRacer
{
public:
	static constexpr double SimDt = 0.004;
	static constexpr int32 Decimation = 5;
	static constexpr float ActionScale = 0.5f;

	FRaceBrain Loco;
	TArray<float> Cmd, LastAction, Obs;	// Cmd: 3; LastAction: Nu; Obs: the last decision's (103)
	bool bLimp = false;

	/** Card (training/characters/<name>.json) for sensors, gait clock and fall rules; the creature fingerprint for
	 *  joints, actuators, the start pose and the root body. */
	bool Bind(const mjModel* m, const FString& InPrefix, const FJsonObject& Card, const FJsonObject& Creature);

	virtual bool UpdateState(const mjModel* m, mjData* d) override;
	virtual void Control(const mjModel* m, mjData* d) override;
	virtual void ResetToSpawn(const mjModel* m, mjData* d) override;
	virtual void KnockOver(const mjModel* m, mjData* d) override;
	virtual void RestartCommandRamp() override { Cmd[0] = Cmd[1] = Cmd[2] = 0.f; }
	virtual double CmdX() const override { return (double)Cmd[0]; }
	virtual bool Locomoting() const override { return true; }	// one brain: limp is a state of the body
	virtual bool Recovering() const override { return bLimp; }

	double UpZ(const mjData* d) const { return d->sensordata[AdrUp + 2]; }

private:
	int32 Nu = 0;
	TArray<int32> Act, Qadr;
	TArray<float> Default;
	int32 Imu = -1, AdrLinvel = -1, AdrGyro = -1, AdrUp = -1;
	double GaitHz = 1.375, GaitSlope = 0.0, GaitV0 = 1.2;
	double FallenPelvisZ = 0.6, FallenUpZ = 0.3;
	int32 LimpAfter = 15;

	double Phase = 0.0;		// gait clock (rad)
	int64 Decisions = 0;		// since the last reset: the phase does not advance on the first
	int64 StepPhase = 0;		// physics steps since the last reset
	int32 DownDecisions = 0;
	bool bUpright = true;

	void Clear();
	void Decide(const mjModel* m, mjData* d);
	static double Wrap(double P);
};
