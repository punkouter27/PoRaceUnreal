#include "RaceShowcase.h"

#include "RaceRewardConfig.h"
#include "Engine/Engine.h"
#include "Engine/GameViewportClient.h"
#include "Engine/World.h"
#include "Framework/Application/IInputProcessor.h"
#include "Framework/Application/SlateApplication.h"
#include "HAL/PlatformMisc.h"
#include "InputCoreTypes.h"
#include "Misc/App.h"
#include "Misc/CommandLine.h"
#include "Misc/Paths.h"
#include "Misc/Parse.h"
#include "RaceThirdParty.h"
RACE_MUJOCO_INCLUDES_START
#include "MuJoCo/Core/AMjManager.h"
#include "MuJoCo/Core/MjPhysicsEngine.h"
RACE_MUJOCO_INCLUDES_END
#include "Styling/CoreStyle.h"
#include "UnrealClient.h"
#include "Widgets/Input/SButton.h"
#include "Widgets/Layout/SBorder.h"
#include "Widgets/Layout/SBox.h"
#include "Widgets/SBoxPanel.h"
#include "Widgets/SOverlay.h"
#include "Widgets/Text/STextBlock.h"

#include UE_INLINE_GENERATED_CPP_BY_NAME(RaceShowcase)

DEFINE_LOG_CATEGORY_STATIC(LogRaceShowcase, Log, All);

namespace RaceShowcaseUi
{
	// Po Game Standard tokens: opaque surface panel, text >= 4.5:1 on it (#e6e9f2 on #121826 is ~14:1).
	static FLinearColor Hex(const TCHAR* H) { return FLinearColor::FromSRGBColor(FColor::FromHex(H)); }
	static FLinearColor Surface() { return Hex(TEXT("121826")); }
	static FLinearColor Text() { return Hex(TEXT("e6e9f2")); }
	static FLinearColor Muted() { return Hex(TEXT("9aa3b5")); }
	static FLinearColor Accent() { return Hex(TEXT("6366f1")); }
	static FLinearColor Line() { return Hex(TEXT("263049")); }
}

// ------------------------------------------------------------------------------------------------------------
// Input: every key, button, touch, wheel, real mouse move and gamepad stick counts as "the player is here".

class FRaceShowcaseInput : public IInputProcessor
{
public:
	FRaceShowcaseInput(URaceShowcaseSubsystem* InOwner, const FKey& InToggleKey) : Owner(InOwner), ToggleKey(InToggleKey) {}

	virtual void Tick(const float DeltaTime, FSlateApplication& SlateApp, TSharedRef<ICursor> Cursor) override {}

	virtual bool HandleKeyDownEvent(FSlateApplication& SlateApp, const FKeyEvent& InKeyEvent) override
	{
		URaceShowcaseSubsystem* O = Owner.Get();
		if (!O) return false;
		O->NotifyUserInput();
		if (InKeyEvent.GetKey() == ToggleKey)
		{
			if (!InKeyEvent.IsRepeat()) O->ToggleOverlay();
			return true;   // the overlay owns its key
		}
		return false;
	}

	virtual bool HandleAnalogInputEvent(FSlateApplication& SlateApp, const FAnalogInputEvent& InAnalogInputEvent) override
	{
		if (FMath::Abs(InAnalogInputEvent.GetAnalogValue()) > 0.25f) Touch();
		return false;
	}

	virtual bool HandleMouseMoveEvent(FSlateApplication& SlateApp, const FPointerEvent& MouseEvent) override
	{
		if (MouseEvent.GetCursorDelta().SizeSquared() > 4.f) Touch();   // synthetic moves carry no delta
		return false;
	}

	virtual bool HandleMouseButtonDownEvent(FSlateApplication& SlateApp, const FPointerEvent& MouseEvent) override
	{
		Touch();   // mouse buttons and touches
		return false;
	}

	virtual bool HandleMouseWheelOrGestureEvent(FSlateApplication& SlateApp, const FPointerEvent& InWheelEvent, const FPointerEvent* InGestureEvent) override
	{
		Touch();
		return false;
	}

	virtual const TCHAR* GetDebugName() const override { return TEXT("RaceShowcase"); }

private:
	void Touch() { if (URaceShowcaseSubsystem* O = Owner.Get()) O->NotifyUserInput(); }

