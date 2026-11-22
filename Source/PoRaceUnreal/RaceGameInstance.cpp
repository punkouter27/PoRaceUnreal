#include "RaceGameInstance.h"

#include "Kismet/GameplayStatics.h"
#include "RaceNames.h"
#include "RaceRegistry.h"

void URaceGameInstance::StartRace(UObject* Context)
{
	const FString Level = RaceRegistry::LevelOf(Track);
	FString Options = FString::Printf(TEXT("Seed=%d"), FMath::RandRange(0, 0xFFFF));
	if (Racers.Num()) Options += TEXT("?Racers=") + FString::Join(Racers, TEXT(","));
	if (Laps > 0) Options += FString::Printf(TEXT("?Laps=%d"), Laps);
	if (bHandicap) Options += TEXT("?Handicap=1");
	UE_LOG(LogRace, Log, TEXT("menu: START %s ?%s"), *Level, *Options);
	UGameplayStatics::OpenLevel(Context, FName(*Level), true, Options);
}

void URaceGameInstance::OpenMenu(UObject* Context)
{
	UGameplayStatics::OpenLevel(Context, FName(TEXT("/Game/Project/Environments/Levels/L_Menu")), true);
}
