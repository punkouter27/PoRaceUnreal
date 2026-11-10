#include "RaceTrack.h"

#include "Dom/JsonObject.h"
#include <cmath>

namespace
{
	TArray<FRaceCurveKey> Keys(const FJsonObject& J, const TCHAR* Field)
	{
		TArray<FRaceCurveKey> Out;
		const TArray<TSharedPtr<FJsonValue>>* A;
		if (!J.TryGetArrayField(Field, A)) return Out;
		for (const TSharedPtr<FJsonValue>& V : *A)
		{
			const FJsonObject& K = *V->AsObject();
			Out.Add({ K.GetNumberField(TEXT("t")), K.GetNumberField(TEXT("v")), K.GetNumberField(TEXT("in")), K.GetNumberField(TEXT("out")) });
		}
		return Out;
	}
}

bool FRaceTrack::Load(const FJsonObject& J)
{
	Id = J.GetStringField(TEXT("id"));
	Name = J.GetStringField(TEXT("displayName"));
	Terrain = J.GetStringField(TEXT("terrain"));
	bClosed = J.GetNumberField(TEXT("closed")) != 0.0;
	DefaultLaps = (int32)J.GetNumberField(TEXT("defaultLaps"));
	HalfWidth = J.GetNumberField(TEXT("halfWidth"));
	GridSlots = (int32)J.GetNumberField(TEXT("gridSlots"));
	LaneSpacing = J.GetNumberField(TEXT("laneSpacing"));
	CheckpointSpacing = J.GetNumberField(TEXT("checkpointSpacing"));
	LookAhead = J.GetNumberField(TEXT("lookAhead"));
	Points.Reset();
	for (const TSharedPtr<FJsonValue>& V : J.GetArrayField(TEXT("centerline")))
		Points.Add(FVector2D(V->AsObject()->GetNumberField(TEXT("x")), V->AsObject()->GetNumberField(TEXT("y"))));
	LaneKeys = Keys(J, TEXT("laneScale"));
	BankKeys = Keys(J, TEXT("bankDeg"));
	if (Points.Num() < 2) return false;
	N = bClosed ? Points.Num() : Points.Num() - 1;
	Cum.Reset();
	Cum.Add(0.0);
	for (int32 i = 0; i < N; ++i)
	{
		const FVector2D A = P(i), B = P(i + 1);
		const double Dx = B.X - A.X, Dy = B.Y - A.Y;
		Cum.Add(Cum.Last() + std::sqrt(Dx * Dx + Dy * Dy));
	}
	Length = Cum.Last();
	return Length > 0.0;
}

FVector2D FRaceTrack::P(int32 i) const
{
	const int32 Num = Points.Num();
	return bClosed ? Points[((i % Num) + Num) % Num] : Points[FMath::Clamp(i, 0, Num - 1)];
}

double FRaceTrack::Wrap(double S) const
{
	const double R = std::fmod(S, Length);
	return R < 0.0 ? R + Length : R;
}

double FRaceTrack::U(double S) const
{
	return bClosed ? Wrap(S) / Length : std::min(std::max(S / Length, 0.0), 1.0);
}

FVector2D FRaceTrack::PointAt(double S, FVector2D& OutTangent) const
{
	if (bClosed) S = Wrap(S);
	int32 i = 0;
	if (S >= Length) i = N - 1;
	else if (S > 0.0) { while (i < N - 1 && Cum[i + 1] <= S) ++i; }
	const FVector2D A = P(i), B = P(i + 1);
	const double Dx = B.X - A.X, Dy = B.Y - A.Y, Ln = std::sqrt(Dx * Dx + Dy * Dy);
	OutTangent = FVector2D(Dx / Ln, Dy / Ln);
	return FVector2D(A.X + OutTangent.X * (S - Cum[i]), A.Y + OutTangent.Y * (S - Cum[i]));
}

double FRaceTrack::Curve(const TArray<FRaceCurveKey>& K, double T, double Default)
{
	if (K.Num() == 0) return Default;
	if (T <= K[0].T) return K[0].V;
	if (T >= K.Last().T) return K.Last().V;
	int32 i = 0;
	while (K[i + 1].T <= T) ++i;
	const FRaceCurveKey& K0 = K[i];
	const FRaceCurveKey& K1 = K[i + 1];
	const double Dt = K1.T - K0.T;
	if (std::isinf(K0.Out) || std::isinf(K1.In)) return K0.V;	// a stepped key
	const double S = (T - K0.T) / Dt, S2 = S * S, S3 = S * S * S;
	return (2 * S3 - 3 * S2 + 1) * K0.V + (S3 - 2 * S2 + S) * Dt * K0.Out + (-2 * S3 + 3 * S2) * K1.V + (S3 - S2) * Dt * K1.In;
}

double FRaceTrack::LaneScale(double S) const { return Curve(LaneKeys, U(S), 1.0); }

FVector2D FRaceTrack::LanePoint(double S, double Lane, FVector2D& OutTangent) const
{
	const FVector2D Pt = PointAt(S, OutTangent);
	const FVector2D L = Left(OutTangent);
	const double K = Lane * LaneScale(S);
	return FVector2D(Pt.X + L.X * K, Pt.Y + L.Y * K);
}

double FRaceTrack::BankAt(double S) const { return Curve(BankKeys, U(S), 0.0); }

double FRaceTrack::SurfaceHeight(double S, double Lateral) const
{
	const double B = BankAt(S);
	if (std::abs(B) < 1e-3) return 0.0;
	// math.radians: x * (pi / 180) in double (FMath::DegreesToRadians uses a float pi)
	return std::max(0.0, BankHalfWidth() - std::copysign(1.0, B) * Lateral) * std::tan(std::abs(B) * (3.14159265358979323846 / 180.0));
}

TArray<double> FRaceTrack::LaneOffsets(int32 Num) const
{
	const double Spacing = Num > GridSlots ? std::min(LaneSpacing, 2.0 * (HalfWidth - 0.35) / (Num - 1)) : LaneSpacing;
	TArray<double> Out;
	for (int32 i = 0; i < Num; ++i) Out.Add(((Num - 1) * 0.5 - i) * Spacing);
	return Out;
}
