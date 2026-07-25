"""The written half of the atlas.

A gazetteer that shows its working: for every place, what the ground is like,
what the name means, and which sound changes had reached that far when the
name settled into its present shape.
"""

import numpy as np

from . import climate
from .world import KM_PER_CELL, METRES_PER_UNIT

ORD = ["first", "second", "third", "fourth", "fifth", "sixth", "seventh",
       "eighth", "ninth", "tenth", "eleventh", "twelfth", "thirteenth",
       "fourteenth", "fifteenth"]


def _lat(w, y):
    return float(w.lat[y, 0])


def _lon(w, x, x0):
    """Degrees from the capital's meridian, at the map's mean latitude."""
    km_per_deg = 111.32 * np.cos(np.deg2rad(float(w.lat.mean())))
    return (x - x0) * KM_PER_CELL / km_per_deg


def _coord(w, y, x, x0):
    la, lo = _lat(w, y), _lon(w, x, x0)
    ns = "N"
    ew = "E" if lo >= 0 else "W"
    return f"{abs(la):.2f}°{ns}, {abs(lo):.2f}°{ew}"


def _bearing(dy, dx):
    ang = np.degrees(np.arctan2(-dy, dx)) % 360
    names = ["east", "north-east", "north", "north-west",
             "west", "south-west", "south", "south-east"]
    return names[int((ang + 22.5) // 45) % 8]


def _derivation(rec, tg):
    """The chain of sound changes, spelled as the map spells them."""
    if not rec["laws"]:
        return None
    chain = [tg.spell(rec["proto"])]
    for nm, desc, before, after in rec["laws"]:
        chain.append(tg.spell(after))
    return " → ".join(f"*{c}*" for c in chain[:-1]) + f" → **{chain[-1]}**"


def _law_notes(rec):
    return "; ".join(f"{nm} ({desc})" for nm, desc, _, _ in rec["laws"])


class Gazetteer:
    def __init__(self, sv):
        self.sv = sv
        self.w = sv.w
        self.cap = sv.sites[0]
        self.x0 = self.cap["x"]

    # -- helpers ------------------------------------------------------
    def site_setting(self, s):
        w = self.w
        y, x = s["y"], s["x"]
        bits = []
        m = w.z[y, x] * METRES_PER_UNIT
        bits.append(f"{m:,.0f} m above the sea" if m > 15 else "barely above the tide")
        b = int(w.biome[y, x])
        if b in climate.BIOME_NAMES:
            bits.append(f"in {climate.BIOME_NAMES[b]}")
        bits.append(f"rainfall {w.precip[y, x]:,.0f} mm")
        bits.append(f"mean {w.temp[y, x]:.1f}°C")
        return "; ".join(bits)

    def river_for(self, s):
        """The river a town is named for, if any; otherwise the nearest."""
        if s.get("named_from"):
            for sysm, rec in zip(self.sv.rivers, self.sv.river_names):
                if rec is s["named_from"]:
                    return sysm, rec
        return self.nearest_river(s)

    def nearest_river(self, s):
        best, bd = None, 1e18
        for sysm, rec in zip(self.sv.rivers, self.sv.river_names):
            for (y, x) in sysm["cells"][::3]:
                d = (y - s["y"]) ** 2 + (x - s["x"]) ** 2
                if d < bd:
                    bd, best = d, (sysm, rec)
        if best and bd < 90:
            return best
        return None

    def neighbours(self, i, k=2):
        D = self.sv.D
        order = np.argsort(D[i])
        out = []
        for j in order:
            if j != i and np.isfinite(D[i, j]) and len(out) < k:
                out.append(int(j))
        return out

    # -- sections -----------------------------------------------------
    def front_matter(self):
        sv, w = self.sv, self.w
        s = sv.summary()
        peak = s["highest"]
        lines = []
        A = lines.append
        A(f"# {sv.title}")
        A("")
        A(f"*{sv.country['gloss']}* — a survey of the country, its waters, "
          f"and the names its three tongues have given them.")
        A("")
        A("---")
        A("")
        A("## The country")
        A("")
        A(f"{sv.title} occupies {s['area_km2']:,} square kilometres between "
          f"{w.lat[w.land].max():.0f}° and {w.lat[w.land].min():.0f}° north. "
          f"A single range runs the length of it from the south-west to the "
          f"north-east, and a second, lower, crosses the north; between them "
          f"lies {sv.seas[0]['name'] if sv.seas else 'the inland water'}, "
          f"enclosed on every side.")
        A("")
        A(f"The prevailing wind is westerly. It arrives wet off the ocean and "
          f"is wrung out on the western slopes, so the west coast carries "
          f"broadleaf forest while the country behind the range is grass and "
          f"thorn. Rainfall across the surveyed land runs from "
          f"{np.percentile(w.precip[w.land], 2):,.0f} mm in the driest "
          f"basins to {np.percentile(w.precip[w.land], 98):,.0f} mm on the "
          f"windward ridges.")
        A("")
        A(f"The highest ground is **{peak['name']}**, {peak['m']:,.0f} m. "
          f"{s['towns']} settlements were visited, holding some "
          f"{s['population']:,} people between them; "
          f"{s['rivers']} river systems were traced from mouth to source.")
        A("")
        counts = {}
        for k, n in climate.BIOME_NAMES.items():
            c = int((w.biome == k).sum())
            if c:
                counts[n] = c / w.land.sum()
        A("| ground cover | share of the land |")
        A("| --- | ---: |")
        for n, f in sorted(counts.items(), key=lambda kv: -kv[1]):
            A(f"| {n} | {f * 100:.1f}% |")
        A("")
        return lines

    def tongues_section(self):
        sv = self.sv
        lines = []
        A = lines.append
        A("---")
        A("")
        A("## The three tongues")
        A("")
        A("Every name in this gazetteer is a compound of ordinary words, and "
          "every compound describes the place it is attached to. A town at a "
          "river's mouth is called *mouth-of-that-river*; a farm on wet ground "
          "is called *reed-field*. The names are therefore readable, and the "
          "reading is given in each entry.")
        A("")
        A("What differs from place to place is how far the words have worn "
          "down. Each tongue has a hearth. Sound changes begin there and "
          "travel outward at the speed of ordinary traffic, which is to say "
          "they travel fast along a river and slowly over a pass. A town four "
          "days' walk from the hearth has taken up most of the changes; a "
          "valley behind the range has taken up only the oldest, and keeps "
          "forms the hearth abandoned generations ago. **The isoglosses on "
          "the map are drawn where the changes stopped, and they stop at the "
          "mountains.**")
        A("")
        for i, tg in enumerate(sv.namer.tongues):
            reg = sv.regions[i]
            hy, hx = tg.hearth
            home = min(sv.sites, key=lambda s: (s["y"] - hy) ** 2 + (s["x"] - hx) ** 2)
            n_here = sum(1 for s in sv.sites if s["tongue_idx"] == i)
            A(f"### {tg.name}")
            A("")
            A(f"Hearth at **{home['name']}** ({_coord(self.w, hy, hx, self.x0)}). "
              f"{n_here} of the surveyed settlements bear {tg.name} names. "
              f"Its country is called *{reg['name']}*, '{reg['gloss']}'.")
            A("")
            A(f"Compounds are **{'head-final' if tg.head_final else 'head-initial'}** "
              f"— the generic element stands "
              f"{'last' if tg.head_final else 'first'}, which is why so many "
              f"{tg.name} names "
              f"{'end' if tg.head_final else 'begin'} alike. "
              f"Linking vowel *-{tg.linker}-*. "
              f"{len(tg.laws)} sound changes are recorded, in this order:")
            A("")
            A("| # | change | rule |")
            A("| ---: | --- | --- |")
            for k, (nm, desc, pat, rep) in enumerate(tg.laws, 1):
                A(f"| {k} | {nm} | {desc} |")
            A("")
            # A worked example: the same root at four distances from the hearth.
            root = ["stone", "ford"]
            proto = tg.compound(root)
            A(f"The same compound *{proto}* ('{tg.gloss(root)}') as it is said "
              f"at increasing distance from the hearth:")
            A("")
            A("| distance from hearth | changes taken up | form |")
            A("| --- | ---: | --- |")
            for frac, label in [(0.0, "at the hearth"), (0.35, "a few days out"),
                                (0.7, "the far valleys"), (1.0, "beyond the range")]:
                k = tg.n_laws_at(frac)
                form = tg.name_for(root, frac)
                A(f"| {label} | {k} of {len(tg.laws)} | **{form}** |")
            A("")
        return lines

    def settlements_section(self):
        sv = self.sv
        lines = []
        A = lines.append
        A("---")
        A("")
        A("## Gazetteer of settlements")
        A("")
        A("*Listed by size. Longitude is measured from the meridian of "
          f"{self.cap['name']}.*")
        A("")
        for i, s in enumerate(sv.sites):
            rank = "the capital" if i == 0 else f"no. {i + 1} by size"
            A(f"### {s['name']}")
            A("")
            A(f"**{s['tongue']}** · {rank} · pop. {s['pop']:,} · "
              f"{_coord(self.w, s['y'], s['x'], self.x0)}")
            A("")
            why = s["why"][0].upper() + s["why"][1:]
            A(f"*Setting.* {self.site_setting(s)}. {why}.")
            near = self.river_for(s)
            if near:
                sysm, rec = near
                A(f"The {rec['name']} runs by; it is {sysm['length_km']:,.0f} km "
                  f"from its source and reaches the sea "
                  f"{_bearing(sysm['mouth'][0] - s['y'], sysm['mouth'][1] - s['x'])} "
                  f"of the town.")
            nb = self.neighbours(i)
            if nb:
                parts = []
                for j in nb:
                    o = sv.sites[j]
                    parts.append(f"{o['name']} "
                                 f"({_bearing(o['y'] - s['y'], o['x'] - s['x'])})")
                A(f"Roads run to {' and '.join(parts)}.")
            A("")
            tg = s["tongue_obj"]
            deriv = _derivation(s, tg)
            line = f"*Name.* {s['tongue']} *{s['proto']}*, '{s['gloss']}'."
            if s.get("named_from"):
                r = s["named_from"]
                line += (f" The first element is taken from the **{r['name']}** "
                         f"(*{r['proto']}*, '{r['gloss']}'), whose water it stands on.")
            A(line)
            A("")
            if deriv:
                A(f"*Derivation.* {deriv}")
                A("")
                A(f"By: {_law_notes(s)}.")
            else:
                A("*Derivation.* The compound offered nothing for the changes "
                  "to act on, and stands in its old shape.")
            near_pct = int(round((1 - min(s["frac"], 1.0)) * 100))
            A("")
            A(f"Reckoned by walking effort, the town stands {near_pct}% of the "
              f"way from the rim of the {s['tongue']} country to its hearth. "
              f"{s['k_reached']} of the {s['n_laws']} recorded changes had "
              f"travelled this far; {len(s['laws'])} of those found anything "
              f"in this name to work on.")
            A("")
        return lines

    def waters_section(self):
        sv = self.sv
        lines = []
        A = lines.append
        A("---")
        A("")
        A("## Rivers")
        A("")
        A("*River names are the oldest layer of any toponymy. They resist "
          "change longer than the names of towns, and several here preserve "
          "forms no living settlement retains.*")
        A("")
        A("| river | tongue | meaning | length | traced from |")
        A("| --- | --- | --- | ---: | --- |")
        for sysm, rec in zip(sv.rivers, sv.river_names):
            src = sysm["cells"][-1]
            A(f"| **{rec['name']}** | {rec['tongue']} | "
              f"*{rec['proto']}*, '{rec['gloss']}' | "
              f"{sysm['length_km']:,.0f} km | "
              f"{self.w.z[src] * METRES_PER_UNIT:,.0f} m |")
        A("")
        if sv.seas:
            A("### Enclosed waters")
            A("")
            for q in sv.seas:
                A(f"**{q['name']}** — {q['tongue']} *{q['proto']}*, "
                  f"'{q['gloss']}'. An enclosed sea in the centre of the "
                  f"country, without an outlet to the ocean.")
                A("")
        A("## Summits")
        A("")
        A("| summit | tongue | meaning | height |")
        A("| --- | --- | --- | ---: |")
        for p in sv.peaks:
            A(f"| **{p['name']}** | {p['tongue']} | *{p['proto']}*, "
              f"'{p['gloss']}' | {p['m']:,.0f} m |")
        A("")
        return lines

    def colophon(self):
        sv = self.sv
        lines = ["---", "",
                 "## How this was made", "",
                 "The ground came first. A rough uplift field was subjected to "
                 "repeated rounds of stream-power incision and hillslope "
                 "diffusion until the drainage network organised itself; the "
                 "valleys are where the water actually cut them.",
                 "",
                 "Moisture was then advected across the finished terrain from "
                 "the west, gaining water over sea and losing it on windward "
                 "slopes, which produced the rainfall field. Vegetation "
                 "follows from rainfall and temperature.",
                 "",
                 "Settlements were sited by scoring every cell on fresh water, "
                 "flat arable ground and shelter, then taking the best "
                 "remaining spot repeatedly. Roads are least-effort walking "
                 "paths over the real slope.",
                 "",
                 "The names came last, and only from what was already there. "
                 "Each is a compound of words true of its site, aged by the "
                 "sound changes that had reached that far — where "
                 "*far* is measured in walking effort, not in kilometres. "
                 "Nothing about the languages was placed by hand except the "
                 "phoneme inventories and the catalogue of possible changes.",
                 "",
                 f"Seed {sv.w.seed}. Every figure above is measured from the "
                 f"model, not asserted.", ""]
        return lines

    def write(self, path):
        lines = (self.front_matter() + self.tongues_section()
                 + self.settlements_section() + self.waters_section()
                 + self.colophon())
        text = "\n".join(lines)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return text
