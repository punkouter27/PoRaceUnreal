#pragma once

// A track as data (training/tracks/<id>.json): the centre line in the MuJoCo frame (x forward, y left, metres) and
// everything that follows from it. training/racelib/track.py is the same maths.

#include "CoreMinimal.h"

class FJsonObject;

struct FRaceCurveKey
{
	double T = 0.0, V = 0.0, In = 0.0, Out = 0.0;
};

struct FRaceTrack
{
	FString Id, Name, Terrain;
	bool bClosed = false;
	int32 DefaultLaps = 1, GridSlots = 4;
	double HalfWidth = 1.65, LaneSpacing = 0.8, CheckpointSpacing = 25.0, LookAhead = 4.0;
	TArray<FVector2D> Points;
	TArray<FRaceCurveKey> LaneKeys, BankKeys;
	TArray<double> Cum;	// arc length at the start of each segment, then the total
	int32 N = 0;		// segments
	double Length = 0.0;

	bool Load(const FJsonObject& J);

	FVector2D P(int32 i) const;
	double Wrap(double S) const;
	double U(double S) const;
	FVector2D PointAt(double S, FVector2D& OutTangent) const;
	double LaneScale(double S) const;
	FVector2D LanePoint(double S, double Lane, FVector2D& OutTangent) const;
	double BankAt(double S) const;
	double BankHalfWidth() const { return HalfWidth + 0.15; }
	double SurfaceHeight(double S, double Lateral) const;
	TArray<double> LaneOffsets(int32 Num) const;

	static FVector2D Left(const FVector2D& T) { return FVector2D(-T.Y, T.X); }
	/** A Unity AnimationCurve: cubic Hermite between keys, clamped outside them. */
	static double Curve(const TArray<FRaceCurveKey>& Keys, double T, double Default);
};
