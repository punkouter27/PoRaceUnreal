#pragma once

#include "CoreMinimal.h"
#include "GameFramework/HUD.h"
#include "RacerController.h"
#include "RaceHUD.generated.h"

/**
 * The race on screen (Canvas, so it draws the same in every build and the checks can read it):
 *   top left     track and lap, then the standings
 *   top centre   frame rate and physics rate
 *   centre       the countdown, GO, FINISH
 *   bottom right the build stamp (version + YYMMDD), always
 * Slice 4 replaces this with the full broadcast layout (corners, results card, menu).
 */
UCLASS()
class PORACEUNREAL_API ARaceHUD : public AHUD
{
	GENERATED_BODY()

public:
	virtual void DrawHUD() override;

	/** "v0.1.0 YYMMDD": the project version and the last commit's date (PoRaceUnreal.Build.cs). */
	static FString BuildStamp();

private:
	FRaceHud Race;
	TWeakObjectPtr<URacerController> Controller;
	double FpsSmooth = 0.0, HzSmooth = 0.0, LastWall = 0.0;
	int64 LastSteps = -1;
	double GoUntil = -1.0;

	/** Text at a point size (Slate font; FCanvasTextItem::Scale is ignored by the engine's runtime fonts). Returns its height. */
	float Text(const FString& S, float X, float Y, const FLinearColor& Color, float Size, bool bCentre = false, bool bRight = false);
};
