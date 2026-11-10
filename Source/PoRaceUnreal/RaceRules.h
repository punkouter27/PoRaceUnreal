#pragma once

// The race rules, ported from the Unity MultiRaceOrchestrator. training/racelib/race.py is the same code.
// Per physics step, before mj_step: PreStep (every racer's state, then the rules), then Control (every racer's brain).
// Tactics and the yellow flag arrive in Slice 5.

#include "CoreMinimal.h"
#include <mujoco/mujoco.h>
#include "RaceTrack.h"
#include "RaceContract.gen.h"
#include "Racer.h"

enum class ERacePhase : uint8 { Countdown, Racing, Finished };

struct FRaceEntry
{
	FString Name;
	FLinearColor Color = FLinearColor::White;
	FRacer* Racer = nullptr;
	double Cruise = 1.5, MaxYaw = 1.2;
	bool bUsesUnstick = true;
	bool bHoldsHeading = false;	// steer to the track heading during the countdown (a brain that drifts on a zero command)
	double ImpRatio = 100.0;		// the impratio its brain was trained at; the race runs at the grid's lowest

	double Lane = 0.0, Speed = 0.0, Aggression = 0.0;
	double Distance = 0.0, Lateral = 0.0;
	int32 Segment = 0, Lap = 0, Checkpoint = 0;
	double FinishTime = -1.0;
	int32 Place = 0;
	ERacerState State = ERacerState::Racing;
	bool bDown = false;
	int32 Falls = 0, StuckSteps = 0, Unsticks = 0, UnstickChain = 0, BackoffSteps = 0, Backoffs = 0, OffTrack = 0, Passes = 0;
	double UnstickDist = 0.0;
};

class FRaceRules
{
public:
	static constexpr double Dt = RaceContract::Go2::SimDt;
	static constexpr int64 CountdownSteps = 750;		// 3 s
	static constexpr double SteerGain = 1.5;
	static constexpr double SpeedSpread = 0.06;		// a race's cruise speed is drawn in [1 - spread, 1] x the racer's
	static constexpr int32 StuckSteps = 125;			// 0.5 s nearly stopped while asked for > 1 m/s -> restart the ramp
	static constexpr double StuckSpeed = 0.3;
	static constexpr int32 BackoffSteps = 300;		// 1.2 s at -0.5 m/s after six restarts gained under 0.3 m
	static constexpr double OffTrack = 1.0;			// m past the half width -> back to the last checkpoint
	static constexpr int64 TestLimitSteps = 150000;	// 600 s

	FRaceTrack Track;
	TArray<FRaceEntry> Entries;
	TArray<FRacer*> Parked;		// racers of the track model not on the grid: held still off the track
	uint64 Seed = 1;
	int32 Laps = 1;
	double FlipAt = -1.0;
	bool bRandomizeGrid = true;

	ERacePhase Phase = ERacePhase::Countdown;
	int64 Step = 0, RaceStart = -1;
	int32 Finished = 0, Flips = 0;
	double Total = 0.0;
	double ImpRatio = 100.0;		// this race's (Setup)

	/** Laps, the seeded draw, every racer reset onto its grid slot. Call once, before the first PreStep. */
	void Setup(const mjModel* m, mjData* d, int32 RequestedLaps);
	void PreStep(const mjModel* m, mjData* d);
	void Control(const mjModel* m, mjData* d);

	double RaceTime() const { return RaceStart >= 0 ? (double)(Step - RaceStart) * Dt : 0.0; }
	double CountdownLeft() const { return Phase == ERacePhase::Countdown ? (double)(CountdownSteps - Step) * Dt : 0.0; }
	bool Over() const { return Phase == ERacePhase::Finished || (RaceStart >= 0 && Step - RaceStart > TestLimitSteps); }
	/** Entry indices, best first: finishers by time, then the rest by distance; ties keep grid order. */
	TArray<int32> Standings() const;
	/** One line per race, the Unity -raceTest format (race.py result_line). */
	FString ResultLine() const;

private:
	void HoldParked(mjData* d) const;
	void Spawn(FRaceEntry& E, double S) const;
	double Progress(FRaceEntry& E, const FVector2D& Pos, double& OutLateral) const;
	int32 Leader() const;
};
