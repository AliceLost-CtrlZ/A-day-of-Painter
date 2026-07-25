"""The survey: one object holding a finished country and everything known
about it. Build order matters -- rivers are named before the towns that take
their names from them.
"""

import numpy as np

from . import naming, settle
from .world import KM_PER_CELL, METRES_PER_UNIT, World


class Survey:
    def __init__(self, seed=17, shape=(420, 620), steps=44, n_sites=26,
                 step=2, verbose=True):
        self.w = World(seed=seed, shape=shape, steps=steps, verbose=verbose)
        w = self.w
        if verbose:
            print("· siting")

        comp, sizes = naming.land_components(w.land)
        main = int(np.argmax(sizes))
        small = np.zeros_like(w.land)
        for i, n in enumerate(sizes):
            if i != main and n < 0.02 * sizes[main]:
                small |= (comp == i)

        self.sites = settle.place(w, n=n_sites, min_sep=max(9, shape[0] // 26),
                                  small_island=small)
        if verbose:
            print("· cutting roads")
        self.paths, self.D, self.fields, self.cost = settle.roads(w, self.sites, step=step)

        if verbose:
            print("· naming")
        self.namer = naming.Namer(w, self.sites, self.cost, step=step)
        self.rivers, self.children = naming.river_systems(w, max_systems=13,
                                                          min_len=max(14, shape[0] // 14))
        self.river_names = [self.namer.name_river(r) for r in self.rivers]
        self.namer.index_rivers(self.rivers, self.river_names)

        self.site_names = [self.namer.name_site(s) for s in self.sites]
        for s, n in zip(self.sites, self.site_names):
            s.update(n)

        self.peaks = self.namer._peaks
        self.peak_names = [self.namer.name_peak(p) for p in self.peaks]
        for p, n in zip(self.peaks, self.peak_names):
            p.update(n)

        self.seas = []
        for cells in w.inland_seas:
            self.seas.append(self.namer.name_water_body(cells, "sea"))
        own = self.namer.owner_c
        step = step
        h, wd = w.z.shape
        own_full = np.repeat(np.repeat(own, step, 0), step, 1)[:h, :wd]
        self.regions = [self.namer.name_region(i, own_full)
                        for i in range(len(self.namer.tongues))]

        # A name for the whole country: the largest tongue's word for itself.
        counts = np.bincount([s["tongue_idx"] for s in self.sites],
                             minlength=len(self.namer.tongues))
        self.leading = int(np.argmax(counts))
        self.country = self.namer.name_country(self.leading)
        self.title = self.country["name"]
        if verbose:
            print(f"· surveyed: {self.title}")

    def summary(self):
        w = self.w
        return dict(
            title=self.title,
            area_km2=int(w.land.sum() * KM_PER_CELL ** 2),
            highest=max(self.peaks, key=lambda p: p["m"]) if self.peaks else None,
            population=sum(s["pop"] for s in self.sites),
            towns=len(self.sites),
            rivers=len(self.rivers),
        )
