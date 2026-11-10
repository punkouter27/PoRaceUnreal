// ARaceHUD: Canvas drawing, the screen flow (menu -> intro -> countdown -> race -> results -> menu) and the
// unattended hooks. The Slate widgets are built in RaceHUDUi.cpp.

#include "RaceHUD.h"

#include "Engine/Canvas.h"
#include "Engine/Engine.h"
#include "Engine/Font.h"
#include "Engine/GameViewportClient.h"
#include "Fonts/FontMeasure.h"
#include "Framework/Application/SlateApplication.h"
#include "UnrealClient.h"
#include "HAL/PlatformMemory.h"
#include "Misc/CommandLine.h"
#include "Misc/ConfigCacheIni.h"
#include "Misc/Parse.h"
#include "MuJoCo/Core/AMjManager.h"
#include "MuJoCo/Core/MjPhysicsEngine.h"
#include "RaceGameInstance.h"
#include "RaceNames.h"
#include "RaceProbe.h"
#include "Rendering/SlateRenderer.h"
#include "Widgets/SOverlay.h"

ARacePlayerController::ARacePlayerController()
{
	bShowMouseCursor = true;
	bEnableClickEvents = true;
	bEnableTouchEvents = true;
}

FString ARaceHUD::BuildStamp()
{
	FString Version;
	GConfig->GetString(TEXT("/Script/EngineSettings.GeneralProjectSettings"), TEXT("ProjectVersion"), Version, GGameIni);
	return FString::Printf(TEXT("v%s %s"), Version.IsEmpty() ? TEXT("0.1.0") : *Version, TEXT(PORACE_BUILD_VERSION));
}

void ARaceHUD::Fail(const FString& What) const
{
	UE_LOG(LogRace, Error, TEXT("[Check] %s FAIL"), *What);
	URacerController::CheckFailures.fetch_add(1);
}

void ARaceHUD::Pass(const FString& What) const
{
	UE_LOG(LogRace, Display, TEXT("[Check] %s OK"), *What);
}

void ARaceHUD::BeginPlay()
{
	Super::BeginPlay();
	const TCHAR* Cmd = FCommandLine::Get();
	bUiTest = FParse::Param(Cmd, TEXT("RaceUiTest"));
	FParse::Value(Cmd, TEXT("AutoStart="), AutoStart);
	FParse::Value(Cmd, TEXT("AutoOk="), AutoOk);
	FParse::Value(Cmd, TEXT("AutoLoops="), AutoLoops);
	if (FParse::Value(Cmd, TEXT("RaceShots="), ShotDir)) ShotDir = FPaths::ConvertRelativePathToFull(ShotDir);
	OpenedAt = FPlatformTime::Seconds();
	Tracks = RaceRegistry::Tracks();
	Roster = RaceRegistry::Racers();
	Controller = URacerController::Find(GetWorld());
	bMenu = !Controller.IsValid();
	if (APlayerController* PC = GetOwningPlayerController())
	{
		PC->SetShowMouseCursor(true);
		PC->SetInputMode(FInputModeGameAndUI().SetHideCursorDuringCapture(false).SetLockMouseToViewportBehavior(EMouseLockMode::DoNotLock));
	}
	if (bMenu) BuildMenu();
	else BuildRace();
	UE_LOG(LogRace, Log, TEXT("hud: %s, %d tracks (%d built), %d racers (%d ready)"), bMenu ? TEXT("menu") : TEXT("race"),
		Tracks.Num(), Tracks.FilterByPredicate([](const FRaceTrackInfo& T) { return T.bBuilt; }).Num(),
		Roster.Num(), Roster.FilterByPredicate([](const FRaceRacerInfo& R) { return R.bReady; }).Num());
}

void ARaceHUD::EndPlay(const EEndPlayReason::Type Reason)
{
	if (GEngine && GEngine->GameViewport && Ui.IsValid()) GEngine->GameViewport->RemoveViewportWidgetContent(Ui.ToSharedRef());
	Ui.Reset();
	Super::EndPlay(Reason);
}

