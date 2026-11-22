#include "RacerVisualStroller.h"

#include "AnimationRuntime.h"
#include "Components/PoseableMeshComponent.h"
#include "EngineUtils.h"
#include "RaceThirdParty.h"
RACE_MUJOCO_INCLUDES_START
#include "MuJoCo/Components/Bodies/MjBody.h"
#include "MuJoCo/Core/AMjManager.h"
#include "MuJoCo/Core/MjPhysicsEngine.h"
#include "MuJoCo/Core/MjRenderSnapshot.h"
#include "MuJoCo/Utils/MjUtils.h"
RACE_MUJOCO_INCLUDES_END
#include "RacerController.h"
#include "RaceNames.h"

namespace
{
	const TCHAR* const Bones[3] = { TEXT("wheel_front"), TEXT("wheel_rear_l"), TEXT("wheel_rear_r") };
	const TCHAR* const Bodies[3] = { TEXT("wheel_front"), TEXT("wheel_rear_l"), TEXT("wheel_rear_r") };

	/** Forward (front hub - rear axle middle) and left (rear left - rear right) as a rotation. */
	FQuat HubFrame(const FVector& Front, const FVector& RearL, const FVector& RearR)
	{
		return FRotationMatrix::MakeFromXY(Front - 0.5 * (RearL + RearR), RearL - RearR).ToQuat();
	}
}

ARacerVisualStroller::ARacerVisualStroller()
{
	PrimaryActorTick.bCanEverTick = true;
	PrimaryActorTick.TickGroup = TG_PostPhysics;
	Mesh = CreateDefaultSubobject<UPoseableMeshComponent>(TEXT("Mesh"));
	Mesh->SetCollisionEnabled(ECollisionEnabled::NoCollision);	// Chaos stays out: MuJoCo owns all contact
	Mesh->SetSimulatePhysics(false);
	Mesh->SetBoundsScale(2.f);
	RootComponent = Mesh;
}

bool ARacerVisualStroller::Init()
{
	AAMjManager* Manager = AAMjManager::GetManager();
	const mjModel* m = Manager && Manager->PhysicsEngine ? Manager->PhysicsEngine->GetModel() : nullptr;
	USkinnedAsset* Asset = Mesh->GetSkinnedAsset();
	if (!m || !Asset) return false;
	Chassis = Race::Find(m, mjOBJ_BODY, m->nbody, Prefix + TEXT("chassis"));
	if (Chassis < 0) return false;
	RootBody = m->body_rootid[Chassis];

	const FReferenceSkeleton& Ref = Asset->GetRefSkeleton();
	RefLocal = Ref.GetRefBonePose();
	FAnimationRuntime::FillUpComponentSpaceTransforms(Ref, RefLocal, RestCS);

	// MuJoCo zero pose (kinematics only): each hub relative to the chassis, in the chassis frame, UE axes and cm
	mjData* d = mj_makeData(m);
	mj_resetData(m, d);
	mj_kinematics(m, d);
	const FVector C0 = MjUtils::MjToUEPosition(d->xpos + 3 * Chassis);
	const FQuat R0 = MjUtils::MjToUERotation(d->xquat + 4 * Chassis);
	FVector BodyHub[3], MeshHub[3];
	bool bOk = true;
	for (int32 k = 0; k < 3; ++k)
	{
		WheelBody[k] = Race::Find(m, mjOBJ_BODY, m->nbody, Prefix + Bodies[k]);
		WheelRef[k] = Ref.FindBoneIndex(FName(Bones[k]));
		if (WheelBody[k] < 0 || WheelRef[k] == INDEX_NONE)
		{
			UE_LOG(LogRace, Error, TEXT("stroller visual %s: body %s (%d) or bone %s missing"), *Prefix, Bodies[k], WheelBody[k], Bones[k]);
			bOk = false;
			continue;
		}
		BodyHub[k] = R0.Inverse() * (MjUtils::MjToUEPosition(d->xpos + 3 * WheelBody[k]) - C0);
		MeshHub[k] = RestCS[WheelRef[k]].GetLocation();
	}
	mj_deleteData(d);
	if (!bOk) return false;

	MeshToBody = HubFrame(BodyHub[0], BodyHub[1], BodyHub[2]) * HubFrame(MeshHub[0], MeshHub[1], MeshHub[2]).Inverse();
	// scale check: the hub spacing on the mesh against the bodies (a 100x import shows here)
	const double MeshTrack = (MeshHub[1] - MeshHub[2]).Size(), BodyTrack = (BodyHub[1] - BodyHub[2]).Size();
	const FVector MeshMid = 0.5 * (MeshHub[1] + MeshHub[2]), BodyMid = 0.5 * (BodyHub[1] + BodyHub[2]);
	MeshOffset = BodyMid - MeshToBody * MeshMid;
	bReady = true;
	UE_LOG(LogRace, Log, TEXT("stroller visual %s: mesh-to-chassis %s, offset %s cm; rear track %.1f cm on the mesh vs %.1f cm between the bodies"),
		*Prefix, *MeshToBody.Rotator().ToString(), *MeshOffset.ToString(), MeshTrack, BodyTrack);
	return true;
}