	TWeakObjectPtr<URaceShowcaseSubsystem> Owner;
	FKey ToggleKey;
};

// ------------------------------------------------------------------------------------------------------------

URaceShowcaseConfig::URaceShowcaseConfig()
{
	OverlayKey = EKeys::Tab;
	DemoCameras = { FName(TEXT("Broadcast")), FName(TEXT("Follow")), FName(TEXT("Orbit")) };
}

const URaceShowcaseConfig* URaceShowcaseSettings::GetShowcaseConfig()
{
	const URaceShowcaseSettings* S = GetDefault<URaceShowcaseSettings>();
	if (S && !S->ShowcaseConfig.IsNull())
	{
		if (const URaceShowcaseConfig* Asset = S->ShowcaseConfig.LoadSynchronous()) return Asset;
	}
	return GetDefault<URaceShowcaseConfig>();
}

const URaceRewardConfig* URaceShowcaseSettings::GetRewardConfig()
{
	const URaceShowcaseSettings* S = GetDefault<URaceShowcaseSettings>();
	if (S && !S->RewardConfig.IsNull())
	{
		if (const URaceRewardConfig* Asset = S->RewardConfig.LoadSynchronous()) return Asset;
	}
	return GetDefault<URaceRewardConfig>();
}

// ------------------------------------------------------------------------------------------------------------

URaceShowcaseSubsystem* URaceShowcaseSubsystem::Get(const UObject* WorldContext)
{
	const UWorld* World = WorldContext ? WorldContext->GetWorld() : nullptr;
	return World ? World->GetSubsystem<URaceShowcaseSubsystem>() : nullptr;
}

bool URaceShowcaseSubsystem::ShouldCreateSubsystem(UObject* Outer) const
{
	return !IsRunningCommandlet() && Super::ShouldCreateSubsystem(Outer);
}

bool URaceShowcaseSubsystem::DoesSupportWorldType(const EWorldType::Type WorldType) const
{
	return WorldType == EWorldType::Game || WorldType == EWorldType::PIE;
}

void URaceShowcaseSubsystem::Initialize(FSubsystemCollectionBase& Collection)
{
	Super::Initialize(Collection);
	const URaceShowcaseConfig* Cfg = URaceShowcaseSettings::GetShowcaseConfig();
	IdleThreshold = Cfg->IdleSeconds;
	FParse::Value(FCommandLine::Get(), TEXT("ShowcaseIdle="), IdleThreshold);
	IdleThreshold = FMath::Max(1.f, IdleThreshold);
	MaxIdleFrame = FMath::Max(0.05f, Cfg->MaxIdleFrameSeconds);
	// a UI test must see the HUD it checks: demo mode never starts under -RaceUiTest (or -NoDemo)
	bDemoDisabled = FParse::Param(FCommandLine::Get(), TEXT("NoDemo")) || FParse::Param(FCommandLine::Get(), TEXT("RaceUiTest"));
	bBenchOnStart = FParse::Param(FCommandLine::Get(), TEXT("ShowcaseBench"));
	LatencySamples.Reset();
	bOverlayVisible = FParse::Param(FCommandLine::Get(), TEXT("DiagOverlay"));
	bTouchButton = Cfg->bTouchCornerButton
		&& (PLATFORM_ANDROID || PLATFORM_IOS || FPlatformMisc::GetUseVirtualJoysticks() || FParse::Param(FCommandLine::Get(), TEXT("ShowcaseTouch")));
	FString Dir;
	if (FParse::Value(FCommandLine::Get(), TEXT("ShowcaseCapture="), Dir)) CaptureDir = FPaths::ConvertRelativePathToFull(Dir);
}

