#pragma once

#include "CoreMinimal.h"

/**
 * Shared Profile B UMG/Slate UI theme tokens for PoRaceUnreal.
 * Centralizes spacing, corner radii, typography sizes, minimum 48dp touch targets,
 * and standard RL policy colors (RED = heuristic bot, GREEN = reference RL, BLUE = custom).
 */
namespace RaceUiTheme
{
	inline constexpr float Space1 = 4.f;
	inline constexpr float Space2 = 8.f;
	inline constexpr float Space3 = 12.f;
	inline constexpr float Space4 = 16.f;
	inline constexpr float Space5 = 24.f;

	inline constexpr float RadiusS = 8.f;
	inline constexpr float RadiusM = 14.f;
	inline constexpr float RadiusL = 24.f;

	inline constexpr float TouchMin = 48.f;
	inline constexpr float SafePadding = 24.f;

	inline const FLinearColor BackdropColor(0.02f, 0.025f, 0.035f, 1.f);
	inline const FLinearColor CardColor(0.f, 0.f, 0.f, 0.78f);
	inline const FLinearColor PanelColor(0.07f, 0.075f, 0.09f, 1.f);
	inline const FLinearColor Gold(1.f, 0.82f, 0.25f, 1.f);
	inline const FLinearColor Dim(0.55f, 0.55f, 0.60f, 1.f);
	inline const FLinearColor Ink(0.93f, 0.93f, 0.95f, 1.f);

	// Standard RL policy badge palette
	inline const FLinearColor PolicyBot(1.f, 0.25f, 0.20f, 1.f);
	inline const FLinearColor PolicyRef(0.16f, 0.55f, 0.28f, 1.f);
	inline const FLinearColor PolicyCustom(0.20f, 0.50f, 1.f, 1.f);
}