FVector2D ARaceHUD::Text(const FString& S, float X, float Y, const FLinearColor& Color, float Size, bool bCentre, bool bRight, FName Group)
{
	const FSlateFontInfo Font(GEngine->GetMediumFont(), FMath::Max(1, FMath::RoundToInt(Size)));
	const FVector2D Extent = FSlateApplication::IsInitialized()
		? FSlateApplication::Get().GetRenderer()->GetFontMeasureService()->Measure(S, Font) : FVector2D(0.6f * Size * S.Len(), Size);
	if (bCentre) X -= 0.5f * Extent.X;
	if (bRight) X -= Extent.X;
	FCanvasTextItem Shadow(FVector2D(X + 2.f, Y + 2.f), FText::FromString(S), Font, FLinearColor(0.f, 0.f, 0.f, 0.6f));
	Canvas->DrawItem(Shadow);
	FCanvasTextItem Item(FVector2D(X, Y), FText::FromString(S), Font, Color);
	Canvas->DrawItem(Item);
	if (!Group.IsNone())
	{
		const FBox2D B(FVector2D(X, Y), FVector2D(X, Y) + Extent);
		FBox2D* G = Drawn.Find(Group);
		if (G) *G += B; else Drawn.Add(Group, B);
	}
	return Extent;
}

