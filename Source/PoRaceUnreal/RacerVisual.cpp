#include "RacerVisual.h"

#include "AnimationRuntime.h"
#include "Components/PoseableMeshComponent.h"
#include "Engine/SkeletalMesh.h"
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
	// bone (the rig's Mecanim names) -> MuJoCo body it rides on: the Unity MattSkin map, parents before children
	const TCHAR* const Map[][2] = {
		{ TEXT("Hips"), TEXT("pelvis") }, { TEXT("Spine"), TEXT("torso_link") }, { TEXT("Chest"), TEXT("torso_link") },
		{ TEXT("UpperChest"), TEXT("torso_link") }, { TEXT("Neck"), TEXT("torso_link") }, { TEXT("Head"), TEXT("torso_link") },
		{ TEXT("LeftShoulder"), TEXT("torso_link") }, { TEXT("RightShoulder"), TEXT("torso_link") },
		{ TEXT("LeftUpperArm"), TEXT("left_shoulder_yaw_link") }, { TEXT("LeftLowerArm"), TEXT("left_elbow_link") }, { TEXT("LeftHand"), TEXT("left_wrist_yaw_link") },
		{ TEXT("RightUpperArm"), TEXT("right_shoulder_yaw_link") }, { TEXT("RightLowerArm"), TEXT("right_elbow_link") }, { TEXT("RightHand"), TEXT("right_wrist_yaw_link") },
		{ TEXT("LeftUpperLeg"), TEXT("left_hip_yaw_link") }, { TEXT("LeftLowerLeg"), TEXT("left_knee_link") },
		{ TEXT("LeftFoot"), TEXT("left_ankle_roll_link") }, { TEXT("LeftToes"), TEXT("left_ankle_roll_link") },
		{ TEXT("RightUpperLeg"), TEXT("right_hip_yaw_link") }, { TEXT("RightLowerLeg"), TEXT("right_knee_link") },
		{ TEXT("RightFoot"), TEXT("right_ankle_roll_link") }, { TEXT("RightToes"), TEXT("right_ankle_roll_link") },
	};
}

ARacerVisual::ARacerVisual()
{
	PrimaryActorTick.bCanEverTick = true;
	PrimaryActorTick.TickGroup = TG_PostPhysics;
	Mesh = CreateDefaultSubobject<UPoseableMeshComponent>(TEXT("Mesh"));
	Mesh->SetCollisionEnabled(ECollisionEnabled::NoCollision);	// Chaos stays out: MuJoCo owns all contact
	Mesh->SetSimulatePhysics(false);
	Mesh->SetBoundsScale(4.f);	// the bones travel far from the component origin; keep it from being culled
	RootComponent = Mesh;
}