void URaceShowcaseSubsystem::OnWorldBeginPlay(UWorld& InWorld)
{
	Super::OnWorldBeginPlay(InWorld);
	if (!FSlateApplication::IsInitialized()) return;
	const URaceShowcaseConfig* Cfg = URaceShowcaseSettings::GetShowcaseConfig();
	Input = MakeShared<FRaceShowcaseInput>(this, Cfg->OverlayKey);
	FSlateApplication::Get().RegisterInputPreProcessor(Input);
	AddWidgets();
	UE_LOG(LogRaceShowcase, Log, TEXT("Showcase: overlay key %s, demo %s, %d demo cameras, touch button %s%s"),
		*Cfg->OverlayKey.ToString(), bDemoDisabled ? TEXT("disabled (-NoDemo / -RaceUiTest)") : *FString::Printf(TEXT("after %.0f s idle"), IdleThreshold),
		Cfg->DemoCameras.Num(), bTouchButton ? TEXT("on") : TEXT("off"),
		CaptureDir.IsEmpty() ? TEXT("") : *FString::Printf(TEXT(", capturing to %s"), *CaptureDir));
}

void URaceShowcaseSubsystem::Deinitialize()
{
	if (Input.IsValid() && FSlateApplication::IsInitialized()) FSlateApplication::Get().UnregisterInputPreProcessor(Input);
	Input.Reset();
	RemoveWidgets();
	Super::Deinitialize();
}

TStatId URaceShowcaseSubsystem::GetStatId() const
{
	RETURN_QUICK_DECLARE_CYCLE_STAT(URaceShowcaseSubsystem, STATGROUP_Tickables);
}

void URaceShowcaseSubsystem::AddWidgets()
{
	UWorld* World = GetWorld();
	UGameViewportClient* VC = World ? World->GetGameViewport() : nullptr;
	if (!VC) return;
	const TWeakObjectPtr<URaceShowcaseSubsystem> Weak(this);
	const FSlateFontInfo Mono = FCoreStyle::GetDefaultFontStyle("Mono", 13);
	const FSlateFontInfo Body = FCoreStyle::GetDefaultFontStyle("Regular", 13);
	const FSlateBrush* White = FCoreStyle::Get().GetBrush("WhiteBrush");

	OverlayWidget = SNew(SBox)
		.HAlign(HAlign_Left).VAlign(VAlign_Top).Padding(FMargin(16.f, 64.f, 16.f, 16.f))
		.Visibility_Lambda([Weak] { return Weak.IsValid() && Weak->IsOverlayVisible() && !Weak->IsDemoActive() ? EVisibility::SelfHitTestInvisible : EVisibility::Collapsed; })
		[
			SNew(SBorder).BorderImage(White).BorderBackgroundColor(RaceShowcaseUi::Surface()).Padding(FMargin(14.f, 10.f))
			[
				SNew(SVerticalBox)
				+ SVerticalBox::Slot().AutoHeight()
				[
					SNew(STextBlock).Font(Mono).ColorAndOpacity(RaceShowcaseUi::Text())
					.Text_Lambda([Weak] { return Weak.IsValid() ? FText::FromString(Weak->BuildOverlayText()) : FText::GetEmpty(); })
				]
				+ SVerticalBox::Slot().AutoHeight().HAlign(HAlign_Left).Padding(FMargin(0.f, 8.f, 0.f, 0.f))
				[
					SNew(SButton)
					.ButtonStyle(&FCoreStyle::Get().GetWidgetStyle<FButtonStyle>("NoBorder"))
					.ContentPadding(FMargin(0.f))
					.ToolTipText(NSLOCTEXT("RaceShowcase", "BenchTip", "Steps a copy of the loaded MuJoCo scene on this CPU for up to a second and shows simulation steps per second"))
					.OnClicked_Lambda([Weak] { if (Weak.IsValid()) Weak->RunSimBenchmark(); return FReply::Handled(); })
					[
						SNew(SBox).MinDesiredHeight(44.f).VAlign(VAlign_Center)
						[
							SNew(SBorder).BorderImage(White).BorderBackgroundColor(RaceShowcaseUi::Line()).Padding(FMargin(12.f, 6.f)).VAlign(VAlign_Center)
							[
								SNew(STextBlock).Font(Body).ColorAndOpacity(RaceShowcaseUi::Text())
								.Text(NSLOCTEXT("RaceShowcase", "BenchButton", "Benchmark sim speed (sim steps/s)"))
							]
						]
					]
				]
			]
		];
	VC->AddViewportWidgetContent(OverlayWidget.ToSharedRef(), 1000);

	DemoHintWidget = SNew(SBox)
		.HAlign(HAlign_Center).VAlign(VAlign_Bottom).Padding(FMargin(16.f, 16.f, 16.f, 40.f))
		.Visibility_Lambda([Weak] { return Weak.IsValid() && Weak->IsDemoActive() ? EVisibility::HitTestInvisible : EVisibility::Collapsed; })
		[
			SNew(SBorder).BorderImage(White).BorderBackgroundColor(RaceShowcaseUi::Surface()).Padding(FMargin(14.f, 8.f))
			[
				SNew(STextBlock).Font(Body).ColorAndOpacity(RaceShowcaseUi::Text())
				.Text(NSLOCTEXT("RaceShowcase", "DemoHint", "Demo  -  press any key or touch to play"))
			]
		];
	VC->AddViewportWidgetContent(DemoHintWidget.ToSharedRef(), 1000);

	if (bTouchButton)
	{
		ButtonWidget = SNew(SBox)
			.HAlign(HAlign_Right).VAlign(VAlign_Top).Padding(FMargin(8.f))
			.Visibility_Lambda([Weak] { return Weak.IsValid() && !Weak->IsDemoActive() ? EVisibility::SelfHitTestInvisible : EVisibility::Collapsed; })
			[
				SNew(SBox).WidthOverride(44.f).HeightOverride(44.f)
				[
					SNew(SButton)
					.ButtonColorAndOpacity(RaceShowcaseUi::Accent())
					.HAlign(HAlign_Center).VAlign(VAlign_Center)
					.ToolTipText(NSLOCTEXT("RaceShowcase", "ButtonTip", "Diagnostics"))
					.OnClicked_Lambda([Weak] { if (Weak.IsValid()) Weak->ToggleOverlay(); return FReply::Handled(); })
					[
						SNew(STextBlock).Font(FCoreStyle::GetDefaultFontStyle("Bold", 15)).ColorAndOpacity(FLinearColor::White)
						.Text(NSLOCTEXT("RaceShowcase", "ButtonLabel", "i"))
					]
				]
			];
		VC->AddViewportWidgetContent(ButtonWidget.ToSharedRef(), 1001);
	}
}

