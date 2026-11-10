#include "RaceDirector.h"

#include "Camera/CameraActor.h"
#include "Camera/CameraComponent.h"
#include "Components/PrimitiveComponent.h"
#include "EngineUtils.h"
#include "Kismet/GameplayStatics.h"
#include "MuJoCo/Components/Bodies/MjBody.h"
#include "MuJoCo/Core/AMjManager.h"
#include "MuJoCo/Core/MjPhysicsEngine.h"
#include "MuJoCo/Utils/MjUtils.h"
#include "RaceNames.h"
#include "Misc/CommandLine.h"
#include "Misc/Parse.h"
#include "UnrealClient.h"

ARaceDirector::ARaceDirector()
{
	PrimaryActorTick.bCanEverTick = true;
	PrimaryActorTick.bStartWithTickEnabled = true;
	PrimaryActorTick.bTickEvenWhenPaused = true;
	PrimaryActorTick.TickGroup = TG_PostPhysics;	// after URLab has moved the bodies this frame
}

void ARaceDirector::BeginPlay()
{
	Super::BeginPlay();
	UE_LOG(LogRace, Log, TEXT("director: BeginPlay (camera %s, tick %s)"), Camera ? *Camera->GetName() : TEXT("none"),
		IsActorTickEnabled() ? TEXT("on") : TEXT("off"));
	if (FParse::Value(FCommandLine::Get(), TEXT("RaceShots="), ShotDir)) ShotDir = FPaths::ConvertRelativePathToFull(ShotDir);
	FParse::Value(FCommandLine::Get(), TEXT("RaceQuitAt="), QuitAt);
	if (Camera)
	{
		// a chase camera swings hard when the pack turns or a racer flips: no motion blur
		FPostProcessSettings& PP = Camera->GetCameraComponent()->PostProcessSettings;
		PP.bOverride_MotionBlurAmount = true;
		PP.MotionBlurAmount = 0.f;
	}
	if (Camera)
		if (APlayerController* PC = UGameplayStatics::GetPlayerController(this, 0)) PC->SetViewTarget(Camera);
}

void ARaceDirector::Fail(const FString& What)
{
	UE_LOG(LogRace, Error, TEXT("[Check] %s FAIL"), *What);
	URacerController::CheckFailures.fetch_add(1);
}

void ARaceDirector::CheckChaos()
{
	bChaosChecked = true;
	int32 Components = 0, Simulating = 0, Colliding = 0;
	for (TActorIterator<AActor> It(GetWorld()); It; ++It)
	{
		TInlineComponentArray<UPrimitiveComponent*> Prims(*It);
		for (UPrimitiveComponent* P : Prims)
		{
			++Components;
			if (P->IsSimulatingPhysics()) { ++Simulating; UE_LOG(LogRace, Error, TEXT("[Check] Chaos simulates %s.%s"), *It->GetName(), *P->GetName()); }
			if (P->GetCollisionEnabled() == ECollisionEnabled::PhysicsOnly || P->GetCollisionEnabled() == ECollisionEnabled::QueryAndPhysics) ++Colliding;
		}
	}
	if (Simulating) Fail(FString::Printf(TEXT("no Chaos: %d of %d primitive components simulate"), Simulating, Components));
	else UE_LOG(LogRace, Display, TEXT("[Check] no Chaos: 0 of %d primitive components simulate (%d have physics collision, never stepped) OK"), Components, Colliding);
}

