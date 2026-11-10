#pragma once

// SplitMix64: the race's seeded dice. training/racelib/rng.py is the same generator, bit for bit.

#include "CoreMinimal.h"

struct FRaceRng
{
	uint64 State;

	explicit FRaceRng(uint64 Seed) : State(Seed) {}

	uint64 NextU64()
	{
		State += 0x9E3779B97F4A7C15ull;
		uint64 Z = State;
		Z = (Z ^ (Z >> 30)) * 0xBF58476D1CE4E5B9ull;
		Z = (Z ^ (Z >> 27)) * 0x94D049BB133111EBull;
		return Z ^ (Z >> 31);
	}

	/** [0, 1) with 53 random bits. */
	double Uniform() { return (double)(NextU64() >> 11) * (1.0 / 9007199254740992.0); }

	/** [0, N). The modulo bias is part of the contract (rng.py does the same). */
	uint64 Below(uint64 N) { return NextU64() % N; }

	/** Fisher-Yates from the back, as rng.py shuffle(). */
	template <typename T>
	void Shuffle(TArray<T>& Items)
	{
		for (int32 i = Items.Num() - 1; i > 0; --i)
		{
			const int32 j = (int32)Below((uint64)i + 1);
			Items.Swap(i, j);
		}
	}
};