void URaceShowcaseSubsystem::RemoveWidgets()
{
	UWorld* World = GetWorld();
	UGameViewportClient* VC = World ? World->GetGameViewport() : nullptr;
	for (TSharedPtr<SWidget>* W : { &OverlayWidget, &DemoHintWidget, &ButtonWidget })
	{
		if (VC && W->IsValid()) VC->RemoveViewportWidgetContent(W->ToSharedRef());
		W->Reset();
	}
}

void URaceShowcaseSubsystem::ReportEpisodeReward(float Reward)
{
	EpisodeReward = Reward;
	bHaveReward = true;
}

void URaceShowcaseSubsystem::ReportInferenceMs(float Milliseconds)
{
	if (!FMath::IsFinite(Milliseconds) || Milliseconds < 0.f) return;
	const int32 Window = FMath::Clamp(URaceShowcaseSettings::GetShowcaseConfig()->LatencyWindow, 1, 600);
	if (LatencySamples.Num() < Window)
	{
		LatencySamples.Add(Milliseconds);
	}
	else
	{
		LatencySamples[LatencyNext % LatencySamples.Num()] = Milliseconds;
	}
	LatencyNext = (LatencyNext + 1) % Window;
}

void URaceShowcaseSubsystem::SetCurriculumStage(const FString& Stage)
{
	CurriculumStage = Stage;
}

float URaceShowcaseSubsystem::GetMeanInferenceMs() const
{
	if (LatencySamples.Num() == 0) return -1.f;
	float Sum = 0.f;
	for (const float V : LatencySamples) Sum += V;
	return Sum / LatencySamples.Num();
}

