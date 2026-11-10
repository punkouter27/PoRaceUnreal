// ARaceHUD's Slate layer: the menu screen, and in a race the gear, the pause sheet and the results card.
// Sizes are Slate units (DPI-scaled); every touch target is at least 48 units; the menu scales down to fit, never scrolls.

#include "RaceHUD.h"

#include "Brushes/SlateColorBrush.h"
#include "Brushes/SlateRoundedBoxBrush.h"
#include "Engine/Engine.h"
#include "Engine/GameViewportClient.h"
#include "RaceGameInstance.h"
#include "RaceNames.h"
#include "RaceProbe.h"
#include "Styling/CoreStyle.h"
#include "Widgets/Input/SButton.h"
#include "Widgets/Layout/SBorder.h"
#include "Widgets/Layout/SBox.h"
#include "Widgets/Layout/SScaleBox.h"
#include "Widgets/Layout/SWrapBox.h"
#include "Widgets/SBoxPanel.h"
#include "Widgets/SOverlay.h"
#include "Widgets/Text/STextBlock.h"

namespace
{
	constexpr float Touch = 48.f;
	const FLinearColor Gold(1.f, 0.82f, 0.25f), Dim(0.55f, 0.55f, 0.6f), Ink(0.93f, 0.93f, 0.95f);
	const FSlateColorBrush& Backdrop() { static const FSlateColorBrush B(FLinearColor(0.02f, 0.025f, 0.035f, 1.f)); return B; }
	const FSlateRoundedBoxBrush& Card() { static const FSlateRoundedBoxBrush B(FLinearColor(0.f, 0.f, 0.f, 0.78f), 14.f); return B; }
	const FSlateRoundedBoxBrush& Panel() { static const FSlateRoundedBoxBrush B(FLinearColor(0.07f, 0.075f, 0.09f, 1.f), 14.f); return B; }
	const FSlateRoundedBoxBrush& On() { static const FSlateRoundedBoxBrush B(FLinearColor(0.13f, 0.11f, 0.05f, 1.f), 10.f, FLinearColor(1.f, 0.82f, 0.25f, 1.f), 2.f); return B; }	// picked: dark, gold outline (a racer's colour stays readable on it)
	const FSlateRoundedBoxBrush& Off() { static const FSlateRoundedBoxBrush B(FLinearColor(1.f, 1.f, 1.f, 0.07f), 10.f); return B; }
	const FSlateRoundedBoxBrush& Faint() { static const FSlateRoundedBoxBrush B(FLinearColor(1.f, 1.f, 1.f, 0.025f), 10.f); return B; }

	TSharedRef<STextBlock> Label(const TAttribute<FText>& T, int32 Size, const TAttribute<FSlateColor>& C, bool bBold = true)
	{
		return SNew(STextBlock).Text(T).Font(FCoreStyle::GetDefaultFontStyle(bBold ? "Bold" : "Regular", Size)).ColorAndOpacity(C).ShadowOffset(FVector2D(1.0, 1.0));
	}

	FText T(const FString& S) { return FText::FromString(S); }

	/** A flat button: its face is Content; Brush follows IsOn; disabled = dim and not clickable. */
	TSharedRef<SWidget> Button(TSharedRef<SWidget> Content, TFunction<void()> Click, TFunction<bool()> IsOn = nullptr, TFunction<bool()> IsEnabled = nullptr,
		float MinWidth = Touch, TSharedPtr<SWidget>* Out = nullptr)
	{
		TSharedPtr<SBorder> Face;
		TSharedRef<SWidget> W = SNew(SBox).MinDesiredHeight(Touch).MinDesiredWidth(MinWidth)
			[SNew(SButton).ButtonStyle(&FCoreStyle::Get().GetWidgetStyle<FButtonStyle>("NoBorder")).ContentPadding(0.f)
				.ClickMethod(EButtonClickMethod::MouseDown).TouchMethod(EButtonTouchMethod::Down)
				.IsEnabled_Lambda([IsEnabled] { return !IsEnabled || IsEnabled(); })
				.OnClicked_Lambda([Click] { Click(); return FReply::Handled(); })
				[SAssignNew(Face, SBorder).Padding(FMargin(14.f, 8.f)).HAlign(HAlign_Center).VAlign(VAlign_Center)
					.BorderImage_Lambda([IsOn, IsEnabled]() -> const FSlateBrush*
					{
						if (IsEnabled && !IsEnabled()) return &Faint();
						return IsOn && IsOn() ? &On() : &Off();
					})
					.ColorAndOpacity_Lambda([IsEnabled] { return (IsEnabled && !IsEnabled()) ? FLinearColor(1.f, 1.f, 1.f, 0.45f) : FLinearColor::White; })
					[Content]]];
		if (Out) *Out = W;
		return W;
	}