bool ARacerVisual::Init()
{
	AAMjManager* Manager = AAMjManager::GetManager();
	const mjModel* m = Manager && Manager->PhysicsEngine ? Manager->PhysicsEngine->GetModel() : nullptr;
	USkinnedAsset* Asset = Mesh->GetSkinnedAsset();
	if (!m || !Asset) return false;

	// MuJoCo zero pose: qpos0 (free joints at the model's placeholder pose, every hinge at 0), kinematics only
	mjData* d = mj_makeData(m);
	mj_resetData(m, d);
	mj_kinematics(m, d);
	PelvisBody = Race::Find(m, mjOBJ_BODY, m->nbody, Prefix + TEXT("pelvis"));
	if (PelvisBody < 0) { mj_deleteData(d); return false; }
	RootBody = m->body_rootid[PelvisBody];

	const FReferenceSkeleton& Ref = Asset->GetRefSkeleton();
	RefLocal = Ref.GetRefBonePose();
	TArray<FTransform> CS;
	FAnimationRuntime::FillUpComponentSpaceTransforms(Ref, RefLocal, CS);
	// a bone's rest scale in component space: the FBX root carries the unit scale (x100, bone offsets in metres below it),
	// so a driven bone must keep the accumulated scale, not its local one (Slice 3: the skin came out 1 cm tall)
	RestScale.Reset();
	for (const FTransform& T : CS) RestScale.Add(T.GetScale3D());
	RefToDriven.Init(INDEX_NONE, CS.Num());
	BodyIds.Reset();
	TArray<int32> RefIdx;
	TMap<FString, TPair<FVector, FVector>> Anchor;	// bone -> (mesh component-space position, MuJoCo zero-pose position relative to the pelvis)
	const FVector Pelvis0 = MjUtils::MjToUEPosition(d->xpos + 3 * PelvisBody);
	for (const auto& Pair : Map)
	{
		const int32 i = Ref.FindBoneIndex(FName(Pair[0]));
		const int32 b = Race::Find(m, mjOBJ_BODY, m->nbody, Prefix + Pair[1]);
		if (i == INDEX_NONE || b < 0) { UE_LOG(LogRace, Warning, TEXT("racer visual %s: bone %s or body %s missing"), *Prefix, Pair[0], Pair[1]); continue; }
		RefToDriven[i] = BodyIds.Num();
		RefIdx.Add(i);
		BodyIds.Add(b);
		Anchor.Add(Pair[0], { CS[i].GetLocation(), MjUtils::MjToUEPosition(d->xpos + 3 * b) - Pelvis0 });
		if (FString(Pair[0]) == TEXT("Hips")) HipsRef = i;
		if (FString(Pair[0]) == TEXT("Head")) HeadRef = i;
	}
	TArray<FQuat> BodyRest;
	for (const int32 b : BodyIds) BodyRest.Add(MjUtils::MjToUERotation(d->xquat + 4 * b));
	mj_deleteData(d);
	for (const TCHAR* Need : { TEXT("Hips"), TEXT("LeftUpperLeg"), TEXT("RightUpperLeg"), TEXT("LeftFoot") })
		if (!Anchor.Contains(Need)) { UE_LOG(LogRace, Error, TEXT("racer visual %s: no bone %s"), *Prefix, Need); return false; }

	// Mesh component space -> world: match up (foot -> hip) and left (right hip -> left hip) on both sides
	auto Frame = [&](bool bWorld)
	{
		auto P = [&](const TCHAR* N) { return bWorld ? Anchor[N].Value : Anchor[N].Key; };
		return FRotationMatrix::MakeFromXY(P(TEXT("LeftUpperLeg")) - P(TEXT("LeftFoot")), P(TEXT("LeftUpperLeg")) - P(TEXT("RightUpperLeg"))).ToQuat();
	};
	const FQuat MeshToWorld = Frame(true) * Frame(false).Inverse();
	const double LegMesh = (Anchor[TEXT("LeftUpperLeg")].Key - Anchor[TEXT("LeftFoot")].Key).Size();
	const double LegBody = (Anchor[TEXT("LeftUpperLeg")].Value - Anchor[TEXT("LeftFoot")].Value).Size();
	Offsets.Reset();
	for (int32 k = 0; k < BodyIds.Num(); ++k) Offsets.Add(BodyRest[k].Inverse() * MeshToWorld * CS[RefIdx[k]].GetRotation());
	// the Hips bone from the pelvis body at the rest pose: the mesh stands on the floor, the pelvis body at PelvisRestZ
	HipsOffset = BodyRest[RefToDriven[HipsRef]].Inverse() * (MeshToWorld * CS[HipsRef].GetLocation() - FVector(0.0, 0.0, PelvisRestZ * 100.0));
	bReady = true;
	UE_LOG(LogRace, Log, TEXT("racer visual %s: %d bones driven, mesh-to-world %s, leg %.1f cm on the mesh vs %.1f cm between the bodies, hips %.1f cm from the pelvis body, root bone scale %s"),
		*Prefix, BodyIds.Num(), *MeshToWorld.Rotator().ToString(), LegMesh, LegBody, HipsOffset.Size(), *RestScale[0].ToString());
	return true;
}

void ARacerVisual::HideCapsules()
{
	// URLab draws every geom; the scan replaces this racer's collision capsules
	AAMjManager* Manager = AAMjManager::GetManager();
	const mjModel* m = Manager && Manager->PhysicsEngine ? Manager->PhysicsEngine->GetModel() : nullptr;
	if (!m || RootBody < 0) return;
	int32 Hidden = 0;
	for (TActorIterator<AActor> It(GetWorld()); It; ++It)
	{
		TInlineComponentArray<UMjBody*> Bodies(*It);
		for (UMjBody* B : Bodies)
		{
			const int32 Id = B->GetMj().id;
			if (Id > 0 && Id < m->nbody && m->body_rootid[Id] == RootBody) { B->SetVisibility(false, true); ++Hidden; }
		}
	}
	bHidden = true;
	UE_LOG(LogRace, Log, TEXT("racer visual %s: hid %d drawn MuJoCo bodies (the scan replaces them)"), *Prefix, Hidden);
}

