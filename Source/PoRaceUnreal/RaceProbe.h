#pragma once

// A pass-through widget that remembers the geometry it was last painted with: the layout check's measuring tape.
// (UE 5.8 does not keep the cached or paint-space geometry of widgets that do not tick; this one records its own.)

#include "CoreMinimal.h"
#include "Widgets/SCompoundWidget.h"

class SRaceProbe : public SCompoundWidget
{
public:
	SLATE_BEGIN_ARGS(SRaceProbe) {}
		SLATE_DEFAULT_SLOT(FArguments, Content)
	SLATE_END_ARGS()

	void Construct(const FArguments& Args) { ChildSlot[Args._Content.Widget]; }

	virtual int32 OnPaint(const FPaintArgs& Args, const FGeometry& Geometry, const FSlateRect& Culling, FSlateWindowElementList& Out,
		int32 Layer, const FWidgetStyle& Style, bool bParentEnabled) const override
	{
		Last = Geometry;
		bPainted = true;
		return SCompoundWidget::OnPaint(Args, Geometry, Culling, Out, Layer, Style, bParentEnabled);
	}

	/** Window pixels of the last paint (invalid when it has not been painted). */
	FBox2D Box() const
	{
		if (!bPainted) return FBox2D(ForceInit);
		const FVector2D P = Last.GetAbsolutePosition();
		return FBox2D(P, P + Last.GetAbsoluteSize());
	}

private:
	mutable FGeometry Last;
	mutable bool bPainted = false;
};
