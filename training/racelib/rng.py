"""SplitMix64: the race's seeded dice. Source/PoRaceUnreal/RaceRng.h is the same generator, bit for bit.

Unity's System.Random cannot be reproduced outside .NET, so seeds from the Unity build do not carry over.
"""

MASK = (1 << 64) - 1


class SplitMix64:
    def __init__(self, seed: int):
        self.state = seed & MASK

    def next_u64(self) -> int:
        self.state = (self.state + 0x9E3779B97F4A7C15) & MASK
        z = self.state
        z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & MASK
        z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & MASK
        return z ^ (z >> 31)

    def uniform(self) -> float:
        """[0, 1) with 53 random bits."""
        return (self.next_u64() >> 11) * (1.0 / 9007199254740992.0)

    def below(self, n: int) -> int:
        """[0, n). The modulo bias (n is a handful of lanes) is part of the contract, not a bug."""
        return self.next_u64() % n

    def shuffle(self, items: list) -> list:
        """Fisher-Yates, from the back."""
        out = list(items)
        for i in range(len(out) - 1, 0, -1):
            j = self.below(i + 1)
            out[i], out[j] = out[j], out[i]
        return out