void ARaceDirector::CheckMarkers(float DeltaSeconds)
{
	bMarkerChecked = true;
	// 1. URLab's conversion on three reference points
	const double P0[3] = { 0, 0, 0 }, PX[3] = { 1, 0, 0 }, PY[3] = { 0, 1, 0 }, PZ[3] = { 0, 0, 1 };
	const FVector U0 = MjUtils::MjToUEPosition(P0), UX = MjUtils::MjToUEPosition(PX), UY = MjUtils::MjToUEPosition(PY), UZ = MjUtils::MjToUEPosition(PZ);
	const bool bPts = U0.Equals(FVector(0, 0, 0), 1e-6) && UX.Equals(FVector(100, 0, 0), 1e-6) && UY.Equals(FVector(0, -100, 0), 1e-6) && UZ.Equals(FVector(0, 0, 100), 1e-6);
	if (!bPts) Fail(FString::Printf(TEXT("marker points: (1,0,0)->%s (0,1,0)->%s (0,0,1)->%s, want (100,0,0) (0,-100,0) (0,0,100)"), *UX.ToString(), *UY.ToString(), *UZ.ToString()));
	else UE_LOG(LogRace, Display, TEXT("[Check] marker points: origin, 1 m along x, y, z land at (0,0,0) (100,0,0) (0,-100,0) (0,0,100) cm OK"));

	// 2. every racer's drawn base body against MuJoCo's position, from the same render snapshot
	AAMjManager* Mgr = AAMjManager::Instance;
	if (!Mgr || !Mgr->PhysicsEngine) { Fail(TEXT("marker bodies: no MuJoCo manager")); return; }
	TMap<int32, UMjBody*> Bodies;
	for (TActorIterator<AActor> It(GetWorld()); It; ++It)
	{
		TInlineComponentArray<UMjBody*> Found(*It);
		for (UMjBody* B : Found) if (B->GetMj().id >= 0) Bodies.Add(B->GetMj().id, B);
	}
	Mgr->PhysicsEngine->WithRenderState([&](const FMjRenderSnapshot& Snap)
	{
		for (const FRaceHudRow& R : Race.Rows)
		{
			UMjBody* const* Body = Bodies.Find(R.BaseBody);
			if (!Body || Snap.XPos.Num() < 3 * R.BaseBody + 3) { Fail(FString::Printf(TEXT("marker body %s: no drawn base body (id %d)"), *R.Name, R.BaseBody)); continue; }
			const FVector Want = MjUtils::MjToUEPosition(&Snap.XPos[3 * R.BaseBody]);
			const FVector Drawn = (*Body)->GetComponentLocation();
			const double Gap = FVector::Dist(Want, Drawn);
			// URLab draws the snapshot it took earlier this frame; the physics thread may have stepped since. Standing on
			// the grid that lag is nothing (0.5 cm); running, allow two frames at the racer's cruise speed. A wrong axis
			// or scale is metres off either way.
			const double Allowed = Race.Phase == ERacePhase::Countdown ? 0.5 : 0.5 + 2.0 * R.Speed * 100.0 * FMath::Max(DeltaSeconds, 1.f / 250.f);
			if (Gap > Allowed) Fail(FString::Printf(TEXT("marker body %s: drawn at %s, MuJoCo says %s (%.2f cm apart, %.2f allowed)"), *R.Name, *Drawn.ToString(), *Want.ToString(), Gap, Allowed));
			else UE_LOG(LogRace, Display, TEXT("[Check] marker body %s: drawn %.3f cm from MuJoCo's base position %s (%s, %.2f cm allowed) OK"),
				*R.Name, Gap, *Want.ToString(), Race.Phase == ERacePhase::Countdown ? TEXT("on the grid") : TEXT("running"), Allowed);
		}
	});
}

