#pragma once

// Writing the training model's own numbers over URLab's rebuild of it (docs/20261110/slice1.md):
// URLab drops the MJCF's <option> block, gives a free joint the default class's damping and armature, zeroes sites
// and passes every value through single precision. The fingerprints (training/contract.py for a creature,
// training/build_track_model.py for a track) carry the exact numbers; these write them back.

#include "CoreMinimal.h"
#include <mujoco/mujoco.h>

class FJsonObject;

namespace RaceModel
{
	/** The fingerprint's "option" object onto m->opt. */
	void ApplyOptions(mjModel* m, const FJsonObject& Option);

	/**
	 * A fingerprint's "model" (creature) or "world" (track) object onto m: bodies, joints and their dofs, actuators,
	 * sites, geoms. Every name is looked up as Prefix + name (a racer's "blue_"). Entries marked "optional" that the
	 * model does not have are skipped. Does not call mj_setConst: call it once after the last write.
	 * Returns how many required names were missing (0 = all matched).
	 */
	int32 ApplyNumbers(mjModel* m, const FJsonObject& Numbers, const FString& Prefix);

	/** mj_saveModel into Saved/PoRace/<FileName>; returns the full path. */
	FString Save(const mjModel* m, const TCHAR* FileName);
}