	void Mount(TSharedPtr<SOverlay>& Ui, int32 Z)
	{
		if (GEngine && GEngine->GameViewport && Ui.IsValid()) GEngine->GameViewport->AddViewportWidgetContent(Ui.ToSharedRef(), Z);
	}
}

// --- the menu -----------------------------------------------------------------------------------------------------------

bool ARaceHUD::CanStart(FString* Why) const
{
	auto No = [Why](const FString& S) { if (Why) *Why = S; return false; };
	const FRaceTrackInfo* Tr = Track();
	if (!Tr) return No(TEXT("pick a track"));
	if (!Tr->bBuilt) return No(Tr->Name + TEXT(" is not built yet"));
	int32 N = 0;
	for (const FString& P : Picked)
		if (const FRaceRacerInfo* R = RaceRegistry::FindRacer(Roster, P); R && RaceRegistry::CanRace(*R, *Tr)) ++N;
	if (!N) return No(TEXT("pick at least one racer"));
	if (Why) Why->Reset();
	return true;
}

void ARaceHUD::SelectTrack(int32 i)
{
	if (!Tracks.IsValidIndex(i)) return;
	SelTrack = i;
	Laps = Tracks[i].bClosed ? FMath::Max(Laps, Tracks[i].DefaultLaps) : 1;
	// drop picks that cannot race here; on a fresh menu pick everyone who can
	TSet<FString> Keep;
	for (const FString& P : Picked)
		if (const FRaceRacerInfo* R = RaceRegistry::FindRacer(Roster, P); R && RaceRegistry::CanRace(*R, Tracks[i])) Keep.Add(P);
	Picked = Keep;
}

void ARaceHUD::Start()
{
	FString Why;
	if (!CanStart(&Why)) { UE_LOG(LogRace, Log, TEXT("menu: START refused: %s"), *Why); return; }
	URaceGameInstance* GI = GetGameInstance<URaceGameInstance>();
	if (!GI) { UE_LOG(LogRace, Error, TEXT("menu: the game instance is not URaceGameInstance (DefaultEngine.ini GameInstanceClass)")); return; }
	GI->Track = Track()->Id;
	GI->Racers.Reset();
	for (const FString& P : Picked)
		if (const FRaceRacerInfo* R = RaceRegistry::FindRacer(Roster, P); R && RaceRegistry::CanRace(*R, *Track())) GI->Racers.Add(P);
	GI->Racers.Sort();
	GI->Laps = Track()->bClosed ? Laps : 0;
	GI->StartRace(this);
}