void ARaceDirector::Tick(float DeltaSeconds)
{
	Super::Tick(DeltaSeconds);
	++Ticks;
	if (!Controller.IsValid())
	{
		Controller = URacerController::Find(GetWorld());
		if (Controller.IsValid()) UE_LOG(LogRace, Log, TEXT("director: tick %d found the race controller %s"), Ticks, *Controller->GetPathName());
	}
	if (!Controller.IsValid()) return;
	Controller->MarkGameReady();
	Controller->GetHud(Race);
	if (!Race.bRace || Race.Rows.Num() == 0)
	{
		// the race never started: the model failed to compile or the controller failed to bind (both log why). A race
		// test exits instead of waiting for ever (Slice 3: three parallel launches broke URLab's mesh cache and hung).
		WaitedSeconds += DeltaSeconds;
		if (!bGaveUp && WaitedSeconds > 240.0 && FParse::Param(FCommandLine::Get(), TEXT("RaceTest")))
		{
			bGaveUp = true;
			Fail(TEXT("race start: no race 240 s after the first drawn frame (model compile or bind failed: see LogURLab / LogRace above)"));
			FPlatformMisc::RequestExitWithStatus(false, 2);
		}
		return;
	}
	if (!bSawRace)
	{
		bSawRace = true;
		UE_LOG(LogRace, Log, TEXT("director: tick %d sees the race (%s, %.2f s of countdown left, step %lld)"),
			Ticks, Race.Phase == ERacePhase::Countdown ? TEXT("countdown") : TEXT("racing"), Race.CountdownLeft, Race.Steps);
	}

	if (!bChaosChecked) CheckChaos();
	if (!bParkedHidden)	// racers parked off the grid are not drawn (they float still 40 m off the track)
	{
		bParkedHidden = true;
		const mjModel* m = AAMjManager::Instance && AAMjManager::Instance->PhysicsEngine ? AAMjManager::Instance->PhysicsEngine->GetModel() : nullptr;
		int32 Hidden = 0;
		if (m && Controller->ParkedRoots().Num())
			for (TActorIterator<AActor> It(GetWorld()); It; ++It)
			{
				TInlineComponentArray<UMjBody*> Bodies(*It);
				for (UMjBody* B : Bodies)
				{
					const int32 Id = B->GetMj().id;
					if (Id > 0 && Id < m->nbody && Controller->ParkedRoots().Contains(m->body_rootid[Id])) { B->SetVisibility(false, true); ++Hidden; }
				}
			}
		UE_LOG(LogRace, Log, TEXT("director: %d parked racers, %d drawn bodies hidden"), Controller->ParkedRoots().Num(), Hidden);
	}
	// standing on the grid 1 s into the countdown: the reset that put them there has long been drawn. (Right after the
	// reset the drawn pose is a frame behind the teleport: a 25 cm "gap" that is not a coordinate error.)
	if (!bMarkerChecked && (Race.Phase != ERacePhase::Countdown || Race.CountdownLeft < 2.0)) CheckMarkers(DeltaSeconds);

	// -RaceQuitAt=<s>: leave once the race clock passes s seconds (quick visual checks)
	if (QuitAt >= 0.0 && Race.Phase != ERacePhase::Countdown && Race.RaceTime >= QuitAt)
	{
		QuitAt = -1.0;
		UE_LOG(LogRace, Display, TEXT("[RaceQuitAt] %.2f s: leaving"), Race.RaceTime);
		FPlatformMisc::RequestExit(false);
	}

	// -RaceShots=<dir>: screenshots with the HUD on the grid, mid-race, after a flip and at the finish (UI reports)
	if (!ShotDir.IsEmpty())
	{
		auto Shot = [&](int32 Bit, const TCHAR* Name)
		{
			if (ShotsTaken & Bit) return;
			ShotsTaken |= Bit;
			const FString File = FPaths::Combine(ShotDir, FString::Printf(TEXT("%s_%s.png"), *Race.Track.Replace(TEXT(" "), TEXT("")), Name));
			FScreenshotRequest::RequestScreenshot(File, true, false);
			UE_LOG(LogRace, Display, TEXT("[Shot] %s"), *File);
		};
		if (Race.Phase == ERacePhase::Countdown && Race.CountdownLeft < 1.5) Shot(1, TEXT("1_grid"));
		if (Race.Phase == ERacePhase::Racing && Race.RaceTime > 12.0) Shot(2, TEXT("2_racing"));
		for (const FRaceHudRow& R : Race.Rows) if (R.bGettingUp && Race.Phase == ERacePhase::Racing) Shot(4, TEXT("3_getup"));
		if (Race.Phase == ERacePhase::Racing && Race.Rows.Num() && Race.Rows[0].Distance > Race.Total - 3.0) Shot(8, TEXT("4_finish"));
	}

	// chase camera: behind and above the mean of the racers still running, looking along the track there
	FVector Target = FVector::ZeroVector;
	int32 N = 0;
	for (const FRaceHudRow& R : Race.Rows) if (R.FinishTime < 0.0) { Target += R.PosUE; ++N; }
	if (!N) { for (const FRaceHudRow& R : Race.Rows) Target += R.PosUE; N = Race.Rows.Num(); }
	Target /= N;
	const float A = bHaveCamera ? 1.f - FMath::Exp(-2.5f * DeltaSeconds) : 1.f;
	CamFwd = FMath::Lerp(CamFwd, Race.TangentUE.GetSafeNormal(), A).GetSafeNormal();
	const FVector Side = FVector::CrossProduct(FVector::UpVector, CamFwd);
	const FVector Want = Target - CamFwd * Chase.X * 100.0 + Side * Chase.Y * 100.0 + FVector::UpVector * Chase.Z * 100.0;
	CamPos = bHaveCamera ? FMath::Lerp(CamPos, Want, A) : Want;
	bHaveCamera = true;
	if (Camera)
	{
		const FVector Look = Target + FVector::UpVector * LookHeight * 100.0;
		Camera->SetActorLocationAndRotation(CamPos, (Look - CamPos).Rotation());
	}
}
