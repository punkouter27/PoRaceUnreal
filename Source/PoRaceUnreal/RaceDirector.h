#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "RaceRegistry.h"
#include "RacerController.h"
#include "RaceDirector.generated.h"

class ACameraActor;

UENUM(BlueprintType)
enum class ERaceCameraMode : uint8
{
	Broadcast,
	Follow,
	Orbit,
	Free
};

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
	FVector Chase = FVector(5.5, 1.2, 2.8);

	UPROPERTY(EditAnywhere, Category = "PoRace")
	float LookHeight = 0.25f;

	virtual void BeginPlay() override;
	virtual void Tick(float DeltaSeconds) override;

	ERaceCameraMode CycleCameraMode();
	void SetCameraMode(ERaceCameraMode InMode);
	ERaceCameraMode GetCameraMode() const { return CameraMode; }

private:
	TWeakObjectPtr<URacerController> Controller;
	FRaceHud Race;
	TArray<FRaceRacerInfo> Roster;	// heights for the intro shots
	bool bChaosChecked = false, bMarkerChecked = false, bHaveCamera = false, bSawRace = false, bParkedHidden = false;
	int32 Ticks = 0, ShotsTaken = 0;
	FString ShotDir;
	double QuitAt = -1.0, WaitedSeconds = 0.0;
	bool bGaveUp = false;
	ERaceCameraMode CameraMode = ERaceCameraMode::Broadcast;
	float OrbitAngleRad = 0.f;
	FVector CamPos = FVector::ZeroVector, CamFwd = FVector::ForwardVector;
	FVector FreeCamPos = FVector::ZeroVector, FreeLookOffset = FVector(600.0, 0.0, -120.0);
	void CheckChaos();
	void CheckMarkers(float DeltaSeconds);
	void Fail(const FString& What);
};