FString URaceShowcaseSubsystem::BuildOverlayText() const
{
	// two columns, the values start at column 19; a long value continues on the next line, indented, so the panel
	// stays narrow enough for a portrait phone
	const TCHAR* Indent = TEXT("\n                   ");
	const URaceShowcaseConfig* Cfg = URaceShowcaseSettings::GetShowcaseConfig();
	const float Lat = GetMeanInferenceMs();
	FString Out = FString::Printf(TEXT("DIAGNOSTICS        [%s]\n"), *Cfg->OverlayKey.GetDisplayName().ToString());
	Out += FString::Printf(TEXT("FPS                %.1f\n"), Fps);
	const FString Note = RewardNote.IsEmpty() ? FString() : FString(Indent) + RewardNote;
	Out += bHaveReward ? FString::Printf(TEXT("Episode reward     %.2f%s\n"), EpisodeReward, *Note) : FString(TEXT("Episode reward     n/a\n"));
	Out += Lat >= 0.f ? FString::Printf(TEXT("Inference latency  %.2f ms (mean of %d)\n"), Lat, LatencySamples.Num())
	                  : FString(TEXT("Inference latency  n/a (no policy step yet)\n"));
	Out += FString::Printf(TEXT("Curriculum stage   %s\n"), CurriculumStage.IsEmpty() ? TEXT("n/a") : *CurriculumStage);
	Out += bDemoDisabled ? FString(TEXT("Demo mode          off (UI test / -NoDemo)"))
	                     : FString::Printf(TEXT("Demo mode          after %.0f s idle (idle %.0f s)"), IdleThreshold, IdleTime);
	Out += FString::Printf(TEXT("\nSim benchmark      %s"), BenchmarkResult.IsEmpty() ? TEXT("not run (button below)") : *BenchmarkResult);
	return Out;
}

FString URaceShowcaseSubsystem::RunSimBenchmark()
{
	// "Training speed" here = how fast this CPU steps the race's own MuJoCo model, which bounds a CPU rollout. It is
	// NOT the GPU (MJX / Brax) trainer's throughput and runs no policy; the result line says exactly that.
	AAMjManager* Mgr = AAMjManager::Instance;
	const mjModel* Live = Mgr && Mgr->PhysicsEngine ? Mgr->PhysicsEngine->GetModel() : nullptr;
	if (!Live)
	{
		BenchmarkResult = TEXT("n/a (no MuJoCo scene loaded)");
		UE_LOG(LogRaceShowcase, Display, TEXT("Showcase: benchmark %s"), *BenchmarkResult);
		return BenchmarkResult;
	}
	const URaceShowcaseConfig* Cfg = URaceShowcaseSettings::GetShowcaseConfig();
	const int32 MaxSteps = FMath::Clamp(Cfg->BenchmarkMaxSteps, 100, 200000);
	const double MaxSeconds = FMath::Clamp(static_cast<double>(Cfg->BenchmarkMaxSeconds), 0.1, 5.0);
	mjModel* M = mj_copyModel(nullptr, Live);	// private copy: the live simulation is not touched
	mjData* D = M ? mj_makeData(M) : nullptr;
	if (!D)
	{
		if (M) mj_deleteModel(M);
		BenchmarkResult = TEXT("n/a (could not copy the MuJoCo model)");
		return BenchmarkResult;
	}
	mj_forward(M, D);
	const double T0 = FPlatformTime::Seconds();
	int32 Steps = 0;
	double Elapsed = 0.0;
	while (Steps < MaxSteps && Elapsed < MaxSeconds)
	{
		for (int32 i = 0; i < 50 && Steps < MaxSteps; ++i, ++Steps) mj_step(M, D);
		Elapsed = FPlatformTime::Seconds() - T0;
	}
	const double Sps = Elapsed > 0.0 ? Steps / Elapsed : 0.0;
	const double Rt = Sps * M->opt.timestep;
	BenchmarkResult = FString::Printf(TEXT("%.0f steps/s, %.0fx real time\n                   MuJoCo, 1 env, CPU, no policy"), Sps, Rt);
	mj_deleteData(D);
	mj_deleteModel(M);
	UE_LOG(LogRaceShowcase, Display, TEXT("Showcase: benchmark %.0f MuJoCo steps/s, %.0fx real time (1 env on this CPU, no policy; %d steps in %.2f s)"),
		Sps, Rt, Steps, Elapsed);
	return BenchmarkResult;
}

void URaceShowcaseSubsystem::SetOverlayVisible(bool bVisible)
{
	bOverlayVisible = bVisible;
}

void URaceShowcaseSubsystem::NotifyUserInput()
{
	IdleTime = 0.f;
	if (bDemoActive) SetDemoActive(false);
}

