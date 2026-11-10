#pragma once

// One Go2 in a shared race model: its two brains, the get-up switch and the auto-reset.
// training/racelib/go2racer.py is the same class line for line; the brain loop is training/go2/sim.py's, which the
// parity gate proved equal to training (docs/20261110/slice1.md).

#include "CoreMinimal.h"
#include "RaceContract.gen.h"
#include "Racer.h"

enum class ERacerMode : uint8 { Loco, Getup };

class FGo2Racer : public FRacer
{
public:
	static constexpr int32 Nu = RaceContract::Go2::Nu;
	static constexpr int32 UprightDecisions = 25;	// the get-up hands back after 25 straight decisions with up z > 0.9
	static constexpr double UprightZ = 0.9;

	FRaceBrain Loco, Getup;
	ERacerMode Mode = ERacerMode::Loco;
	float Cmd[3] = {};
	float LastAction[Nu] = {};
	float Obs[RaceContract::Go2::ObsJoystick] = {};	// the last decision's observation (loco: 48, get-up: the first 42)

	/** Resolves this racer's model addresses (Prefix + training names). False when any is missing. */
	bool Bind(const mjModel* m, const FString& InPrefix, double InHomeHeight);

	virtual bool UpdateState(const mjModel* m, mjData* d) override;
	virtual void Control(const mjModel* m, mjData* d) override;
	virtual void ResetToSpawn(const mjModel* m, mjData* d) override;
	virtual void KnockOver(const mjModel* m, mjData* d) override;
	virtual void RestartCommandRamp() override { Cmd[0] = Cmd[1] = Cmd[2] = 0.f; }
	virtual double CmdX() const override { return (double)Cmd[0]; }
	virtual bool Locomoting() const override { return Mode == ERacerMode::Loco; }
	virtual bool Recovering() const override { return Mode == ERacerMode::Getup; }

	double UpZ(const mjData* d) const { return d->sensordata[AdrUp + 2]; }

private:
	int32 Act[Nu] = {}, Qadr[Nu] = {}, Vadr[Nu] = {};
	int32 Imu = -1, AdrLinvel = -1, AdrGyro = -1, AdrUp = -1;
	int64 Phase = 0;			// physics steps since the last reset
	int32 UprightCount = 0;

	void Clear();
	void Decide(const mjModel* m, mjData* d);
};
