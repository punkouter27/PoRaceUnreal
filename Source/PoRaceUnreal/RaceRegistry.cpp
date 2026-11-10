#include "RaceRegistry.h"

#include "Dom/JsonObject.h"
#include "HAL/FileManager.h"
#include "Misc/PackageName.h"
#include "Misc/Paths.h"
#include "RaceNames.h"

namespace
{
	TArray<FString> JsonFiles(const FString& RelDir)
	{
		TArray<FString> Names;
		IFileManager::Get().FindFiles(Names, *FPaths::Combine(FPaths::ProjectDir(), RelDir, TEXT("*.json")), true, false);
		Names.Sort();
		return Names;
	}

	/** A creature fingerprint's mass: its own bodies (not the "optional" scene around it). */
	double FingerprintMass(const FString& RelPath)
	{
		if (RelPath.IsEmpty()) return 0.0;
		const TSharedPtr<FJsonObject> Fp = Race::ReadJson(FPaths::Combine(FPaths::ProjectDir(), RelPath));
		if (!Fp) return 0.0;
		double Mass = 0.0;
		if (Fp->TryGetNumberField(TEXT("mass"), Mass)) return Mass;
		const TSharedPtr<FJsonObject>* Model;
		const TSharedPtr<FJsonObject>* Bodies;
		if (!Fp->TryGetObjectField(TEXT("model"), Model) || !(*Model)->TryGetObjectField(TEXT("bodies"), Bodies)) return 0.0;
		for (const TPair<FString, TSharedPtr<FJsonValue>>& B : (*Bodies)->Values)
		{
			bool bOptional = false;
			B.Value->AsObject()->TryGetBoolField(TEXT("optional"), bOptional);
			if (!bOptional) Mass += B.Value->AsObject()->GetNumberField(TEXT("mass"));
		}
		return Mass;
	}
}

FString RaceRegistry::LevelOf(const FString& TrackId)
{
	TArray<FString> Words;
	TrackId.ParseIntoArray(Words, TEXT("_"));
	FString Pascal;
	for (const FString& W : Words) Pascal += W.Left(1).ToUpper() + W.Mid(1);
	return TEXT("/Game/Levels/L_") + Pascal;
}

TArray<FRaceTrackInfo> RaceRegistry::Tracks()
{
	TArray<FRaceTrackInfo> Out;
	for (const FString& File : JsonFiles(TEXT("training/tracks")))
	{
		const TSharedPtr<FJsonObject> J = Race::ReadJson(FPaths::Combine(FPaths::ProjectDir(), TEXT("training/tracks"), File));
		if (!J) continue;
		FRaceTrackInfo& T = Out.AddDefaulted_GetRef();
		T.Id = J->GetStringField(TEXT("id"));
		T.Name = J->GetStringField(TEXT("displayName"));
		T.Terrain = J->GetStringField(TEXT("terrain"));
		T.bClosed = J->GetNumberField(TEXT("closed")) != 0.0;
		T.DefaultLaps = (int32)J->GetNumberField(TEXT("defaultLaps"));
		const TArray<TSharedPtr<FJsonValue>>& P = J->GetArrayField(TEXT("centerline"));
		for (int32 i = 0; i + 1 < P.Num() + (T.bClosed ? 1 : 0); ++i)
		{
			const TSharedPtr<FJsonObject> A = P[i]->AsObject(), B = P[(i + 1) % P.Num()]->AsObject();
			const double Dx = B->GetNumberField(TEXT("x")) - A->GetNumberField(TEXT("x")), Dy = B->GetNumberField(TEXT("y")) - A->GetNumberField(TEXT("y"));
			T.Length += FMath::Sqrt(Dx * Dx + Dy * Dy);
		}
		T.Level = LevelOf(T.Id);
		T.bBuilt = FPackageName::DoesPackageExist(T.Level);
		if (const TSharedPtr<FJsonObject> Fp = Race::ReadJson(FPaths::Combine(FPaths::ProjectDir(), TEXT("training/models/tracks"), T.Id + TEXT("_fingerprint.json"))))
			for (const TSharedPtr<FJsonValue>& R : Fp->GetArrayField(TEXT("racers"))) T.Racers.Add(R->AsObject()->GetStringField(TEXT("name")).ToLower());
		T.bBuilt &= T.Racers.Num() > 0;
	}
	return Out;
}

TArray<FRaceRacerInfo> RaceRegistry::Racers()
{
	TArray<FRaceRacerInfo> Out;
	for (const FString& File : JsonFiles(TEXT("training/characters")))
	{
		const TSharedPtr<FJsonObject> J = Race::ReadJson(FPaths::Combine(FPaths::ProjectDir(), TEXT("training/characters"), File));
		if (!J) continue;
		FRaceRacerInfo& R = Out.AddDefaulted_GetRef();
		R.Card = FPaths::GetBaseFilename(File);
		if (!J->TryGetStringField(TEXT("racerName"), R.Name)) R.Name = J->GetStringField(TEXT("displayName"));
		J->TryGetStringField(TEXT("kind"), R.Kind);
		J->TryGetNumberField(TEXT("height"), R.Height);
		double Raceable = 0.0;
		J->TryGetNumberField(TEXT("raceable"), Raceable);
		R.bReady = Raceable != 0.0;
		J->TryGetStringField(TEXT("blockedBy"), R.Blocked);
		const TArray<TSharedPtr<FJsonValue>>* A;
		if (J->TryGetArrayField(TEXT("racerColor"), A) && A->Num() >= 3)
			R.Color = FLinearColor((float)(*A)[0]->AsNumber(), (float)(*A)[1]->AsNumber(), (float)(*A)[2]->AsNumber());
		if (J->TryGetArrayField(TEXT("terrains"), A)) for (const TSharedPtr<FJsonValue>& V : *A) R.Terrains.Add(V->AsString());
		const TSharedPtr<FJsonObject>* Brains;
		if (J->TryGetObjectField(TEXT("brains"), Brains)) (*Brains)->TryGetStringField(TEXT("flat"), R.Brain);
		FString Fp;
		J->TryGetStringField(TEXT("fingerprint"), Fp);
		R.Mass = FingerprintMass(Fp);
	}
	Out.StableSort([](const FRaceRacerInfo& A, const FRaceRacerInfo& B) { return A.bReady != B.bReady ? A.bReady : A.Name < B.Name; });
	return Out;
}

bool RaceRegistry::CanRace(const FRaceRacerInfo& R, const FRaceTrackInfo& T, FString* Why)
{
	auto No = [Why](const FString& S) { if (Why) *Why = S; return false; };
	if (!R.bReady) return No(TEXT("not ready yet"));
	if (!R.Terrains.Contains(T.Terrain)) return No(R.Terrains.Num() == 1 ? R.Terrains[0] + TEXT(" tracks only") : TEXT("not trained for ") + T.Terrain);
	if (!T.Racers.Contains(R.Name.ToLower())) return No(TEXT("not in this track's build"));
	if (Why) Why->Reset();
	return true;
}

const FRaceRacerInfo* RaceRegistry::FindRacer(const TArray<FRaceRacerInfo>& All, const FString& Name)
{
	return All.FindByPredicate([&](const FRaceRacerInfo& R) { return R.Name.Equals(Name, ESearchCase::IgnoreCase); });
}