void URaceShowcaseSubsystem::SetDemoActive(bool bActive)
{
	if (bDemoActive == bActive) return;
	bDemoActive = bActive;
	CameraTime = 0.f;
	CameraIndex = 0;
	UE_LOG(LogRaceShowcase, Log, TEXT("Showcase: demo mode %s"), bActive ? TEXT("on (idle)") : TEXT("off (input)"));
	OnDemoModeChanged.Broadcast(bActive);
	const TArray<FName>& Cams = URaceShowcaseSettings::GetShowcaseConfig()->DemoCameras;
	if (bActive && Cams.Num() > 0) OnDemoCamera.Broadcast(Cams[0], 0);
}

void URaceShowcaseSubsystem::Tick(float DeltaTime)
{
	Super::Tick(DeltaTime);
	const float Dt = static_cast<float>(FApp::GetDeltaTime());   // real time: pause and slow motion don't stop the idle clock
	if (Dt > 0.f)
	{
		const float Inst = 1.f / Dt;
		Fps = Fps <= 0.f ? Inst : FMath::Lerp(Fps, Inst, 0.05f);
	}
	// a long frame (level load, shader compile, stalled window) is not the player being idle
	if (Dt <= MaxIdleFrame) IdleTime += Dt;
	if (!bDemoActive && !bDemoDisabled && IdleTime >= IdleThreshold) SetDemoActive(true);
	if (bBenchOnStart && IdleTime > 3.f)
	{
		bBenchOnStart = false;
		RunSimBenchmark();
	}
	if (bDemoActive)
	{
		const URaceShowcaseConfig* Cfg = URaceShowcaseSettings::GetShowcaseConfig();
		CameraTime += Dt;
		if (Cfg->DemoCameras.Num() > 0 && CameraTime >= Cfg->CameraDwellSeconds)
		{
			CameraTime = 0.f;
			CameraIndex = (CameraIndex + 1) % Cfg->DemoCameras.Num();
			OnDemoCamera.Broadcast(Cfg->DemoCameras[CameraIndex], CameraIndex);
		}
	}
	if (!CaptureDir.IsEmpty()) TickCapture(Dt);
}

void URaceShowcaseSubsystem::Shot(const TCHAR* Name)
{
	const FString File = FPaths::Combine(CaptureDir, FString::Printf(TEXT("%s.png"), Name));
	FScreenshotRequest::RequestScreenshot(File, /*bShowUI*/ true, /*bAddFilenameSuffix*/ false);
	UE_LOG(LogRaceShowcase, Log, TEXT("Showcase: screenshot %s (overlay %d, demo %d, idle %.1f s)"), *File, bOverlayVisible ? 1 : 0, bDemoActive ? 1 : 0, IdleTime);
}

void URaceShowcaseSubsystem::TickCapture(float Dt)
{
	// Scripted check of C12 / C13 without touching the input clock: overlay on, overlay off, demo mode after the
	// idle threshold (two shots one camera dwell apart), then quit.
	CaptureClock += Dt;
	const float Dwell = URaceShowcaseSettings::GetShowcaseConfig()->CameraDwellSeconds;
	const float DemoAt = IdleThreshold + 5.f;
	switch (CaptureStep)
	{
	case 0: if (CaptureClock >= 8.f) { SetOverlayVisible(true); ++CaptureStep; } break;
	case 1: if (CaptureClock >= 9.f) { Shot(TEXT("overlay_on")); ++CaptureStep; } break;
	case 2: if (CaptureClock >= 11.f) { SetOverlayVisible(false); ++CaptureStep; } break;
	case 3: if (CaptureClock >= 12.f) { Shot(TEXT("overlay_off")); ++CaptureStep; } break;
	case 4: if (CaptureClock >= DemoAt && bDemoActive) { Shot(TEXT("demo_a")); ++CaptureStep; } break;
	case 5: if (CaptureClock >= DemoAt + Dwell + 1.f) { Shot(TEXT("demo_b")); ++CaptureStep; } break;
	case 6: if (CaptureClock >= DemoAt + Dwell + 4.f)
		{
			UE_LOG(LogRaceShowcase, Log, TEXT("Showcase: capture done (demo %d), exiting"), bDemoActive ? 1 : 0);
			++CaptureStep;
			FPlatformMisc::RequestExit(false, TEXT("ShowcaseCapture"));
		}
		break;
	default: break;
	}
}
