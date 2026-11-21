#pragma once

#include "CoreMinimal.h"
#include "GameFramework/HUD.h"
#include "GameFramework/PlayerController.h"
#include "Layout/Visibility.h"
#include "RaceRegistry.h"
#include "RacerController.h"
#include "RaceHUD.generated.h"

class SWidget;
class SOverlay;
class SRaceProbe;

/**
 * Everything on screen. Two layers:
 *   Canvas (drawn every frame, read-only): top left the track, lap and standings; top centre the frame and physics
 *     rates; the centre the racer intro, the countdown, GO; bottom right the build stamp, always.
 *   Slate (what you press; mouse and touch alike, every target at least 48 units): the menu screen (L_Menu), and in a
 *     race the gear (top right) with its pause sheet, and the results card.
 * The menu sits on an opaque backdrop and scales down to fit any screen: nothing scrolls.
 *
 * Unattended (tests, kiosk):
 *   -RaceUiTest     the screens' checks (registry, eligibility, START's rules, layout) as [Check] lines; exits 0 / 3
 *   -AutoStart=<s>  the menu presses START after s seconds    -AutoOk=<s>  the results card goes back to the menu after s
 *   -AutoLoops=<n>  leave after n races (memory logged per race: the leak check)
 */
UCLASS()
class PORACEUNREAL_API ARaceHUD : public AHUD
{
	GENERATED_BODY()

public:
	virtual void BeginPlay() override;
	virtual void EndPlay(const EEndPlayReason::Type Reason) override;
	virtual void DrawHUD() override;

	/** "v0.1.0 YYMMDD": the project version and the last commit's date (PoRaceUnreal.Build.cs). */
	static FString BuildStamp();

private:
	// --- shared ---
	bool bMenu = false;						// this level is the menu (no race controller in it)
	TArray<FRaceTrackInfo> Tracks;
	TArray<FRaceRacerInfo> Roster;
	TSharedPtr<SOverlay> Ui;
	double OpenedAt = 0.0, FirstDrawAt = -1.0;
	int32 Frames = 0, SameSizeFrames = 0;
	FVector2D LastCanvas = FVector2D::ZeroVector;
	double AutoStart = -1.0, AutoOk = -1.0;
	int32 AutoLoops = 0;
	bool bUiTest = false, bUiChecked = false, bMenuShot = false, bIntroShot = false, bResultsShot = false, bExiting = false;
	FString ShotDir;
	TMap<FName, FBox2D> Drawn;				// this frame's Canvas groups, viewport pixels (the layout check)
	void Fail(const FString& What) const;
	void Pass(const FString& What) const;
	TSharedPtr<SRaceProbe> ScreenProbe;		// wraps the whole overlay (it fills the viewport): the origin for the others
	FBox2D WidgetBox(const TSharedPtr<SRaceProbe>& W) const;
	void CheckLayout(const TCHAR* Screen, TMap<FName, FBox2D> Boxes);

	// --- the menu ---
	int32 SelTrack = 0;
	TSet<FString> Picked;					// racer names, lower case
	int32 Laps = 0;
	bool bHandicap = false;					// head starts that equalise expected finish times
	TSharedPtr<SRaceProbe> MenuPanel, MenuStamp;
	TSharedPtr<SWidget> StartButton;
	void BuildMenu();
	const FRaceTrackInfo* Track() const { return Tracks.IsValidIndex(SelTrack) ? &Tracks[SelTrack] : nullptr; }
	bool CanStart(FString* Why = nullptr) const;
	void SelectTrack(int32 i);
	void Start();
	void MenuChecks();

	// --- the race ---
	FRaceHud Race;
	TWeakObjectPtr<URacerController> Controller;
	bool bPaused = false;
	bool bTelemetryVisible = true;
	int32 AppModeIndex = 0;	// 0 = Watch, 1 = Play, 2 = Testbed
	double ResultsAt = -1.0;
	bool bCounted = false;
	TSharedPtr<SRaceProbe> Gear;
	void BuildRace();
	void TogglePause();
	void Rematch();
	void NextTrack();
	void BackToMenu();
	void CountLoop();

	// --- idle demo mode + diagnostics overlay (RaceShowcase) ---
	bool bDemo = false;
	int32 PreDemoAppMode = 0;
	EVisibility PreDemoUiVisibility = EVisibility::Visible;
	void HandleDemoMode(bool bActive);
	void HandleDemoCamera(FName CameraName, int32 Index);
	void ReportShowcase();

	// --- Canvas ---
	double FpsSmooth = 0.0, HzSmooth = 0.0, LastWall = 0.0;
	int64 LastSteps = -1;
	double GoUntil = -1.0;
	/** Text at a point size (FCanvasTextItem::Scale is ignored by the engine's runtime fonts); grows the group's box. */
	FVector2D Text(const FString& S, float X, float Y, const FLinearColor& Color, float Size, bool bCentre = false, bool bRight = false, FName Group = NAME_None);
	void DrawIntro(float W, float H, float S);
};

/** Mouse cursor on (the menu, the gear, the cards); touch behaves as the mouse (DefaultInput.ini bUseMouseForTouch). */
UCLASS()
class PORACEUNREAL_API ARacePlayerController : public APlayerController
{
	GENERATED_BODY()

public:
	ARacePlayerController();
};
