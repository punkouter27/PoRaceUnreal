// Automation tests for the idle demo mode (Po Game Standard C13). Run with a renderer (never -nullrhi), e.g.
//   UnrealEditor.exe PoRaceUnreal.uproject -ExecCmds="Automation RunTests PoRace.Showcase;Quit" -unattended -nosplash
//       -nosound -windowed -ResX=1280 -ResY=720 -TestExit="Automation Test Queue Empty"
#include "Misc/AutomationTest.h"
#include "RaceShowcase.h"

#if WITH_DEV_AUTOMATION_TESTS

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FRaceIdleClockTest, "PoRace.Showcase.IdleClock",
	EAutomationTestFlags::EditorContext | EAutomationTestFlags::ClientContext | EAutomationTestFlags::EngineFilter)

bool FRaceIdleClockTest::RunTest(const FString& Parameters)
{
	const URaceShowcaseConfig* Cfg = GetDefault<URaceShowcaseConfig>();
	TestEqual(TEXT("idle threshold is 30 s"), Cfg->IdleSeconds, 30.f);
	TestEqual(TEXT("frames over 0.25 s are ignored"), Cfg->MaxIdleFrameSeconds, 0.25f);
	const float Max = Cfg->MaxIdleFrameSeconds;
	const float Threshold = Cfg->IdleSeconds;

	// 29.5 s of 60 fps frames: not yet; one more second: demo mode
	float Idle = 0.f;
	bool bStart = false;
	for (int32 i = 0; i < 29 * 60 + 30; ++i) bStart = FRaceIdleClock::Advance(Idle, 1.f / 60.f, Max, Threshold);
	TestFalse(TEXT("29.5 s idle does not start demo mode"), bStart);
	for (int32 i = 0; i < 60; ++i) bStart = FRaceIdleClock::Advance(Idle, 1.f / 60.f, Max, Threshold);
	TestTrue(TEXT("30.5 s idle starts demo mode"), bStart);

	// long frames do not count: a 45 s stall alone, or 20 s of frames plus a 15 s hitch, is not 30 s idle
	Idle = 0.f;
	TestFalse(TEXT("one 45 s frame is not idle time"), FRaceIdleClock::Advance(Idle, 45.f, Max, Threshold));
	TestFalse(TEXT("a 0.26 s frame is not idle time"), FRaceIdleClock::Advance(Idle, 0.26f, Max, Threshold));
	TestEqual(TEXT("idle stays 0 after long frames"), Idle, 0.f);
	for (int32 i = 0; i < 20 * 60; ++i) FRaceIdleClock::Advance(Idle, 1.f / 60.f, Max, Threshold);
	TestFalse(TEXT("20 s + a 15 s hitch is not 30 s"), FRaceIdleClock::Advance(Idle, 15.f, Max, Threshold));
	FRaceIdleClock::Advance(Idle, 0.25f, Max, Threshold);
	TestTrue(TEXT("a 0.25 s frame still counts"), FMath::IsNearlyEqual(Idle, 20.25f, 0.01f));
	TestFalse(TEXT("negative frame time is ignored"), FRaceIdleClock::Advance(Idle, -1.f, Max, Threshold));
	TestTrue(TEXT("idle unchanged by a negative frame"), FMath::IsNearlyEqual(Idle, 20.25f, 0.01f));
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS
