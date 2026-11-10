#pragma once

// The race rules, ported from the Unity MultiRaceOrchestrator. training/racelib/race.py is the same code.
// Per physics step, before mj_step: PreStep (every racer's state, then the rules), then Control (every racer's brain).
// Slice 5: tactics (pass, avoid, block, the lateral step), the yellow flag, the handicap, bump counting, the contact
// audit. The pure pieces (FYellowFlag, Tactic) are also driven without physics by SelfTest (training/selftest.py).

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
	TArray<FString> Feet;			// foot geom names (prefixed), for the contact audit
	double Pace = 1.0;				// share of the commanded speed it holds over a race (card "pace"): the handicap's expectation

	double Lane = 0.0, Speed = 0.0, Aggression = 0.0, HeadStart = 0.0;
	double SpawnS = 0.0;			// arc length (laps included) a reset puts it back to
	double Distance = 0.0, Lateral = 0.0;
	double Offset = 0.0;			// tactical offset from the racing line (+ left)
	FString Intent;					// "PASS L" / "PASS R" / "AVOID" / "BLOCK" / ""
	int32 Passing = -1;				// the racer this one is getting past (-1: none)
	int32 Segment = 0, Lap = 0, Checkpoint = 0;
	double FinishTime = -1.0;
	int32 Place = 0;
	ERacerState State = ERacerState::Racing;
	bool bDown = false;
	int32 Falls = 0, StuckSteps = 0, Unsticks = 0, UnstickChain = 0, BackoffSteps = 0, Backoffs = 0, OffTrack = 0, Passes = 0;
	double UnstickDist = 0.0;
};

/** Out when 2+ racers are down mid-race (3+ on the grid); in when fewer than 2 are down or after YellowSteps; then a
 *  cooldown so a long pile-up does not hold the field back for good (Unity proposals r3 A3). */
struct FYellowFlag
{
	static constexpr double Scale = 0.8;
	static constexpr int64 YellowSteps = 1250;		// out for at most 5 s
	static constexpr int64 CooldownSteps = 3750;	// then not again for 15 s

	bool bEnabled = false;
	bool bOut = false;
	int64 Since = -1, End = -(int64(1) << 40);
	int32 Count = 0;

	void Update(int64 Step, bool bRacing, int32 NumLive, int32 NumDown);
};

/** "No clipping", measured (Unity ContactAudit, proposals r3 B9): per contact class the deepest penetration and the
 *  longest run of steps past its limit (feet on the floor 1 cm, everything else 2.5 cm). Read only. */
struct FContactAudit
{
	enum { FootFloor, BodyFloor, RobotRobot, Self, Other, Count };
	static constexpr double FootLimit = 0.01, OtherLimit = 0.025;
	static constexpr int64 SustainSteps = 25;	// 0.1 s past the limit in a row fails -ContactGate

	TSet<int32> Roots, Feet;
	double Max[Count] = {};
	int64 Run[Count] = {}, Worst[Count] = {}, Contacts[Count] = {};
	int64 Steps = 0;

	void Bind(const mjModel* m, const TArray<struct FRaceEntry>& Entries);
	void Step(const mjModel* m, const mjData* d);
	FString Line() const;
	TArray<FString> Failures() const;
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
	// tactics (Unity MultiRaceOrchestrator.Tactic)
	static constexpr double MaxLateral = 0.25;		// m/s sideways toward the chosen line (brains trained on |vy| <= 0.8)
	static constexpr double OffsetSlew = 0.6 * Dt;	// the tactical offset moves at 0.6 m/s
	static constexpr double PassGap = 0.65, AvoidGap = 0.85, Margin = 0.45;
	static constexpr double PassClear = 1.0;			// m ahead before a pass under way lets go
	static constexpr double OvertakeHyst = 0.25;		// m apart before "who is ahead" changes

	FRaceTrack Track;
	TArray<FRaceEntry> Entries;
	TArray<FRacer*> Parked;		// racers of the track model not on the grid: held still off the track
	uint64 Seed = 1;
	int32 Laps = 1;
	double FlipAt = -1.0;
	int32 FlipCount = 1;			// racers knocked over at FlipAt: the leader, then the next in the standings
	bool bRandomizeGrid = true;
	bool bTactics = true;
	bool bHandicap = false;
	bool bAudit = false;
	int64 IntroSteps = 0;			// racers stand on the grid this long before the countdown (the racer intro)
	int64 FinishWindowSteps = 0;	// interactive: the race is called this long after the winner (0: off, as in tests)
	int64 LimitSteps = TestLimitSteps;	// the race is called this long after the start

	ERacePhase Phase = ERacePhase::Countdown;
	int64 Step = 0, RaceStart = -1;
	int32 Finished = 0, Flips = 0;
	bool bCalled = false;			// ended by the finish window or the limit: the rest are classified by distance
	int64 FirstFinish = -1;
	double Total = 0.0;
	double ImpRatio = 100.0;		// this race's (Setup)
	FYellowFlag Yellow;				// set Yellow.bEnabled before Setup
	int64 YellowSteps = 0;			// steps the flag was out
	int32 Bumps = 0;				// robot-robot contacts while racing: separate touches, and steps in contact
	int64 BumpSteps = 0;
	FContactAudit Audit;
	TArray<FString> Events;			// "<race time>s pass Blue Matt", "... yellow", "... green"

	/** Laps, the seeded draw, every racer reset onto its grid slot. Call once, before the first PreStep. */
	void Setup(const mjModel* m, mjData* d, int32 RequestedLaps);
	void PreStep(const mjModel* m, mjData* d);
	void Control(const mjModel* m, mjData* d);

	double RaceTime() const { return RaceStart >= 0 ? (double)(Step - RaceStart) * Dt : 0.0; }
	double CountdownLeft() const { return Phase == ERacePhase::Countdown ? (double)(IntroSteps + CountdownSteps - Step) * Dt : 0.0; }
	double IntroLeft() const { return Phase == ERacePhase::Countdown && Step < IntroSteps ? (double)(IntroSteps - Step) * Dt : 0.0; }
	bool Over() const { return Phase == ERacePhase::Finished; }
	/** Entry indices, best first: finishers by time, then the rest by distance; ties keep grid order. */
	TArray<int32> Standings() const;
	/** One line per race, the Unity -raceTest format (race.py result_line). */
	FString ResultLine() const;

	/** Where racer i wants to be across the track (lateral, + left); sets its Intent and Passing. */
	double Tactic(int32 i, double Line);
	/** The tactics and yellow-flag rules on made-up fields, no physics: the same lines as training/selftest.py. */
	static TArray<FString> SelfTest();

private:
	TArray<int32> RootBodies;
	TMap<int64, int32> Ahead;		// (i << 32 | j) -> +1 i ahead, -1 j ahead
	bool bInBump = false;

	void HoldParked(mjData* d) const;
	void Spawn(FRaceEntry& E, double S) const;
	void Resync(FRaceEntry& E) const;
	double Progress(FRaceEntry& E, const FVector2D& Pos, double& OutLateral) const;
	double Room(int32 i, double Lat) const;
	void DetectOvertakes();
	void CountBumps(const mjModel* m, const mjData* d);
};
