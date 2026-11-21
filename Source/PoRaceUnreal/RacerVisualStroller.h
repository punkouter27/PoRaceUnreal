#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "RacerVisualStroller.generated.h"

class UPoseableMeshComponent;

/**
 * The stroller's scanned mesh (the source FBX SK_Stroller.fbx, imported to Content/Racers), posed from its MuJoCo bodies
 * every frame (drawing only). The rig has a root bone and one bone per wheel at the hub (training/stroller/make_model.py
 * uses the same hub positions), so the mesh rides the chassis body and each wheel bone turns with its wheel body (the
 * front one also steers). Mesh-to-chassis alignment is measured at start from the three hubs, not assumed from the FBX
 * axes. URLab's drawn boxes and cylinders of this racer are hidden; the scan replaces them.
 */
UCLASS()
class PORACEUNREAL_API ARacerVisualStroller : public AActor
{
	GENERATED_BODY()

public:
	ARacerVisualStroller();

	UPROPERTY(VisibleAnywhere, Category = "PoRace")
	TObjectPtr<UPoseableMeshComponent> Mesh;

	/** The racer's MuJoCo name prefix in the track model ("stroller_"). */
	UPROPERTY(EditAnywhere, Category = "PoRace")
	FString Prefix = TEXT("stroller_");

	virtual void Tick(float DeltaSeconds) override;

private:
	bool Init();
	void HideBodies();
	bool bReady = false, bHidden = false, bParkedHidden = false;
	int32 Frames = 0;
	int32 Chassis = -1, RootBody = -1;
	int32 WheelBody[3] = { -1, -1, -1 };			// front, rear left, rear right
	int32 WheelRef[3] = { INDEX_NONE, INDEX_NONE, INDEX_NONE };
	FQuat MeshToBody = FQuat::Identity;			// mesh component space -> chassis frame (UE axes)
	FVector MeshOffset = FVector::ZeroVector;		// mesh origin in the chassis frame (cm)
	TArray<FTransform> RefLocal, RestCS, CompSpace;
};