void ARacerVisualStroller::HideBodies()
{
	AAMjManager* Manager = AAMjManager::GetManager();
	const mjModel* m = Manager && Manager->PhysicsEngine ? Manager->PhysicsEngine->GetModel() : nullptr;
	if (!m || RootBody < 0) return;
	int32 Hidden = 0;
	for (TActorIterator<AActor> It(GetWorld()); It; ++It)
	{
		TInlineComponentArray<UMjBody*> Found(*It);
		for (UMjBody* B : Found)
		{
			const int32 Id = B->GetMj().id;
			if (Id > 0 && Id < m->nbody && m->body_rootid[Id] == RootBody) { B->SetVisibility(false, true); ++Hidden; }
		}
	}
	bHidden = true;
	UE_LOG(LogRace, Log, TEXT("stroller visual %s: hid %d drawn MuJoCo bodies (the scan replaces them)"), *Prefix, Hidden);
}

void ARacerVisualStroller::Tick(float DeltaSeconds)
{
	Super::Tick(DeltaSeconds);
	if (!bReady && !Init()) return;
	if (!bHidden) HideBodies();
	if (URacerController* C = URacerController::Find(GetWorld()))
	{
		const bool bParked = C->IsParked(Prefix);
		if (bParked != bParkedHidden) { bParkedHidden = bParked; Mesh->SetVisibility(!bParked); }
		if (bParked) return;
	}
	AAMjManager* Manager = AAMjManager::GetManager();
	if (!Manager || !Manager->PhysicsEngine) return;
	const FReferenceSkeleton& Ref = Mesh->GetSkinnedAsset()->GetRefSkeleton();
	TArray<FTransform>& Local = Mesh->BoneSpaceTransforms;
	bool bPosed = false;
	Manager->PhysicsEngine->WithRenderState([&](const FMjRenderSnapshot& S)
	{
		if (S.XPos.Num() < 3 * (Chassis + 1) || S.XQuat.Num() < 4 * (WheelBody[2] + 1)) return;
		const FQuat Rot = MjUtils::MjToUERotation(&S.XQuat[4 * Chassis]);
		const FVector Pos = MjUtils::MjToUEPosition(&S.XPos[3 * Chassis]);
		SetActorLocationAndRotation(Pos + Rot * MeshOffset, Rot * MeshToBody);
		CompSpace = RestCS;
		for (int32 k = 0; k < 3; ++k)
		{
			// the wheel's turn relative to the chassis (spin, and steer for the front), expressed in mesh axes
			const FQuat Rel = Rot.Inverse() * MjUtils::MjToUERotation(&S.XQuat[4 * WheelBody[k]]);
			const int32 i = WheelRef[k];
			CompSpace[i].SetRotation(MeshToBody.Inverse() * Rel * MeshToBody * RestCS[i].GetRotation());
		}
		for (int32 i = 0; i < Local.Num() && i < CompSpace.Num(); ++i)
		{
			const int32 P = Ref.GetParentIndex(i);
			Local[i] = P == INDEX_NONE ? CompSpace[i] : CompSpace[i].GetRelativeTransform(CompSpace[P]);
		}
		bPosed = true;
	});
	if (bPosed) Mesh->MarkRefreshTransformDirty();
	if (bPosed && ++Frames == 120)
		UE_LOG(LogRace, Log, TEXT("stroller visual %s: at %s, front wheel bone %s; bounds r %.0f, visible %d, mesh %s"),
			*Prefix, *GetActorLocation().ToString(), *Mesh->GetBoneLocation(TEXT("wheel_front")).ToString(), Mesh->Bounds.SphereRadius,
			Mesh->IsVisible(), *GetNameSafe(Mesh->GetSkinnedAsset()));
}
