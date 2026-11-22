#pragma once

// Wrap URLab / MuJoCo includes in RACE_MUJOCO_INCLUDES_START / _END: their headers warn in every file that includes
// them (MuJoCo's mjsan.h redefines UE's ASAN_* macros: C4005; URLab's generated option defaults: C4305). The warnings
// are suppressed for those headers only, so this module itself still builds with 0 warnings.
#include "CoreMinimal.h"

#if defined(_MSC_VER) && !defined(__clang__)
	#define RACE_MUJOCO_INCLUDES_START THIRD_PARTY_INCLUDES_START __pragma(warning(disable: 4005 4305))
#else
	#define RACE_MUJOCO_INCLUDES_START THIRD_PARTY_INCLUDES_START
#endif
#define RACE_MUJOCO_INCLUDES_END THIRD_PARTY_INCLUDES_END
