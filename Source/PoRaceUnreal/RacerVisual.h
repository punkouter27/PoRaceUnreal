#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "RacerVisual.generated.h"

class UPoseableMeshComponent;
class USkeletalMesh;

/**
 * A human racer's skinned scan, posed from its MuJoCo bodies every frame (drawing only: never touches the physics).
 * Port of the Unity MattSkin: the MJCF was built from this rig (tools/blender/matt_mjcf.py), with every joint on its
 * bone's head, so each mapped bone's world rotation is its body's rotation times a fixed offset taken at the rest pose,
 * and the hips follow the pelvis. Every other bone keeps its rest offset from its parent, so the spine chain (four
 * bones riding one torso body) bends as one piece instead of collapsing onto the body's origin.
 * URLab's drawn collision capsules of this racer are hidden; the scan replaces them.
 */
UCLASS()
class PORACEUNREAL_API ARacerVisual : public AActor
{
	GENERATED_BODY()

public:
	ARacerVisual();

	UPROPERTY(VisibleAnywhere, Category = "PoRace")
	TObjectPtr<UPoseableMeshComponent> Mesh;

	/** The racer's MuJoCo name prefix in the track model ("matt_"). */
	UPROPERTY(EditAnywhere, Category = "PoRace")
	FString Prefix = TEXT("matt_");

	/** The pelvis body's height at the MuJoCo zero pose: where the rig's Hips head sits (creature fingerprint pelvis_rest_z). */
	UPROPERTY(EditAnywhere, Category = "PoRace")
	double PelvisRestZ = 0.96675;

	virtual void Tick(float DeltaSeconds) override;

private:
	bool Init();
	bool bReady = false, bHidden = false, bParkedHidden = false;
	int32 Frames = 0;
	TArray<int32> RefToDriven;		// reference-skeleton index -> driven index, or INDEX_NONE
	TArray<int32> BodyIds;			// per driven bone
	TArray<FQuat> Offsets;			// per driven bone: rest world rotation relative to its body's rest rotation
	int32 HipsRef = INDEX_NONE, PelvisBody = -1, RootBody = -1;
	FVector HipsOffset = FVector::ZeroVector;	// the Hips bone from the pelvis body, in the pelvis frame (cm)
	TArray<FTransform> RefLocal, CompSpace;
	TArray<FVector> RestScale;		// per reference bone: its rest scale in component space
	void HideCapsules();
};
