"""Does the terrain actually obey the law it was built from?

Stream power drives a landscape towards S proportional to A^(-m/n), so a
regression of log channel slope on log drainage area should recover -m/n --
here -0.5. This is the one number that says whether the erosion parameters are
set sensibly rather than merely set to something that looks nice.

Borrowed, with thanks, from an earlier build of mine that had the sense to
write it the first time.
"""

import numpy as np

from atlas import terrain


def exponent(seed, shape=(240, 354), steps=24, area_min=60, area_max=20000):
    z, land = terrain.build(shape=shape, seed=seed, steps=steps, verbose=False)
    # Bare drainage area, not rainfall-weighted discharge: the law is in area.
    area, rec, filled, slope = terrain.flow_accumulate(z, 0.0)

    m = land & (area > area_min) & (area < area_max) & (slope > 1e-6)
    if m.sum() < 400:
        return None, 0
    A = np.log10(area[m])
    S = np.log10(slope[m])
    # Bin by area and take medians, so the fit is not dominated by the
    # enormous number of small headwater cells.
    bins = np.linspace(A.min(), A.max(), 22)
    idx = np.digitize(A, bins)
    xs, ys = [], []
    for b in range(1, len(bins)):
        sel = idx == b
        if sel.sum() >= 25:
            xs.append(A[sel].mean())
            ys.append(np.median(S[sel]))
    if len(xs) < 6:
        return None, int(m.sum())
    k, _ = np.polyfit(xs, ys, 1)
    return float(k), int(m.sum())


if __name__ == "__main__":
    print("regressing log(channel slope) on log(drainage area)")
    print("stream power with m=0.5, n=1 predicts -0.50\n")
    vals = []
    for s in [3, 11, 17, 23, 29, 41]:
        k, n = exponent(s)
        if k is None:
            print(f"  seed {s:>3}: too few channel cells")
            continue
        vals.append(k)
        print(f"  seed {s:>3}:  {k:+.3f}   ({n:,} channel cells)")
    if vals:
        print(f"\n  mean {np.mean(vals):+.3f}   sd {np.std(vals):.3f}"
              f"   error vs -0.500: {abs(np.mean(vals) + 0.5):.3f}")
