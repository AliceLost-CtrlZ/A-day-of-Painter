"""Read the land, then say what it is called.

Every name here is a claim about its place. A town is named for the water it
sits on, the trees around it, the pass it guards; the words are then aged by
the local dialect. Nothing is drawn from a list of pretty syllables.
"""

from collections import defaultdict, deque

import numpy as np

from . import climate, settle, tongue
from .world import METRES_PER_UNIT, KM_PER_CELL

BIOME_WORD = {
    climate.FOREST: "oak", climate.TAIGA: "pine", climate.WOODLAND: "birch",
    climate.MARSH: "reed", climate.STEPPE: "grass", climate.SCRUB: "ash",
    climate.DESERT: "stone", climate.TUNDRA: "moor", climate.ALPINE: "stone",
    climate.ICE: "white",
}


def land_components(land):
    """Label separate landmasses so islands can be recognised as islands."""
    h, w = land.shape
    lab = np.full((h, w), -1, int)
    sizes = []
    nid = 0
    for sy in range(h):
        for sx in range(w):
            if land[sy, sx] and lab[sy, sx] < 0:
                q = deque([(sy, sx)])
                lab[sy, sx] = nid
                n = 0
                while q:
                    y, x = q.popleft()
                    n += 1
                    for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1),
                                   (-1, -1), (-1, 1), (1, -1), (1, 1)):
                        ny, nx = y + dy, x + dx
                        if 0 <= ny < h and 0 <= nx < w and land[ny, nx] and lab[ny, nx] < 0:
                            lab[ny, nx] = nid
                            q.append((ny, nx))
                sizes.append(n)
                nid += 1
    return lab, np.array(sizes)


def river_systems(w, max_systems=14, min_len=18):
    """Trace main stems from every river mouth, largest first."""
    h, wd = w.z.shape
    rec = w.rec
    disch = w.discharge.ravel()
    land = w.land.ravel()

    children = defaultdict(list)
    for i in range(h * wd):
        r = rec[i]
        if r != i and land[i]:
            children[r].append(i)

    mouths = []
    for i in range(h * wd):
        if land[i] and rec[i] != i and not land[rec[i]]:
            mouths.append(i)
    mouths.sort(key=lambda i: -disch[i])

    systems = []
    for m in mouths[:max_systems * 3]:
        stem = [m]
        cur = m
        while True:
            kids = children.get(cur)
            if not kids:
                break
            nxt = max(kids, key=lambda k: disch[k])
            if disch[nxt] < disch[m] * 0.012:
                break
            stem.append(nxt)
            cur = nxt
        if len(stem) < min_len:
            continue
        cells = [divmod(i, wd) for i in stem]
        systems.append(dict(mouth=divmod(m, wd), cells=cells,
                            discharge=float(disch[m]), length_km=len(stem) * KM_PER_CELL))
        if len(systems) >= max_systems:
            break
    return systems, children


def peaks(w, n=10, sep=22):
    """Prominent summits: local maxima separated by a decent distance."""
    z = np.where(w.land, w.z, -1)
    h, wd = z.shape
    yy, xx = np.mgrid[0:h, 0:wd]
    work = z.copy()
    out = []
    for _ in range(n):
        idx = int(np.argmax(work))
        y, x = divmod(idx, wd)
        if work[y, x] <= 0.35:
            break
        out.append(dict(y=y, x=x, m=float(z[y, x] * METRES_PER_UNIT)))
        work = np.where((yy - y) ** 2 + (xx - x) ** 2 < sep ** 2, -1, work)
    return out


