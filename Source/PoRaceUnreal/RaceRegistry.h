#pragma once

// The roster and the track list for the menu, from the same JSON the races read (training/characters/*.json,
// training/tracks/*.json, training/models/tracks/*_fingerprint.json). A new card or track file shows up here with no
// code change: a racer as "not ready" until its card says raceable, a track as "not built" until its level exists.

#include "CoreMinimal.h"

struct FRaceTrackInfo
{
	FString Id, Name, Terrain, Level;	// Level: /Game/Levels/L_<Pascal>
	bool bClosed = false, bBuilt = false;
	double Length = 0.0;
	int32 DefaultLaps = 1;
	TArray<FString> Racers;				// racer names in the track's model (lower case)
};

struct FRaceRacerInfo
{
	FString Card, Name, Kind, Blocked, Brain;
	FLinearColor Color = FLinearColor::White;
	double Height = 0.0, Mass = 0.0;	// m, kg
	bool bReady = false;
	TArray<FString> Terrains;
};

namespace RaceRegistry
{
	/** Every track file, sorted by name; bBuilt when its level package exists. */
	TArray<FRaceTrackInfo> Tracks();
	/** Every character card, ready ones first, then by name. */
	TArray<FRaceRacerInfo> Racers();
	/** Can this racer be on this track's grid? Why it cannot, in a few words, when not. */
	bool CanRace(const FRaceRacerInfo& R, const FRaceTrackInfo& T, FString* Why = nullptr);
	const FRaceRacerInfo* FindRacer(const TArray<FRaceRacerInfo>& All, const FString& Name);
	FString LevelOf(const FString& TrackId);
}
