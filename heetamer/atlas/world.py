"""Assemble a world: ground, water bodies, weather, and the derived layers
everything else in the atlas reads from.
"""

from collections import deque

import numpy as np

from . import climate, terrain

METRES_PER_UNIT = 700.0   # relief units -> metres, chosen so the peaks are alpine
KM_PER_CELL = 2.4         # ground scale of one grid cell


def _chamfer(seed_mask):
    """Approximate Euclidean distance (in cells) to the nearest True cell."""
    big = 1e6
    d = np.where(seed_mask, 0.0, big)
    a, b = 1.0, 1.4142
    h, w = d.shape
    for _ in range(2):
        for y in range(1, h):
            row, prev = d[y], d[y - 1]
            cand = np.minimum(prev + a, np.r_[big, prev[:-1] + b])
            cand = np.minimum(cand, np.r_[prev[1:] + b, big])
            row = np.minimum(row, cand)
            for x in range(1, w):
                if row[x - 1] + a < row[x]:
                    row[x] = row[x - 1] + a
            for x in range(w - 2, -1, -1):
                if row[x + 1] + a < row[x]:
                    row[x] = row[x + 1] + a
            d[y] = row
        d = d[::-1, ::-1].copy()
    return d


def _label_water(land):
    """Split standing water into: open ocean (touching the frame) and basins."""
    h, w = land.shape
    water = ~land
    lab = np.full((h, w), -1, int)
    ocean = np.zeros((h, w), bool)

    q = deque()
    for x in range(w):
        for y in (0, h - 1):
            if water[y, x]:
                q.append((y, x)); ocean[y, x] = True
    for y in range(h):
        for x in (0, w - 1):
            if water[y, x]:
                q.append((y, x)); ocean[y, x] = True
    while q:
        y, x = q.popleft()
        for dy, dx in terrain.NB:
            ny, nx = y + dy, x + dx
            if 0 <= ny < h and 0 <= nx < w and water[ny, nx] and not ocean[ny, nx]:
                ocean[ny, nx] = True
                q.append((ny, nx))

    basins = []
    nid = 0
    for sy in range(h):
        for sx in range(w):
            if water[sy, sx] and not ocean[sy, sx] and lab[sy, sx] < 0:
                cells = []
                lab[sy, sx] = nid
                q = deque([(sy, sx)])
                while q:
                    y, x = q.popleft()
                    cells.append((y, x))
                    for dy, dx in terrain.NB:
                        ny, nx = y + dy, x + dx
                        if (0 <= ny < h and 0 <= nx < w and water[ny, nx]
                                and not ocean[ny, nx] and lab[ny, nx] < 0):
                            lab[ny, nx] = nid
                            q.append((ny, nx))
                basins.append(cells)
                nid += 1
    return ocean, lab, basins


class World:
    def __init__(self, seed=17, shape=(420, 620), steps=44, verbose=True):
        self.seed = seed
        self.shape = shape
        rng = np.random.default_rng(seed * 1013 + 7)
        self.rng = rng

        if verbose:
            print("· raising ground")
        self.z, self.land = terrain.build(shape=shape, seed=seed, steps=steps,
                                          verbose=verbose)
        h, w = shape

        if verbose:
            print("· sorting the waters")
        self.ocean, self.basin_id, self.basin_cells = _label_water(self.land)
        # Basins wider than this are seas in their own right, not ponds.
        self.inland_seas = [c for c in self.basin_cells if len(c) > 0.004 * h * w]

        if verbose:
            print("· weather")
        self.temp, self.lat = climate.temperature(shape, self.z)
        self.precip = climate.rainfall(self.z, self.land, self.temp)

        if verbose:
            print("· drainage")
        # Discharge is accumulated rainfall, not bare area: dry basins carry
        # small rivers even when they are large.
        wt = np.where(self.land, np.maximum(self.precip, 1e-4), 0.0)
        self.discharge, self.rec, self.filled, self.d8slope = terrain.flow_accumulate(
            self.z, 0.0, weight=wt)
        self.discharge = np.where(self.land, self.discharge, 0.0)

        # Depressions the flood had to fill are lakes.
        self.lake = self.land & ((self.filled - self.z) > 0.004)

        gy, gx = np.gradient(self.z)
        self.slope = np.hypot(gy, gx)
        self.water_dist = _chamfer(~self.land | self.lake)
        self.coast_dist = _chamfer(self.ocean)

        self.biome = climate.classify(self.z, self.land, self.temp, self.precip,
                                      self.slope, self.water_dist)
        if verbose:
            self.report()

    # --- convenience -----------------------------------------------------
    def metres(self, y, x):
        return float(self.z[y, x] * METRES_PER_UNIT)

    def river_mask(self, q=None):
        thr = np.percentile(self.discharge[self.land], 99.0) * 0.06
        return self.land & (self.discharge > thr) & ~self.lake

    def report(self):
        land = self.land
        print(f"  land {land.mean() * 100:.0f}%   peak {self.z.max() * METRES_PER_UNIT:,.0f} m")
        print(f"  inland seas: {len(self.inland_seas)}   lake cells: {self.lake.sum()}")
        names = climate.BIOME_NAMES
        counts = {}
        for k, n in names.items():
            c = int((self.biome == k).sum())
            if c:
                counts[n] = c / land.sum()
        for n, f in sorted(counts.items(), key=lambda kv: -kv[1]):
            print(f"  {f * 100:5.1f}%  {n}")