void ARaceHUD::DrawHUD()
{
	Super::DrawHUD();
	if (!Canvas) return;
	Drawn.Reset();
	const float W = Canvas->ClipX, H = Canvas->ClipY, Pad = 0.025f * FMath::Min(W, H);
	const float S = FMath::Clamp(FMath::Min(W, H) / 720.f, 0.75f, 3.f);	// point sizes follow the short side (1.0 at 720 p)
	const double Now = FPlatformTime::Seconds();
	APlayerController* PC = GetOwningPlayerController();
	// timers count from the first DRAWN frame (the editor binary can take a minute between BeginPlay and its first
	// frame), and the checks wait for Slate to have painted the widgets too
	if (FirstDrawAt < 0.0) FirstDrawAt = Now;
	++Frames;
	// ... and for the screen to keep its size (a window resized after it opened: -ForceRes, a phone rotating)
	const FVector2D CanvasSize(W, H);
	if (!CanvasSize.Equals(LastCanvas, 0.5)) { LastCanvas = CanvasSize; SameSizeFrames = 0; }
	++SameSizeFrames;
	const bool bSettled = Frames > 30 && SameSizeFrames > 30 && Now - FirstDrawAt > 1.5;

	// build stamp, always (the menu draws its own in Slate, above its backdrop)
	if (!bMenu) Text(BuildStamp(), W - Pad, H - Pad - 20.f * S, FLinearColor(1.f, 1.f, 1.f, 0.7f), 12.f * S, false, true, TEXT("BR"));

	if (bMenu)
	{
		if (!ShotDir.IsEmpty() && !bMenuShot && bSettled)	// -RaceShots=<dir>: the menu, once
		{
			bMenuShot = true;
			FVector2D Size(0, 0);
			if (GEngine->GameViewport) GEngine->GameViewport->GetViewportSize(Size);
			FScreenshotRequest::RequestScreenshot(FPaths::Combine(ShotDir, FString::Printf(TEXT("Menu_%.0fx%.0f.png"), Size.X, Size.Y)), true, false);
		}
		if (PC && PC->WasInputKeyJustPressed(EKeys::Enter)) Start();
		if (bUiTest && !bUiChecked && bSettled) { bUiChecked = true; MenuChecks(); }
		if (AutoStart >= 0.0 && bSettled && Now - FirstDrawAt > AutoStart && (!bUiTest || bUiChecked)) { AutoStart = -1.0; UE_LOG(LogRace, Display, TEXT("[Auto] START")); Start(); }
		return;
	}

	if (!Controller.IsValid()) Controller = URacerController::Find(GetWorld());
	if (Controller.IsValid()) Controller->GetHud(Race);

	// rates: frames drawn and physics steps per wall second
	if (LastWall > 0.0)
	{
		const double Dt = FMath::Max(Now - LastWall, 1e-4);
		FpsSmooth = FMath::Lerp(FpsSmooth, 1.0 / Dt, 0.05);
		if (LastSteps >= 0 && Race.Steps >= LastSteps) HzSmooth = FMath::Lerp(HzSmooth, (Race.Steps - LastSteps) / Dt, 0.05);
	}
	LastWall = Now;
	LastSteps = Race.Steps;
	Text(FString::Printf(TEXT("%.0f fps  ·  %.0f Hz"), FpsSmooth, HzSmooth), 0.5f * W, Pad, FLinearColor(0.85f, 0.85f, 0.85f), 13.f * S, true, false, TEXT("TC"));
	if (!Race.bRace) return;

	if (PC && PC->WasInputKeyJustPressed(EKeys::Escape)) TogglePause();

	// top left: track and lap, then the standings and the race clock
	int32 Lap = 1;
	for (const FRaceHudRow& R : Race.Rows) if (R.FinishTime < 0.0) { Lap = FMath::Min(R.Lap + 1, Race.Laps); break; }
	Text(Race.Laps > 1 ? FString::Printf(TEXT("%s  ·  Lap %d/%d"), *Race.Track, Lap, Race.Laps) : Race.Track, Pad, Pad, FLinearColor::White, 20.f * S, false, false, TEXT("TL"));
	float Y = Pad + 38.f * S;
	for (int32 i = 0; i < Race.Rows.Num(); ++i)
	{
		const FRaceHudRow& R = Race.Rows[i];
		const FString Status = R.FinishTime >= 0.0 ? FString::Printf(TEXT("%.2f s"), R.FinishTime)
			: Race.Phase == ERacePhase::Finished ? FString::Printf(TEXT("DNF  %.0f m"), R.Distance)
			: FString::Printf(TEXT("%.0f m%s"), R.Distance, R.bGettingUp ? TEXT("  DOWN") : R.State == ERacerState::Stumble ? TEXT("  stumble") : TEXT(""));
		Text(FString::Printf(TEXT("%d. %s"), i + 1, *R.Name), Pad, Y, R.Color, 16.f * S, false, false, TEXT("TL"));
		Text(Status, Pad + 120.f * S, Y, FLinearColor(0.92f, 0.92f, 0.92f), 16.f * S, false, false, TEXT("TL"));
		Y += 26.f * S;
	}
	Text(FString::Printf(TEXT("%.2f s"), Race.RaceTime), Pad, Y + 6.f * S, FLinearColor(0.92f, 0.92f, 0.92f), 16.f * S, false, false, TEXT("TL"));

	// centre: the racer intro, the countdown, GO
	if (Race.IntroLeft > 0.0) DrawIntro(W, H, S);
	else if (Race.Phase == ERacePhase::Countdown) { Text(FString::FromInt(FMath::Max(1, FMath::CeilToInt(Race.CountdownLeft))), 0.5f * W, 0.26f * H, FLinearColor(1.f, 0.85f, 0.2f), 90.f * S, true, false, TEXT("C")); GoUntil = -1.0; }
	else if (Race.Phase == ERacePhase::Racing)
	{
		if (GoUntil < 0.0) GoUntil = Now + 1.0;
		if (Now < GoUntil) Text(TEXT("GO!"), 0.5f * W, 0.26f * H, FLinearColor(1.f, 0.85f, 0.2f), 90.f * S, true, false, TEXT("C"));
	}

	// the results card (Slate) shows once the race is over; the unattended loop moves on from it
	if (Race.Phase == ERacePhase::Finished)
	{
		if (ResultsAt < 0.0) ResultsAt = Now;
		if (!bCounted && !Race.Result.IsEmpty()) CountLoop();	// the result line arrives with the controller's next publish
		if (PC && PC->WasInputKeyJustPressed(EKeys::Enter)) BackToMenu();
		if (AutoOk >= 0.0 && Now - ResultsAt > AutoOk) { AutoOk = -1.0; UE_LOG(LogRace, Display, TEXT("[Auto] OK")); BackToMenu(); }
	}

	// -RaceShots: the racer intro (the first card) and the results card
	auto Shot = [&](bool& bTaken, const TCHAR* Name)
	{
		if (bTaken || ShotDir.IsEmpty()) return;
		bTaken = true;
		FVector2D Size(0, 0);
		if (GEngine->GameViewport) GEngine->GameViewport->GetViewportSize(Size);
		FScreenshotRequest::RequestScreenshot(FPaths::Combine(ShotDir, FString::Printf(TEXT("%s_%s_%.0fx%.0f.png"), *Race.Track.Replace(TEXT(" "), TEXT("")), Name, Size.X, Size.Y)), true, false);
	};
	if (Race.IntroLeft > 0.0 && Race.IntroSeconds - Race.IntroLeft > 1.0) Shot(bIntroShot, TEXT("0_intro"));
	if (ResultsAt >= 0.0 && Now - ResultsAt > 1.0) Shot(bResultsShot, TEXT("5_results"));

	// the race screen's layout check, once, on a racing frame with everything drawn; the test ends at the results
	if (bUiTest && !bUiChecked && Race.Phase == ERacePhase::Racing && Race.RaceTime > 2.5)
	{
		bUiChecked = true;
		TMap<FName, FBox2D> Boxes = Drawn;
		Boxes.Add(TEXT("TR"), WidgetBox(Gear));
		CheckLayout(TEXT("race"), Boxes);
	}
	if (bUiTest && AutoLoops <= 0 && ResultsAt >= 0.0 && Now - ResultsAt > 2.0 && !bExiting)
	{
		bExiting = true;
		const int32 Failures = URacerController::CheckFailures.load();
		UE_LOG(LogRace, Display, TEXT("[RaceUiTest] done at the results card: %d check failures"), Failures);
		FPlatformMisc::RequestExitWithStatus(false, Failures ? 3 : 0);
	}
}