void ARacerVisual::Tick(float DeltaSeconds)
{
	Super::Tick(DeltaSeconds);
	if (!bReady && !Init()) return;
	if (!bHidden) HideCapsules();

	// a racer parked off the grid is not drawn
	if (URacerController* C = URacerController::Find(GetWorld()))
	{
		const bool bParked = C->IsParked(Prefix);
		if (bParked != bParkedHidden) { bParkedHidden = bParked; Mesh->SetVisibility(!bParked); }
		if (bParked) return;
	}

	AAMjManager* Manager = AAMjManager::GetManager();
	if (!Manager || !Manager->PhysicsEngine) return;
	// the actor travels with the pelvis, so the mesh's bounds (and its culling) go where he goes; the bones are posed
	// relative to wherever the component is
	Manager->PhysicsEngine->WithRenderState([&](const FMjRenderSnapshot& S)
	{
		if (S.XPos.Num() > 3 * PelvisBody + 2) SetActorLocation(MjUtils::MjToUEPosition(&S.XPos[3 * PelvisBody]));
	});
	const FTransform ToComponent = Mesh->GetComponentTransform().Inverse();
	const FReferenceSkeleton& Ref = Mesh->GetSkinnedAsset()->GetRefSkeleton();
	TArray<FTransform>& Local = Mesh->BoneSpaceTransforms;
	bool bPosed = false;
	const mjModel* Model = Manager->PhysicsEngine->GetModel();
	Manager->PhysicsEngine->WithRenderState([&](const FMjRenderSnapshot& S)
	{
		if (S.XPos.Num() < 3 * (PelvisBody + 1)) return;
		CompSpace.SetNum(Local.Num());
		for (int32 i = 0; i < Local.Num(); ++i)
		{
			const int32 P = Ref.GetParentIndex(i);
			const int32 k = RefToDriven[i];
			if (k == INDEX_NONE)	// not driven: its rest offset from its parent
			{
				CompSpace[i] = P == INDEX_NONE ? RefLocal[i] : RefLocal[i] * CompSpace[P];
				Local[i] = RefLocal[i];
				continue;
			}
			const int32 b = BodyIds[k];
			const FQuat World = MjUtils::MjToUERotation(&S.XQuat[4 * b]) * Offsets[k];
			FVector Loc;
			if (i == HipsRef)	// the hips follow the pelvis body
			{
				const FQuat PelvisRot = MjUtils::MjToUERotation(&S.XQuat[4 * PelvisBody]);
				Loc = ToComponent.TransformPosition(MjUtils::MjToUEPosition(&S.XPos[3 * PelvisBody]) + PelvisRot * HipsOffset);
			}
			else Loc = P == INDEX_NONE ? RefLocal[i].GetLocation() : CompSpace[P].TransformPosition(RefLocal[i].GetLocation());
			CompSpace[i] = FTransform(ToComponent.GetRotation() * World, Loc, RestScale[i]);
			Local[i] = P == INDEX_NONE ? CompSpace[i] : CompSpace[i].GetRelativeTransform(CompSpace[P]);
		}
		ApplyGaze(S, Model, ToComponent, DeltaSeconds);
		bPosed = true;
	});
	if (bPosed) Mesh->MarkRefreshTransformDirty();
	if (bPosed && (Frames + 1) % 600 == 120)	// every 10 s from 2 s in: what the render-only gaze is doing
	{
		const mjModel* m = Manager->PhysicsEngine->GetModel();
		const char* Target = GazeTarget >= 0 && m ? mj_id2name(m, mjOBJ_BODY, GazeTarget) : nullptr;
		UE_LOG(LogRace, Log, TEXT("racer visual %s: gaze target %s, head turned %.1f deg off the torso (max %.0f)"), *Prefix,
			Target ? *FString(UTF8_TO_TCHAR(Target)) : TEXT("ahead"), GetGazeDegrees(), GazeMaxDegrees);
	}
	if (bPosed && ++Frames == 120)	// one look at what the skin is doing, two seconds in
	{
		const mjModel* m = Manager->PhysicsEngine->GetModel();
		FVector Pelvis = FVector::ZeroVector;
		Manager->PhysicsEngine->WithRenderState([&](const FMjRenderSnapshot& S) { if (S.XPos.Num() > 3 * PelvisBody + 2) Pelvis = MjUtils::MjToUEPosition(&S.XPos[3 * PelvisBody]); });
		UE_LOG(LogRace, Log, TEXT("racer visual %s: pelvis body at %s; Hips bone %s, Head %s, LeftFoot %s; bounds %s r %.0f; visible %d, hidden in game %d, mesh %s, material %s, LODs %d"),
			*Prefix, *Pelvis.ToString(), *Mesh->GetBoneLocation(TEXT("Hips")).ToString(), *Mesh->GetBoneLocation(TEXT("Head")).ToString(),
			*Mesh->GetBoneLocation(TEXT("LeftFoot")).ToString(), *Mesh->Bounds.Origin.ToString(), Mesh->Bounds.SphereRadius,
			Mesh->IsVisible(), Mesh->bHiddenInGame, *GetNameSafe(Mesh->GetSkinnedAsset()), *GetNameSafe(Mesh->GetMaterial(0)),
			Mesh->GetSkinnedAsset() ? Mesh->GetSkinnedAsset()->GetLODNum() : -1);
	}
}

