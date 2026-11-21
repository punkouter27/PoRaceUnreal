// Reward penalty weights and curriculum thresholds, editable in the editor (Po Game Standard C9 / C10).
// Mirrors training/reward_config.json (what the Python trainer reads); tests/test_unreal_reward_mirror.py fails when the two differ.
// Changing a value here or there does NOT retrain the shipped policies: they keep the weights they were trained with.
#pragma once

#include "CoreMinimal.h"
#include "Engine/DataAsset.h"
#include "RaceRewardConfig.generated.h"

USTRUCT(BlueprintType)
struct PORACEUNREAL_API FRaceCurriculumStage
{
	GENERATED_BODY()

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Curriculum") FString Stage;
	/** Gate value that promotes a policy past this stage (unit in Metric). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Curriculum") float Threshold = 0.f;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Curriculum") FString Metric;
};

/** Reward weights (added as weight * term, negative = penalty) and curriculum gates. */
UCLASS(BlueprintType)
class PORACEUNREAL_API URaceRewardConfig : public UPrimaryDataAsset
{
	GENERATED_BODY()

public:
	URaceRewardConfig();

	/** Joint torque squared: sum of actuator force^2. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Reward|Penalties") float TorqueSqWeight = -1e-05f;
	/** Joint angular velocity squared: sum of joint qvel^2. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Reward|Penalties") float JointAngVelSqWeight = -0.0001f;
	/** Action rate: |a_t - a_(t-1)|^2. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Reward|Penalties") float ActionRateSqWeight = -0.01f;
	/** Foot slip: planar foot speed while the foot is in contact. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Reward|Penalties") float FootSlipWeight = -0.1f;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Curriculum") TArray<FRaceCurriculumStage> CurriculumStages;

	/** Index of Stage in CurriculumStages, or INDEX_NONE. */
	UFUNCTION(BlueprintPure, Category = "Curriculum") int32 FindStage(const FString& Stage) const;

private:
	void AddStage(const TCHAR* Stage, float Threshold, const TCHAR* Metric);
};