void ARaceHUD::DrawIntro(float W, float H, float S)
{
	// one card per racer, in grid order, for an equal share of the intro; the director frames the same racer
	const int32 N = FMath::Max(1, Race.Rows.Num());
	const double Per = Race.IntroSeconds / N;
	const int32 k = FMath::Clamp(FMath::FloorToInt((Race.IntroSeconds - Race.IntroLeft) / FMath::Max(Per, 1e-3)), 0, N - 1);
	const FRaceHudRow& R = Race.Rows[k];	// at the intro everyone is at 0 m: standings order = grid order
	const FRaceRacerInfo* Info = RaceRegistry::FindRacer(Roster, R.Name);
	const float Y = 0.62f * H;
	Text(R.Name, 0.5f * W, Y, R.Color, 54.f * S, true, false, TEXT("C"));
	if (Info)
	{
		const FString Kind = Info->Kind == TEXT("go2") ? TEXT("Unitree Go2 robot dog") : Info->Kind == TEXT("human") ? TEXT("human") : Info->Kind;
		Text(FString::Printf(TEXT("%s  ·  %.2f m  ·  %.0f kg"), *Kind, Info->Height, Info->Mass), 0.5f * W, Y + 64.f * S, FLinearColor::White, 18.f * S, true, false, TEXT("C"));
		Text(FString::Printf(TEXT("brain: %s  ·  cruising at %.2f m/s this race"), *Info->Brain, R.Speed), 0.5f * W, Y + 92.f * S, FLinearColor(0.85f, 0.85f, 0.85f), 15.f * S, true, false, TEXT("C"));
	}
}

FBox2D ARaceHUD::WidgetBox(const TSharedPtr<SRaceProbe>& Wd) const
{
	// window pixels of the last paint, relative to the overlay that fills the viewport
	if (!Wd.IsValid() || !ScreenProbe.IsValid()) return FBox2D(ForceInit);
	const FBox2D B = Wd->Box(), V = ScreenProbe->Box();
	if (!B.bIsValid || !V.bIsValid) return FBox2D(ForceInit);
	return FBox2D(B.Min - V.Min, B.Max - V.Min);
}

