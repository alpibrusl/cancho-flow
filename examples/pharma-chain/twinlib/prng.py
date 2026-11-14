"""The twin's random numbers: SplitMix64 and integer arithmetic only (docs/use-cases.md section 2, T1).

Python's `random` is not used: its stream is a property of the Python version. Nothing here calls a floating-point function of the C
library, whose last bit can differ between platforms: every draw is an integer, and a probability is an integer in parts per million.
"""
import hashlib
from decimal import Decimal, localcontext

MASK = (1 << 64) - 1
PPM = 1_000_000


class SplitMix64:
    def __init__(self, seed):
        self.seed = seed
        self.s = seed & MASK

    def next_u64(self):
        self.s = (self.s + 0x9E3779B97F4A7C15) & MASK
        z = self.s
        z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & MASK
        z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & MASK
        return z ^ (z >> 31)

    def below(self, n):
        """An integer in [0, n), without modulo bias (rejection)."""
        limit = (1 << 64) - ((1 << 64) % n)
        while True:
            x = self.next_u64()
            if x < limit:
                return x % n

    def ppm(self):
        return self.below(PPM)

    def bernoulli(self, p_ppm):
        return self.ppm() < p_ppm

    def categorical(self, weighted):
        """weighted: a list of [value, weight] with integer weights; the value is returned."""
        total = sum(w for _, w in weighted)
        r = self.below(total)
        for value, w in weighted:
            if r < w:
                return value
            r -= w
        raise AssertionError("unreachable: r < total")

    def weighted_index(self, weights):
        total = sum(weights)
        r = self.below(total)
        for i, w in enumerate(weights):
            if r < w:
                return i
            r -= w
        raise AssertionError("unreachable: r < total")

    def poisson_milli(self, mean_milli):
        """A Poisson draw with mean mean_milli/1000, by inversion in decimal arithmetic (correctly rounded, so the same on every platform)."""
        with localcontext() as ctx:
            ctx.prec = 40
            lam = Decimal(mean_milli) / Decimal(1000)
            term = (-lam).exp()
            cdf = term
            u = Decimal(self.below(10**12)) / Decimal(10**12)
            k = 0
            while u >= cdf and k < 100000:
                k += 1
                term = term * lam / k
                cdf += term
            return k

    def normal_micro(self):
        """An integer with mean 0 and standard deviation 1,000,000 (the Irwin-Hall sum of twelve uniforms: exact, no libm)."""
        return sum(self.ppm() for _ in range(12)) - 6 * PPM

    def fork(self, label):
        """An independent stream named by a label, so that adding a table does not move the others."""
        h = hashlib.sha256(("%d:%s" % (self.seed, label)).encode("utf-8")).digest()
        return SplitMix64(int.from_bytes(h[:8], "big"))