void ARacerVisual::ApplyGaze(const FMjRenderSnapshot& S, const mjModel* m, const FTransform& ToComponent, float DeltaSeconds)
{
	// Render-only gaze: MuJoCo has no neck joint for this racer, so the Head bone (riding the torso body) is turned
	// toward the nearest rival ahead. Nothing here touches the simulation.
	if (!m || HeadRef == INDEX_NONE || !CompSpace.IsValidIndex(HeadRef)) return;
	const int32 k = RefToDriven[HeadRef];
	if (k == INDEX_NONE || S.XQuat.Num() < 4 * (BodyIds[k] + 1)) return;
	const FTransform ToWorld = ToComponent.Inverse();
	const FVector HeadWorld = ToWorld.TransformPosition(CompSpace[HeadRef].GetLocation());
	const FVector Facing = MjUtils::MjToUERotation(&S.XQuat[4 * BodyIds[k]]).RotateVector(FVector::ForwardVector).GetSafeNormal();
	if (Facing.IsNearlyZero()) return;

	// nearest other racer (a free root body) in front of the torso and within range
	GazeTarget = -1;
	double Best = FMath::Square(static_cast<double>(GazeRange));
	FVector Look = Facing;
	for (int32 b = 1; b < m->nbody && 3 * b + 2 < S.XPos.Num(); ++b)
	{
		if (m->body_parentid[b] != 0 || b == RootBody || m->body_jntnum[b] == 0) continue;
		const FVector To = MjUtils::MjToUEPosition(&S.XPos[3 * b]) - HeadWorld;
		const double D2 = To.SizeSquared();
		if (D2 < Best && D2 > 1.0 && FVector::DotProduct(To.GetSafeNormal(), Facing) > 0.2)
		{
			Best = D2;
			GazeTarget = b;
			Look = To.GetSafeNormal();
		}
	}
	FQuat Want = FQuat::FindBetweenNormals(Facing, Look);
	FVector Axis;
	float Angle;
	Want.ToAxisAndAngle(Axis, Angle);
	const float MaxRad = FMath::DegreesToRadians(GazeMaxDegrees);
	if (Angle > MaxRad) Want = FQuat(Axis, MaxRad);
	GazeDelta = FQuat::Slerp(GazeDelta, Want, FMath::Clamp(DeltaSeconds * GazeSpeed, 0.f, 1.f)).GetNormalized();

	const FQuat C = ToComponent.GetRotation();
	FTransform& Head = CompSpace[HeadRef];
	Head.SetRotation((C * GazeDelta * C.Inverse() * Head.GetRotation()).GetNormalized());
	TArray<FTransform>& Local = Mesh->BoneSpaceTransforms;
	const int32 P = Mesh->GetSkinnedAsset()->GetRefSkeleton().GetParentIndex(HeadRef);
	Local[HeadRef] = P == INDEX_NONE ? Head : Head.GetRelativeTransform(CompSpace[P]);
}
