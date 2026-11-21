#include "RaceRewardConfig.h"

#include UE_INLINE_GENERATED_CPP_BY_NAME(RaceRewardConfig)

URaceRewardConfig::URaceRewardConfig()
{
	// Same order and values as training/reward_config.json "curriculum".
	AddStage(TEXT("r0"), 1.0f, TEXT("pass fraction of seeded eval episodes: stand 10 s on a zero command"));
	AddStage(TEXT("r1"), 1.0f, TEXT("pass fraction: velocity tracking error < 0.2 m/s"));
	AddStage(TEXT("r2"), 0.9f, TEXT("pass fraction: 30 N.s push + 1 kg cube drop"));
	AddStage(TEXT("r3"), 0.9f, TEXT("pass fraction: standing within 3 s from fallen (getup)"));
	AddStage(TEXT("speed"), 0.9f, TEXT("pass fraction: forward speed >= 90 % of the command"));
	AddStage(TEXT("bank"), 0.9f, TEXT("pass fraction: 15 deg slope, straight + circling"));
	AddStage(TEXT("steeple"), 0.9f, TEXT("pass fraction over 100 held-out episodes, zero NaN (graduation gate)"));
}

void URaceRewardConfig::AddStage(const TCHAR* Stage, float Threshold, const TCHAR* Metric)
{
	FRaceCurriculumStage& S = CurriculumStages.AddDefaulted_GetRef();
	S.Stage = Stage;
	S.Threshold = Threshold;
	S.Metric = Metric;
}

int32 URaceRewardConfig::FindStage(const FString& Stage) const
{
	return CurriculumStages.IndexOfByPredicate([&Stage](const FRaceCurriculumStage& S) { return S.Stage == Stage; });
}
