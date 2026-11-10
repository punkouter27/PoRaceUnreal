#pragma once

#include "CoreMinimal.h"
#include "Engine/GameInstance.h"
#include "RaceGameInstance.generated.h"

/**
 * What outlives a level: the menu's choices (so Rematch and Next keep them, and the menu reopens on them) and the
 * unattended loop's counters (-AutoStart / -AutoOk / -AutoLoops).
 */
UCLASS()
class PORACEUNREAL_API URaceGameInstance : public UGameInstance
{
	GENERATED_BODY()

public:
	FString Track;					// track id; empty = the first built one
	TArray<FString> Racers;			// racer names (lower case) picked on the menu; empty = every eligible one
	int32 Laps = 0;					// 0 = the track's default
	int32 Loops = 0;				// races completed this session (the loop test counts them)
	double FirstLoopMB = 0.0;		// memory at the end of the first loop (the leak check)

	/** Opens the track's level with these choices and a fresh seed: ?Racers=blue,matt?Laps=2?Seed=<n>. */
	void StartRace(UObject* Context);
	void OpenMenu(UObject* Context);
};