void ARaceHUD::CheckLayout(const TCHAR* Screen, TMap<FName, FBox2D> Boxes)
{
	FVector2D Size(0, 0);
	if (GEngine && GEngine->GameViewport) GEngine->GameViewport->GetViewportSize(Size);
	const FBox2D View(FVector2D(0, 0), Size);
	int32 Bad = 0;
	TArray<FName> Names;
	Boxes.GetKeys(Names);
	for (const FName& N : Names)
	{
		const FBox2D& B = Boxes[N];
		if (!B.bIsValid) { Fail(FString::Printf(TEXT("%s layout: group %s was not drawn"), Screen, *N.ToString())); ++Bad; continue; }
		if (!View.IsInside(B.Min) || !View.IsInside(B.Max - FVector2D(1, 1)))
		{
			Fail(FString::Printf(TEXT("%s layout: group %s (%s) leaves the %.0fx%.0f screen"), Screen, *N.ToString(), *B.ToString(), Size.X, Size.Y));
			++Bad;
		}
	}
	for (int32 i = 0; i < Names.Num(); ++i)
		for (int32 j = i + 1; j < Names.Num(); ++j)
		{
			const FBox2D& A = Boxes[Names[i]];
			const FBox2D& B = Boxes[Names[j]];
			if (A.bIsValid && B.bIsValid && A.Intersect(B))
			{
				Fail(FString::Printf(TEXT("%s layout: %s %s overlaps %s %s"), Screen, *Names[i].ToString(), *A.ToString(), *Names[j].ToString(), *B.ToString()));
				++Bad;
			}
		}
	if (!Bad) Pass(FString::Printf(TEXT("%s layout at %.0fx%.0f: %d groups inside the screen, none overlapping"), Screen, Size.X, Size.Y, Names.Num()));
}

void ARaceHUD::MenuChecks()
{
	// registry: every card and track file listed; the unready ones shown with a reason
	const int32 Built = Tracks.FilterByPredicate([](const FRaceTrackInfo& T) { return T.bBuilt; }).Num();
	const int32 Ready = Roster.FilterByPredicate([](const FRaceRacerInfo& R) { return R.bReady; }).Num();
	if (Tracks.Num() >= 4 && Built >= 2) Pass(FString::Printf(TEXT("menu tracks: %d listed, %d built"), Tracks.Num(), Built));
	else Fail(FString::Printf(TEXT("menu tracks: %d listed, %d built (want 4 and 2)"), Tracks.Num(), Built));
	if (Roster.Num() >= 4 && Ready >= 2) Pass(FString::Printf(TEXT("menu racers: %d listed, %d ready"), Roster.Num(), Ready));
	else Fail(FString::Printf(TEXT("menu racers: %d listed, %d ready (want 4 and 2)"), Roster.Num(), Ready));
	for (const TCHAR* N : { TEXT("Grandma"), TEXT("G1") })
	{
		const FRaceRacerInfo* R = RaceRegistry::FindRacer(Roster, N);
		if (R && !R->bReady && !R->Blocked.IsEmpty()) Pass(FString::Printf(TEXT("%s listed as not ready: %s"), N, *R->Blocked));
		else Fail(FString::Printf(TEXT("%s should be listed as not ready, with a reason"), N));
	}
	// eligibility: a human cannot be picked on a track that is not flat
	const FRaceRacerInfo* Matt = RaceRegistry::FindRacer(Roster, TEXT("Matt"));
	const FRaceTrackInfo* Bank = Tracks.FindByPredicate([](const FRaceTrackInfo& T) { return T.Terrain != TEXT("flat"); });
	FString Why;
	if (Matt && Bank && !RaceRegistry::CanRace(*Matt, *Bank, &Why)) Pass(FString::Printf(TEXT("Matt refused on %s: %s"), *Bank->Name, *Why));
	else Fail(TEXT("Matt must be refused on a track that is not flat"));
	// START: refused with nobody picked, allowed with Blue on a built track
	const TSet<FString> Keep = Picked;
	const int32 KeepTrack = SelTrack;
	SelTrack = Tracks.IndexOfByPredicate([](const FRaceTrackInfo& T) { return T.bBuilt; });
	Picked.Reset();
	const bool bEmptyRefused = !CanStart(&Why);
	const FString EmptyWhy = Why;
	Picked.Add(TEXT("blue"));
	const bool bBlueOk = CanStart();
	Picked = Keep;
	SelTrack = KeepTrack;
	if (bEmptyRefused) Pass(FString::Printf(TEXT("START refused with nobody picked (\"%s\")"), *EmptyWhy));
	else Fail(TEXT("START must be refused with nobody picked"));
	if (bBlueOk) Pass(TEXT("START allowed with Blue on a built track"));
	else Fail(TEXT("START refused with Blue on a built track"));
	// layout
	UE_LOG(LogRace, Log, TEXT("menu layout probes: screen %s, panel %s"), ScreenProbe.IsValid() ? *ScreenProbe->Box().ToString() : TEXT("none"),
		MenuPanel.IsValid() ? *MenuPanel->Box().ToString() : TEXT("none"));
	TMap<FName, FBox2D> Boxes;
	Boxes.Add(TEXT("menu"), WidgetBox(MenuPanel));
	Boxes.Add(TEXT("BR"), WidgetBox(MenuStamp));
	CheckLayout(TEXT("menu"), Boxes);
	if (AutoStart < 0.0)	// nothing else to do: report and leave
	{
		const int32 Failures = URacerController::CheckFailures.load();
		UE_LOG(LogRace, Display, TEXT("[RaceUiTest] menu done: %d check failures"), Failures);
		FPlatformMisc::RequestExitWithStatus(false, Failures ? 3 : 0);
	}
}

