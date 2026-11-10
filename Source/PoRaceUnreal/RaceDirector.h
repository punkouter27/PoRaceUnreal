#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "RacerController.h"
#include "RaceDirector.generated.h"

class ACameraActor;

/**
 * Game-thread side of the race: the chase camera on the pack, and two checks the race test gates on.
 *   marker check  MuJoCo metres -> Unreal centimetres with Y mirrored: three reference points through URLab's
 *                 conversion, and every racer's drawn base body against its MuJoCo position (during the countdown,
 *                 when the racers stand still)
 *   Chaos check   no primitive component in the level simulates physics (MuJoCo owns all of it)
 * Failures are logged as "[Check] ... FAIL" and make -RaceTest exit 3. Slice 7 grows this into the broadcast director.
 */
UCLASS()
class PORACEUNREAL_API ARaceDirector : public AActor
{
	GENERATED_BODY()

public:
	ARaceDirector();

	UPROPERTY(EditAnywhere, Category = "PoRace")
	TObjectPtr<ACameraActor> Camera;

	/** Chase offsets, metres: behind the pack, above it, and the height the camera looks at. */
	UPROPERTY(EditAnywhere, Category = "PoRace")
	FVector Chase = FVector(4.5, 1.2, 1.8);

	UPROPERTY(EditAnywhere, Category = "PoRace")
	float LookHeight = 0.25f;

	virtual void BeginPlay() override;
	virtual void Tick(float DeltaSeconds) override;

private:
	TWeakObjectPtr<URacerController> Controller;
	FRaceHud Race;
	bool bChaosChecked = false, bMarkerChecked = false, bHaveCamera = false, bSawRace = false;
	int32 Ticks = 0, ShotsTaken = 0;
	FString ShotDir;
	FVector CamPos = FVector::ZeroVector, CamFwd = FVector::ForwardVector;
	void CheckChaos();
	void CheckMarkers(float DeltaSeconds);
	void Fail(const FString& What);
};
