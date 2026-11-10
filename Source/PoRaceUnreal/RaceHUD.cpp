#include "RaceHUD.h"

#include "Engine/Canvas.h"
#include "Engine/Engine.h"
#include "Engine/Font.h"
#include "Fonts/FontMeasure.h"
#include "Framework/Application/SlateApplication.h"
#include "Rendering/SlateRenderer.h"
#include "EngineUtils.h"
#include "Misc/ConfigCacheIni.h"

FString ARaceHUD::BuildStamp()
{
	FString Version;
	GConfig->GetString(TEXT("/Script/EngineSettings.GeneralProjectSettings"), TEXT("ProjectVersion"), Version, GGameIni);
	return FString::Printf(TEXT("v%s %s"), Version.IsEmpty() ? TEXT("0.1.0") : *Version, TEXT(PORACE_BUILD_VERSION));
}

float ARaceHUD::Text(const FString& S, float X, float Y, const FLinearColor& Color, float Size, bool bCentre, bool bRight)
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
	return Extent.Y;
}

void ARaceHUD::DrawHUD()
{
	Super::DrawHUD();
	if (!Canvas) return;
	const float W = Canvas->ClipX, H = Canvas->ClipY, Pad = 0.025f * FMath::Min(W, H);
	const float S = FMath::Clamp(H / 720.f, 0.75f, 3.f);	// point sizes grow with the window (1.0 at 720 p)

	if (!Controller.IsValid()) Controller = URacerController::Find(GetWorld());
	if (Controller.IsValid()) Controller->GetHud(Race);

	// rates: frames drawn and physics steps per wall second
	const double Now = FPlatformTime::Seconds();
	if (LastWall > 0.0)
	{
		const double Dt = FMath::Max(Now - LastWall, 1e-4);
		FpsSmooth = FMath::Lerp(FpsSmooth, 1.0 / Dt, 0.05);
		if (LastSteps >= 0 && Race.Steps >= LastSteps) HzSmooth = FMath::Lerp(HzSmooth, (Race.Steps - LastSteps) / Dt, 0.05);
	}
	LastWall = Now;
	LastSteps = Race.Steps;
	Text(FString::Printf(TEXT("%.0f fps  ·  %.0f Hz"), FpsSmooth, HzSmooth), 0.5f * W, Pad, FLinearColor(0.85f, 0.85f, 0.85f), 13.f * S, true);

	// build stamp, always
	Text(BuildStamp(), W - Pad, H - Pad - 20.f * S, FLinearColor(1.f, 1.f, 1.f, 0.7f), 12.f * S, false, true);

	if (!Race.bRace) return;

	// track and lap, then the standings
	int32 Lap = 1;
	for (const FRaceHudRow& R : Race.Rows) if (R.FinishTime < 0.0) { Lap = FMath::Min(R.Lap + 1, Race.Laps); break; }
	Text(Race.Laps > 1 ? FString::Printf(TEXT("%s  ·  Lap %d/%d"), *Race.Track, Lap, Race.Laps) : Race.Track, Pad, Pad, FLinearColor::White, 20.f * S);
	float Y = Pad + 38.f * S;
	for (int32 i = 0; i < Race.Rows.Num(); ++i)
	{
		const FRaceHudRow& R = Race.Rows[i];
		const FString Status = R.FinishTime >= 0.0 ? FString::Printf(TEXT("%.2f s"), R.FinishTime)
			: FString::Printf(TEXT("%.0f m%s"), R.Distance, R.bGettingUp ? TEXT("  GETTING UP") : R.State == ERacerState::Fallen ? TEXT("  DOWN")
				: R.State == ERacerState::Stumble ? TEXT("  stumble") : TEXT(""));
		Text(FString::Printf(TEXT("%d. %s"), i + 1, *R.Name), Pad, Y, R.Color, 16.f * S);
		Text(Status, Pad + 120.f * S, Y, FLinearColor(0.92f, 0.92f, 0.92f), 16.f * S);
		Y += 26.f * S;
	}
	Text(FString::Printf(TEXT("%.2f s"), Race.RaceTime), Pad, Y + 6.f * S, FLinearColor(0.92f, 0.92f, 0.92f), 16.f * S);

	// centre: countdown, GO, FINISH
	FString Big;
	if (Race.Phase == ERacePhase::Countdown) { Big = FString::FromInt(FMath::Max(1, FMath::CeilToInt(Race.CountdownLeft))); GoUntil = -1.0; }
	else if (Race.Phase == ERacePhase::Racing)
	{
		if (GoUntil < 0.0) GoUntil = Now + 1.0;
		if (Now < GoUntil) Big = TEXT("GO!");
	}
	else Big = TEXT("FINISH");
	if (!Big.IsEmpty()) Text(Big, 0.5f * W, 0.26f * H, FLinearColor(1.f, 0.85f, 0.2f), 90.f * S, true);
}