void ARaceHUD::BuildMenu()
{
	// the choices of the last race, or the first built track with everyone who can race on it
	const URaceGameInstance* GI = GetGameInstance<URaceGameInstance>();
	SelTrack = Tracks.IndexOfByPredicate([&](const FRaceTrackInfo& Tr) { return GI && Tr.Id == GI->Track; });
	if (SelTrack < 0) SelTrack = Tracks.IndexOfByPredicate([](const FRaceTrackInfo& Tr) { return Tr.bBuilt; });
	if (GI && GI->Racers.Num()) for (const FString& R : GI->Racers) Picked.Add(R);
	else if (Track()) for (const FRaceRacerInfo& R : Roster) if (RaceRegistry::CanRace(R, *Track())) Picked.Add(R.Name.ToLower());
	Laps = GI && GI->Laps > 0 ? GI->Laps : Track() ? Track()->DefaultLaps : 1;
	SelectTrack(SelTrack);

	TWeakObjectPtr<ARaceHUD> Self(this);
	TSharedRef<SVerticalBox> TrackList = SNew(SVerticalBox);
	for (int32 i = 0; i < Tracks.Num(); ++i)
	{
		const FRaceTrackInfo Tr = Tracks[i];
		const FString Line = FString::Printf(TEXT("%s  ·  %.0f m%s  ·  %s"), *Tr.Name, Tr.Length, Tr.bClosed ? TEXT(" lap") : TEXT(""), *Tr.Terrain);
		TrackList->AddSlot().AutoHeight().Padding(0.f, 3.f)
			[Button(SNew(SHorizontalBox)
					+ SHorizontalBox::Slot().FillWidth(1.f).VAlign(VAlign_Center)[Label(T(Line), 15, FSlateColor(Ink))]
					+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center).Padding(12.f, 0.f, 0.f, 0.f)[Label(T(Tr.bBuilt ? TEXT("") : TEXT("later build")), 12, FSlateColor(Dim), false)],
				[Self, i] { if (Self.IsValid()) Self->SelectTrack(i); },
				[Self, i] { return Self.IsValid() && Self->SelTrack == i; },
				[Tr] { return Tr.bBuilt; }, 420.f)];
	}

	TSharedRef<SWrapBox> Chips = SNew(SWrapBox).PreferredSize(560.f).InnerSlotPadding(FVector2D(6.f, 6.f));	// its own width: a height to match its rows
	for (const FRaceRacerInfo& R0 : Roster)
	{
		const FRaceRacerInfo R = R0;
		const FString Key = R.Name.ToLower();
		auto Why = [Self, R]() -> FString
		{
			FString W;
			if (!Self.IsValid() || !Self->Track()) return W;
			RaceRegistry::CanRace(R, *Self->Track(), &W);
			return W;
		};
		const FString Kind = R.Kind == TEXT("go2") ? TEXT("robot dog") : R.Kind;
		Chips->AddSlot()
			[Button(SNew(SBox).WidthOverride(170.f)
					[SNew(SVerticalBox)
						+ SVerticalBox::Slot().AutoHeight()[Label(T(R.Name), 17, FSlateColor(R.Color))]
						+ SVerticalBox::Slot().AutoHeight()[Label(T(FString::Printf(TEXT("%s · %.2f m"), *Kind, R.Height)), 12, FSlateColor(Ink), false)]
						+ SVerticalBox::Slot().AutoHeight()[SNew(STextBlock).Font(FCoreStyle::GetDefaultFontStyle("Regular", 11)).ColorAndOpacity(FSlateColor(Gold)).AutoWrapText(true)
							.Text_Lambda([Why, R] { const FString W = Why(); return T(R.bReady ? W : TEXT("not ready: ") + R.Blocked); })]],
				[Self, Key] { if (Self.IsValid()) { if (Self->Picked.Contains(Key)) Self->Picked.Remove(Key); else Self->Picked.Add(Key); } },
				[Self, Key] { return Self.IsValid() && Self->Picked.Contains(Key); },
				[Why] { return Why().IsEmpty(); })];
	}

	auto Closed = [Self] { return Self.IsValid() && Self->Track() && Self->Track()->bClosed; };
	TSharedRef<SWidget> LapsRow = SNew(SHorizontalBox)
		+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center).Padding(0.f, 0.f, 12.f, 0.f)[Label(T(TEXT("LAPS")), 14, FSlateColor(Dim))]
		+ SHorizontalBox::Slot().AutoWidth()[Button(Label(T(TEXT("-")), 18, FSlateColor(Ink)), [Self] { if (Self.IsValid()) Self->Laps = FMath::Max(1, Self->Laps - 1); }, nullptr, Closed)]
		+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center).Padding(14.f, 0.f)
			[SNew(STextBlock).Font(FCoreStyle::GetDefaultFontStyle("Bold", 20)).ColorAndOpacity(FSlateColor(Ink))
				.Text_Lambda([Self, Closed] { return T(!Self.IsValid() ? TEXT("") : Closed() ? FString::FromInt(Self->Laps) : TEXT("1 (a sprint)")); })]
		+ SHorizontalBox::Slot().AutoWidth()[Button(Label(T(TEXT("+")), 18, FSlateColor(Ink)), [Self] { if (Self.IsValid()) Self->Laps = FMath::Min(5, Self->Laps + 1); }, nullptr, Closed)];

	TSharedRef<SWidget> Panel_ = SNew(SBorder).BorderImage(&Panel()).Padding(FMargin(28.f, 22.f))
		[SNew(SVerticalBox)
			+ SVerticalBox::Slot().AutoHeight()[Label(T(TEXT("PoRace")), 40, FSlateColor(Gold))]
			+ SVerticalBox::Slot().AutoHeight().Padding(0.f, 0.f, 0.f, 16.f)[Label(T(TEXT("Racers that taught themselves to move. Real physics, no animation.")), 13, FSlateColor(Dim), false)]
			+ SVerticalBox::Slot().AutoHeight().Padding(0.f, 0.f, 0.f, 4.f)[Label(T(TEXT("TRACK")), 14, FSlateColor(Dim))]
			+ SVerticalBox::Slot().AutoHeight()[TrackList]
			+ SVerticalBox::Slot().AutoHeight().Padding(0.f, 16.f, 0.f, 4.f)[Label(T(TEXT("RACERS")), 14, FSlateColor(Dim))]
			+ SVerticalBox::Slot().AutoHeight()[Chips]
			+ SVerticalBox::Slot().AutoHeight().Padding(0.f, 16.f, 0.f, 0.f)[LapsRow]
			+ SVerticalBox::Slot().AutoHeight().Padding(0.f, 20.f, 0.f, 0.f).HAlign(HAlign_Center)
				[Button(Label(T(TEXT("START")), 24, FSlateColor(Gold)), [Self] { if (Self.IsValid()) Self->Start(); },
					[] { return true; }, [Self] { return Self.IsValid() && Self->CanStart(); }, 260.f, &StartButton)]
			+ SVerticalBox::Slot().AutoHeight().HAlign(HAlign_Center).Padding(0.f, 6.f, 0.f, 0.f)
				[SNew(STextBlock).Font(FCoreStyle::GetDefaultFontStyle("Regular", 12)).ColorAndOpacity(FSlateColor(Dim))
					.Text_Lambda([Self] { FString W; if (Self.IsValid()) Self->CanStart(&W); return T(W); })]];
	Ui = SNew(SOverlay)
		+ SOverlay::Slot()[SAssignNew(ScreenProbe, SRaceProbe)[SNew(SBorder).BorderImage(&Backdrop())]]
		+ SOverlay::Slot().HAlign(HAlign_Center).VAlign(VAlign_Center).Padding(FMargin(16.f, 16.f, 16.f, 48.f))
			[SNew(SScaleBox).Stretch(EStretch::ScaleToFit).StretchDirection(EStretchDirection::DownOnly)[SAssignNew(MenuPanel, SRaceProbe)[Panel_]]]
		// the build stamp, in Slate here: the Canvas one is drawn under the menu's opaque backdrop
		+ SOverlay::Slot().HAlign(HAlign_Right).VAlign(VAlign_Bottom).Padding(FMargin(12.f, 8.f))
			[SAssignNew(MenuStamp, SRaceProbe)[Label(T(BuildStamp()), 11, FSlateColor(FLinearColor(1.f, 1.f, 1.f, 0.7f)), false)]];
	Mount(Ui, 10);
}