void ARaceHUD::CountLoop()
{
	if (bCounted) return;
	bCounted = true;
	URaceGameInstance* GI = GetGameInstance<URaceGameInstance>();
	if (!GI) return;
	++GI->Loops;
	const double MB = FPlatformMemory::GetStats().UsedPhysical / (1024.0 * 1024.0);
	if (GI->Loops == 1) GI->FirstLoopMB = MB;
	UE_LOG(LogRace, Display, TEXT("[Loop] %d%s: %s | memory %.0f MB (%+.0f MB since the first race)"), GI->Loops,
		AutoLoops > 0 ? *FString::Printf(TEXT("/%d"), AutoLoops) : TEXT(""), *Race.Result, MB, MB - GI->FirstLoopMB);
	if (AutoLoops > 0 && GI->Loops >= AutoLoops)
	{
		const int32 Failures = URacerController::CheckFailures.load();
		UE_LOG(LogRace, Display, TEXT("[AutoLoops] %d races done, %d check failures"), GI->Loops, Failures);
		FPlatformMisc::RequestExitWithStatus(false, Failures ? 3 : 0);
	}
}

void ARaceHUD::TogglePause()
{
	AAMjManager* Mgr = AAMjManager::Instance;
	if (!Mgr || !Mgr->PhysicsEngine || Race.Phase == ERacePhase::Finished) return;
	bPaused = !bPaused;
	Mgr->PhysicsEngine->bIsPaused = bPaused;	// the physics clock stops: the race resumes exactly where it was (R-13)
	UE_LOG(LogRace, Log, TEXT("hud: %s"), bPaused ? TEXT("paused") : TEXT("resumed"));
}

void ARaceHUD::BackToMenu()
{
	if (AAMjManager* Mgr = AAMjManager::Instance; Mgr && Mgr->PhysicsEngine) Mgr->PhysicsEngine->bIsPaused = false;
	if (URaceGameInstance* GI = GetGameInstance<URaceGameInstance>()) GI->OpenMenu(this);
}

void ARaceHUD::Rematch()
{
	URaceGameInstance* GI = GetGameInstance<URaceGameInstance>();
	if (!GI) return;
	if (GI->Track.IsEmpty()) GI->Track = Race.TrackId;
	GI->StartRace(this);
}

void ARaceHUD::NextTrack()
{
	URaceGameInstance* GI = GetGameInstance<URaceGameInstance>();
	if (!GI) return;
	// the next built track after this one; the picked racers that may race there (everyone eligible if none is left)
	const int32 Here = Tracks.IndexOfByPredicate([&](const FRaceTrackInfo& T) { return T.Id == Race.TrackId; });
	for (int32 k = 1; k <= Tracks.Num(); ++k)
	{
		const FRaceTrackInfo& T = Tracks[(Here + k) % Tracks.Num()];
		if (!T.bBuilt) continue;
		TArray<FString> Keep;
		for (const FString& N : GI->Racers)
			if (const FRaceRacerInfo* R = RaceRegistry::FindRacer(Roster, N); R && RaceRegistry::CanRace(*R, T)) Keep.Add(N);
		GI->Track = T.Id;
		GI->Racers = Keep;
		GI->Laps = 0;
		GI->StartRace(this);
		return;
	}
}
