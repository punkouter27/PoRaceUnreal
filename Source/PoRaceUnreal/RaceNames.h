#pragma once

// MuJoCo name lookup and project data files, shared by the controller, the visuals and the HUD.

#include "CoreMinimal.h"
#include "Dom/JsonObject.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "MuJoCo/Utils/MjUtils.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"

/** The game's log category. The checks grep for these lines. */
DECLARE_LOG_CATEGORY_EXTERN(LogRace, Log, All);

namespace Race
{
	inline FString Name(const mjModel* m, mjtObj Type, int32 Id) { return MjUtils::MjToString(mj_id2name(m, Type, Id)); }

	/** Model names carry URLab's "{Actor}_" prefix; a training name matches as the whole name or as a "_"-suffix. */
	inline bool Matches(const FString& Full, const FString& Short)
	{
		return Full == Short || Full.EndsWith(TEXT("_") + Short, ESearchCase::CaseSensitive);
	}

	inline int32 Find(const mjModel* m, mjtObj Type, int32 Count, const FString& Short)
	{
		for (int32 i = 0; i < Count; ++i)
		{
			if (Matches(Name(m, Type, i), Short)) return i;
		}
		return -1;
	}

	inline int32 QposWidth(const mjModel* m, int32 Joint)
	{
		return m->jnt_type[Joint] == mjJNT_FREE ? 7 : m->jnt_type[Joint] == mjJNT_BALL ? 4 : 1;
	}

	/**
	 * The qpos address of a slot named as training/contract.py names it: "joint" (a hinge), "joint[k]" (slot k of a
	 * free joint), or "@body[k]" (slot k of the first joint of that body: the Go2's root joint has no name). -1 = none.
	 */
	inline int32 QposSlot(const mjModel* m, const FString& SlotName)
	{
		FString Base = SlotName;
		int32 K = 0, Open;
		if (SlotName.EndsWith(TEXT("]")) && SlotName.FindLastChar(TEXT('['), Open))
		{
			K = FCString::Atoi(*SlotName.Mid(Open + 1));
			Base = SlotName.Left(Open);
		}
		int32 Joint = -1;
		if (Base.StartsWith(TEXT("@")))
		{
			const int32 Body = Find(m, mjOBJ_BODY, m->nbody, Base.Mid(1));
			if (Body >= 0 && m->body_jntnum[Body] > 0) Joint = m->body_jntadr[Body];
		}
		else Joint = Find(m, mjOBJ_JOINT, m->njnt, Base);
		return Joint >= 0 && K < QposWidth(m, Joint) ? m->jnt_qposadr[Joint] + K : -1;
	}

	/** A JSON file, read quietly: null when it is missing or malformed. */
	inline TSharedPtr<FJsonObject> ReadJson(const FString& Path)
	{
		FString Raw;
		TSharedPtr<FJsonObject> J;
		return FFileHelper::LoadFileToString(Raw, *Path) && FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Raw), J) ? J : nullptr;
	}

	/** A project data file by its repo-relative path (an absolute path is used as is): the source checkout, then the
	 *  packaged Content/Data/<file> (packaged builds stage the cards and fingerprints there). */
	inline TSharedPtr<FJsonObject> LoadJson(const FString& RelPath)
	{
		for (const FString& Path : { FPaths::IsRelative(RelPath) ? FPaths::Combine(FPaths::ProjectDir(), RelPath) : RelPath,
			FPaths::Combine(FPaths::ProjectContentDir(), TEXT("Data"), FPaths::GetCleanFilename(RelPath)) })
			if (TSharedPtr<FJsonObject> J = ReadJson(Path)) return J;
		UE_LOG(LogRace, Error, TEXT("Could not read %s"), *RelPath);
		return nullptr;
	}

	inline TArray<double> Numbers(const TArray<TSharedPtr<FJsonValue>>& A)
	{
		TArray<double> Out;
		Out.Reserve(A.Num());
		for (const TSharedPtr<FJsonValue>& V : A) Out.Add(V->AsNumber());
		return Out;
	}
}