// --- the race -----------------------------------------------------------------------------------------------------------

void ARaceHUD::BuildRace()
{
	TWeakObjectPtr<ARaceHUD> Self(this);
	auto Finished = [Self] { return Self.IsValid() && Self->Race.bRace && Self->Race.Phase == ERacePhase::Finished; };
	auto Paused = [Self, Finished] { return Self.IsValid() && Self->bPaused && !Finished(); };

	// the results card: the classified order, then where to go next
	TSharedRef<SVerticalBox> Rows = SNew(SVerticalBox);
	for (int32 k = 0; k < 6; ++k)	// rows bound to the live standings (empty when there are fewer racers)
	{
		Rows->AddSlot().AutoHeight().Padding(0.f, 3.f)
			[SNew(SHorizontalBox)
				.Visibility_Lambda([Self, k] { return Self.IsValid() && Self->Race.Rows.IsValidIndex(k) ? EVisibility::Visible : EVisibility::Collapsed; })
				+ SHorizontalBox::Slot().AutoWidth().Padding(0.f, 0.f, 10.f, 0.f)
					[SNew(SBox).WidthOverride(36.f)[SNew(STextBlock).Font(FCoreStyle::GetDefaultFontStyle("Bold", 18)).ColorAndOpacity(FSlateColor(Gold))
						.Text_Lambda([Self, k] { return T(Self.IsValid() && Self->Race.Rows.IsValidIndex(k) ? FString::Printf(TEXT("%d."), k + 1) : TEXT("")); })]]
				+ SHorizontalBox::Slot().FillWidth(1.f)
					[SNew(STextBlock).Font(FCoreStyle::GetDefaultFontStyle("Bold", 18))
						.ColorAndOpacity_Lambda([Self, k] { return FSlateColor(Self.IsValid() && Self->Race.Rows.IsValidIndex(k) ? Self->Race.Rows[k].Color : FLinearColor::White); })
						.Text_Lambda([Self, k] { return T(Self.IsValid() && Self->Race.Rows.IsValidIndex(k) ? Self->Race.Rows[k].Name : TEXT("")); })]
				+ SHorizontalBox::Slot().AutoWidth()
					[SNew(STextBlock).Font(FCoreStyle::GetDefaultFontStyle("Regular", 18)).ColorAndOpacity(FSlateColor(Ink))
						.Text_Lambda([Self, k]
						{
							if (!Self.IsValid() || !Self->Race.Rows.IsValidIndex(k)) return T(TEXT(""));
							const FRaceHudRow& R = Self->Race.Rows[k];
							return T(R.FinishTime >= 0.0 ? FString::Printf(TEXT("%.2f s"), R.FinishTime) : FString::Printf(TEXT("DNF  %.0f m"), R.Distance));
						})]];
	}
	TSharedRef<SWidget> Results = SNew(SBorder).BorderImage(&Card()).Padding(FMargin(26.f, 20.f))
		[SNew(SBox).MinDesiredWidth(380.f)
			[SNew(SVerticalBox)
				+ SVerticalBox::Slot().AutoHeight()[SNew(STextBlock).Font(FCoreStyle::GetDefaultFontStyle("Bold", 24)).ColorAndOpacity(FSlateColor(Ink))
					.Text_Lambda([Self] { return T(Self.IsValid() ? Self->Race.Track + (Self->Race.bCalled ? TEXT("  ·  called") : TEXT("  ·  results")) : TEXT("")); })]
				+ SVerticalBox::Slot().AutoHeight().Padding(0.f, 10.f)[Rows]
				+ SVerticalBox::Slot().AutoHeight().Padding(0.f, 8.f, 0.f, 0.f)
					[SNew(SHorizontalBox)
						+ SHorizontalBox::Slot().AutoWidth().Padding(0.f, 0.f, 8.f, 0.f)[Button(Label(T(TEXT("MENU")), 16, FSlateColor(Ink)), [Self] { if (Self.IsValid()) Self->BackToMenu(); })]
						+ SHorizontalBox::Slot().AutoWidth().Padding(0.f, 0.f, 8.f, 0.f)[Button(Label(T(TEXT("REMATCH")), 16, FSlateColor(Ink)), [Self] { if (Self.IsValid()) Self->Rematch(); })]
						+ SHorizontalBox::Slot().AutoWidth()[Button(Label(T(TEXT("NEXT TRACK")), 16, FSlateColor(Ink)), [Self] { if (Self.IsValid()) Self->NextTrack(); })]]]];

	// the pause sheet
	TSharedRef<SWidget> Sheet = SNew(SBorder).BorderImage(&Card()).Padding(FMargin(26.f, 20.f))
		.Visibility_Lambda([Paused] { return Paused() ? EVisibility::Visible : EVisibility::Collapsed; })
		[SNew(SVerticalBox)
			+ SVerticalBox::Slot().AutoHeight().HAlign(HAlign_Center).Padding(0.f, 0.f, 0.f, 12.f)[Label(T(TEXT("PAUSED")), 26, FSlateColor(Gold))]
			+ SVerticalBox::Slot().AutoHeight().Padding(0.f, 3.f)[Button(Label(T(TEXT("RESUME")), 16, FSlateColor(Ink)), [Self] { if (Self.IsValid()) Self->TogglePause(); }, nullptr, nullptr, 220.f)]
			+ SVerticalBox::Slot().AutoHeight().Padding(0.f, 3.f)[Button(Label(T(TEXT("RESTART")), 16, FSlateColor(Ink)), [Self] { if (Self.IsValid()) { Self->TogglePause(); Self->Rematch(); } }, nullptr, nullptr, 220.f)]
			+ SVerticalBox::Slot().AutoHeight().Padding(0.f, 3.f)[Button(Label(T(TEXT("MENU")), 16, FSlateColor(Ink)), [Self] { if (Self.IsValid()) Self->BackToMenu(); }, nullptr, nullptr, 220.f)]];

	Ui = SNew(SOverlay)
		+ SOverlay::Slot()[SAssignNew(ScreenProbe, SRaceProbe)[SNew(SBox)]]
		+ SOverlay::Slot().HAlign(HAlign_Right).VAlign(VAlign_Top).Padding(FMargin(12.f))
			[SAssignNew(Gear, SRaceProbe)[Button(Label(T(TEXT("II")), 18, FSlateColor(Ink)), [Self] { if (Self.IsValid()) Self->TogglePause(); },
				[Paused] { return Paused(); }, [Finished] { return !Finished(); }, Touch)]]
		+ SOverlay::Slot().HAlign(HAlign_Center).VAlign(VAlign_Center)[Sheet]
		+ SOverlay::Slot().HAlign(HAlign_Center).VAlign(VAlign_Center).Padding(FMargin(16.f))
			[SNew(SScaleBox).Stretch(EStretch::ScaleToFit).StretchDirection(EStretchDirection::DownOnly)
				// visibility on the scale box: one around a collapsed card kept the zero size it measured and never showed it
				.Visibility_Lambda([Finished] { return Finished() ? EVisibility::Visible : EVisibility::Collapsed; })[Results]];
	Mount(Ui, 10);
}