class Namer:
    def __init__(self, w, sites, cost_grid, step=2, rng=None):
        self.w = w
        self.sites = sites
        self.step = step
        self.rng = rng or w.rng
        self.cost = cost_grid
        self.comp, self.comp_sizes = land_components(w.land)
        self.main_comp = int(np.argmax(self.comp_sizes))

        self.used_names = set()
        self.used_keys = set()
        self.used_mods = defaultdict(int)
        self.used_heads = defaultdict(int)
        self._peaks = peaks(w, n=12)

        hearths = self._pick_hearths()
        self.tongues = tongue.make_tongues(self.rng, hearths)
        self._distance_fields(hearths)

    # -- territory ----------------------------------------------------
    def _pick_hearths(self):
        """Three well-separated cradles among the better sites."""
        cands = self.sites[:14]
        first = cands[0]
        def d2(a, b):
            return (a["y"] - b["y"]) ** 2 + (a["x"] - b["x"]) ** 2
        second = max(cands, key=lambda s: d2(s, first))
        third = max(cands, key=lambda s: min(d2(s, first), d2(s, second)))
        return [(s["y"], s["x"]) for s in (first, second, third)]

    def _distance_fields(self, hearths):
        step = self.step
        self.fields = []
        for (y, x) in hearths:
            cy, cx = y // step, x // step
            if self.cost[cy, cx] >= settle.IMPASSABLE:
                ys, xs = np.where(self.cost < settle.IMPASSABLE)
                k = np.argmin((ys - cy) ** 2 + (xs - cx) ** 2)
                cy, cx = int(ys[k]), int(xs[k])
            d, _ = settle.dijkstra(self.cost, (cy, cx))
            self.fields.append(d)
        F = np.stack(self.fields)
        self.owner_c = np.argmin(np.where(np.isfinite(F), F, np.inf), axis=0)
        reach = np.isfinite(F).any(axis=0)
        self.owner_c = np.where(reach, self.owner_c, -1)
        # Normalising distance per tongue, so `frac` is comparable across them.
        self.dmax = []
        for i, d in enumerate(self.fields):
            own = (self.owner_c == i) & np.isfinite(d)
            self.dmax.append(float(np.percentile(d[own], 97)) if own.any() else 1.0)

    def law_field(self):
        """Integer count of sound changes reaching each cell.

        Boundaries between its levels are the isoglosses: lines beyond which
        a given change has not travelled.
        """
        out = np.full(self.owner_c.shape, -1, int)
        for i, tg in enumerate(self.tongues):
            m = (self.owner_c == i) & np.isfinite(self.fields[i])
            if not m.any():
                continue
            fr = np.clip(self.fields[i] / (self.dmax[i] + 1e-9), 0, 1)
            share = 1.0 - 0.62 * np.power(fr, 0.85)
            out = np.where(m, np.round(len(tg.laws) * share).astype(int), out)
        return out

    def at(self, y, x):
        """(tongue index, how far out of its range this point lies 0..1)"""
        cy, cx = min(y // self.step, self.owner_c.shape[0] - 1), \
                 min(x // self.step, self.owner_c.shape[1] - 1)
        t = int(self.owner_c[cy, cx])
        if t < 0:
            # Unreachable on foot -- an island. It belongs to the nearest
            # tongue as the crow flies, and keeps very archaic forms.
            best, bd = 0, 1e18
            for i, hs in enumerate([tg.hearth for tg in self.tongues]):
                dd = (hs[0] - y) ** 2 + (hs[1] - x) ** 2
                if dd < bd:
                    best, bd = i, dd
            return best, 1.0
        d = self.fields[t][cy, cx]
        return t, float(np.clip(d / (self.dmax[t] + 1e-9), 0, 1.15))

    # -- feature reading ----------------------------------------------
    def index_rivers(self, systems, named):
        """Map every stem cell to its river, so towns can be named after it."""
        self.river_at = {}
        for sysm, rec in zip(systems, named):
            for (y, x) in sysm["cells"]:
                for dy in range(-2, 3):
                    for dx in range(-2, 3):
                        self.river_at.setdefault((y + dy, x + dx), (sysm, rec))

    def _site_concepts(self, s):
        w = self.w
        y, x = s["y"], s["x"]
        big = np.percentile(w.discharge[w.land], 99.5)
        q = w.discharge[y, x] / (big + 1e-9)
        island = (self.comp[y, x] != self.main_comp)
        self._named_from = None
        on_river = self.river_at.get((y, x)) if hasattr(self, "river_at") else None

        heads = []                     # (generic, why) -- all of them true
        if island:
            heads.append(("island", "on an island"))
            heads.append(("haven", "an island anchorage"))
        if s["harbour"] and q > 0.10:
            heads.append(("mouth", "at the mouth of a river"))
        if s["harbour"]:
            heads += [("haven", "a sheltered anchorage"),
                      ("bay", "on the bay"), ("cape", "on the headland")]
        if q > 0.25 and w.slope[y, x] < 0.02:
            heads += [("ford", "at a crossing place"),
                      ("bridge", "at the bridge")]
        if q > 0.06:
            heads += [("river", "on the river"), ("mill", "at the water mill")]
        if w.z[y, x] > 0.55:
            heads += [("pass", "high in the hills"), ("hill", "on the hill")]
        if w.lake[max(0, y - 3):y + 4, max(0, x - 3):x + 4].any():
            heads.append(("lake", "beside a lake"))
        if w.water_dist[y, x] < 2.5:
            heads.append(("spring", "at a spring"))
        if s["pop"] > 30000:
            heads += [("market", "a market of the interior"),
                      ("gate", "the gate of the province")]
        if s["pop"] > 14000:
            heads += [("wall", "a walled town"), ("fort", "about the old fort")]
        heads += [("field", "among the fields"), ("meadow", "on the meadows"),
                  ("town", "a settlement"), ("hall", "about the hall"),
                  ("house", "a farmstead grown large"),
                  ("shelter", "a refuge on the road")]

        # Among the true options, prefer the generic least worn out already:
        # a country with thirty places all called -mouth reads as a list.
        seen = {}
        for gen, why in heads:
            seen.setdefault(gen, why)
        ordered = sorted(seen.items(),
                         key=lambda kv: (self.used_heads[kv[0]],
                                         list(seen).index(kv[0])))
        head, why = ordered[0]

        # A town on a named river takes that river's root: the Exe gives
        # Exmouth. Otherwise it is named for what is around it.
        inherited = None
        if on_river is not None and head in ("mouth", "ford", "bridge", "river", "haven"):
            sysm, rec = on_river
            inherited = rec["parts"][0]
            cands = [inherited]
            self._named_from = rec
        else:
            # Every candidate below is *true* of the site. Which one gets used
            # is decided later by whichever is rarest on the map so far, so the
            # gazetteer diversifies without any of it becoming a lie.
            cands = []
            if w.temp[y, x] < 3.0:
                cands.append("cold")
            if w.precip[y, x] < 380:
                cands.append("dry")
            elif w.precip[y, x] > 1250:
                cands.append("deep")
            if w.z[y, x] > 0.8 and head != "pass":
                cands.append("high")
            if w.slope[y, x] > 0.045:
                cands.append("cliff")
            b = int(w.biome[y, x])
            if b in BIOME_WORD and head != "island":
                cands.append(BIOME_WORD[b])
            if w.coast_dist[y, x] > 28:
                cands.append("far")
            if self.near_peak(y, x):
                cands.append("stone")
            if w.lake[max(0, y - 5):y + 6, max(0, x - 5):x + 6].any():
                cands.append("quiet")
            if (w.biome[max(0, y - 4):y + 5, max(0, x - 4):x + 5] == climate.MARSH).any():
                cands.append("reed")
            if s["pop"] > 45000:
                cands.append("king")
            if not cands:
                cands = ["old", "broad", "quiet", "narrow", "grey"]

        return cands, head, why, inherited

    FALLBACK = ["old", "new", "far", "narrow", "broad", "grey", "black",
                "white", "green", "red", "quiet", "high"]

    def _distinct(self, tg, cands, head, frac, pair=False):
        """Choose the first candidate whose etymology is not already taken.

        Uniqueness is enforced on the sense, not the spelling: two towns may
        drift into similar shapes, but no two are named the same thing.
        """
        pool = list(dict.fromkeys(list(cands) + self.FALLBACK))
        for i, m in enumerate(pool):
            mods = [m]
            if pair:
                second = next((c for c in pool if c != m), None)
                if second:
                    mods = [second, m]
            key = (tg.name, tuple(mods), head)
            if key in self.used_keys:
                continue
            name, proto, applied = tg.name_for(mods + [head], frac, trace=True)
            if name in self.used_names:
                continue
            self.used_keys.add(key)
            self.used_names.add(name)
            return mods + [head], name, proto, applied
        # Everything collided: fall through with the first option regardless.
        mods = [pool[0]]
        name, proto, applied = tg.name_for(mods + [head], frac, trace=True)
        self.used_names.add(name)
        return mods + [head], name, proto, applied

    def near_peak(self, y, x, r=14):
        return any((p["y"] - y) ** 2 + (p["x"] - x) ** 2 < r * r for p in self._peaks)

    def name_site(self, s):
        cands, head, why, inherited = self._site_concepts(s)
        t, frac = self.at(s["y"], s["x"])
        tg = self.tongues[t]

        # Prefer the rarest true modifier, so the map is not all Oakfords.
        if inherited is None:
            cands = sorted(cands, key=lambda c: (self.used_mods[c], cands.index(c)))
        mods = cands[:1]
        if s["pop"] > 40000 and len(cands) > 1:
            mods = cands[:2]

        pair = s["pop"] > 40000 and len(cands) > 1
        parts, name, proto, applied = self._distinct(tg, cands, head, frac, pair)
        for m in parts[:-1]:
            self.used_mods[m] += 1
        self.used_heads[parts[-1]] += 1

        return dict(name=name, tongue=tg.name, tongue_idx=t, proto=proto,
                    parts=parts, gloss=tg.gloss(parts), frac=frac,
                    laws=applied, why=why, inherited=inherited,
                    named_from=self._named_from, k_reached=tg.n_laws_at(frac),
                    n_laws=len(tg.laws), tongue_obj=tg)

    def name_river(self, sysm):
        y, x = sysm["mouth"]
        t, frac = self.at(y, x)
        tg = self.tongues[t]
        # Hydronyms are the oldest layer of any toponymy: they resist change.
        frac = 0.55 + 0.45 * frac
        cells = sysm["cells"]
        mid = cells[len(cells) // 2]
        head = cells[-1]
        cands = []
        if sysm["discharge"] > np.percentile(self.w.discharge[self.w.land], 99.85):
            cands.append("king")
        if self.w.precip[mid] > 1150:
            cands.append("deep")
        if self.w.z[head] > 0.75:
            cands.append("high")
        if self.w.temp[head] < 1.0:
            cands.append("cold")
        b = int(self.w.biome[mid])
        if b in BIOME_WORD:
            cands.append(BIOME_WORD[b])
        drop = float(self.w.z[head] - self.w.z[mid])
        cands.append("narrow" if drop > 0.5 else "broad")
        cands += ["grey", "black", "old", "green", "white"]
        cands = sorted(cands, key=lambda c: (self.used_mods[c], cands.index(c)))

        km = sysm["length_km"]
        gen = "river" if km > 200 else ("water" if km > 100 else
              ("bend" if km > 60 else "spring"))
        parts, name, proto, applied = self._distinct(tg, cands, gen, frac)
        self.used_mods[parts[0]] += 1
        return dict(name=name, tongue=tg.name, proto=proto, parts=parts,
                    gloss=tg.gloss(parts), laws=applied, frac=frac)

    def name_peak(self, p):
        t, frac = self.at(p["y"], p["x"])
        tg = self.tongues[t]
        frac = 0.4 + 0.6 * frac       # summits are conservative too
        cands = ["white"] if p["m"] > 2100 else (
            ["cold"] if self.w.temp[p["y"], p["x"]] < 0 else ["grey", "stone"])
        cands = cands + ["stone", "cliff", "old", "black", "high", "far"]
        gen = "mountain" if p["m"] > 1500 else "hill"
        parts, name, proto, applied = self._distinct(tg, cands, gen, frac)
        return dict(name=name, tongue=tg.name, proto=proto, parts=parts,
                    gloss=tg.gloss(parts), laws=applied)

    def name_water_body(self, cells, kind):
        # Anchor the label at the basin's pole of inaccessibility, so a
        # crescent-shaped sea does not get its name written on dry land.
        ys, xs = self._deep_point(cells)
        t, frac = self.at(ys, xs)
        tg = self.tongues[t]
        frac = 0.5 + 0.5 * frac
        parts = (["quiet", "sea"] if kind == "sea" else ["deep", "lake"])
        name, proto, applied = tg.name_for(parts, frac, trace=True)
        return dict(name=name, tongue=tg.name, proto=proto, parts=parts,
                    gloss=tg.gloss(parts), laws=applied, y=ys, x=xs)

    def _deep_point(self, cells):
        arr = np.array(cells)
        y0, x0 = arr[:, 0].min(), arr[:, 1].min()
        y1, x1 = arr[:, 0].max(), arr[:, 1].max()
        m = np.zeros((y1 - y0 + 3, x1 - x0 + 3), bool)
        m[arr[:, 0] - y0 + 1, arr[:, 1] - x0 + 1] = True
        from .world import _chamfer
        d = _chamfer(~m)
        k = int(np.argmax(np.where(m, d, -1)))
        yy, xx = divmod(k, m.shape[1])
        return int(yy + y0 - 1), int(xx + x0 - 1)

    def name_region(self, idx, own_full=None):
        """A region is named for how it actually differs from the others."""
        tg = self.tongues[idx]
        cands = []
        if own_full is not None:
            m = (own_full == idx) & self.w.land
            if m.any():
                allm = self.w.land
                z, t, p = self.w.z[m].mean(), self.w.temp[m].mean(), self.w.precip[m].mean()
                if z > self.w.z[allm].mean() * 1.15:
                    cands.append("high")
                if t < self.w.temp[allm].mean() - 1.0:
                    cands.append("cold")
                if p > self.w.precip[allm].mean() * 1.15:
                    cands.append("deep")
                elif p < self.w.precip[allm].mean() * 0.85:
                    cands.append("dry")
                if self.w.coast_dist[m].mean() > self.w.coast_dist[allm].mean():
                    cands.append("far")
        cands += ["broad", "old", "green", "quiet"]
        parts, name, proto, applied = self._distinct(tg, cands, "land", 0.0)
        return dict(name=name, tongue=tg.name, proto=proto, parts=parts,
                    gloss=tg.gloss(parts), laws=applied)

    def name_country(self, idx):
        tg = self.tongues[idx]
        parts = ["folk", "land"]
        name, proto, applied = tg.name_for(parts, 0.0, trace=True)
        return dict(name=name, tongue=tg.name, proto=proto, parts=parts,
                    gloss=tg.gloss(parts), laws=applied)
