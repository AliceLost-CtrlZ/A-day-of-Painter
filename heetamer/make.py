"""Build the atlas.

    python make.py [seed] [--quick]

Produces, in out/:
    <name>-map.png        the survey plate
    <name>-isoglosses.png the linguistic plate
    <name>.md             the gazetteer
"""

import sys
import time

from atlas.dialects import DialectPlate
from atlas.gazetteer import Gazetteer
from atlas.render import MapRenderer
from atlas.survey import Survey


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    quick = "--quick" in sys.argv
    seed = int(args[0]) if args else 17

    shape, steps, n = ((240, 354), 24, 22) if quick else ((420, 620), 44, 32)
    t0 = time.time()
    sv = Survey(seed=seed, shape=shape, steps=steps, n_sites=n, verbose=True)

    slug = sv.title.lower()
    print("· drawing the survey plate")
    MapRenderer(sv, scale=2, supersample=2).render(f"out/{slug}-map.png")
    print("· drawing the linguistic plate")
    DialectPlate(sv, scale=2, supersample=2).render(f"out/{slug}-isoglosses.png")
    print("· writing the gazetteer")
    text = Gazetteer(sv).write(f"out/{slug}.md")

    s = sv.summary()
    print()
    print(f"  {sv.title} — {sv.country['gloss']}")
    print(f"  {s['area_km2']:,} sq km · {s['population']:,} people · "
          f"{s['towns']} towns · {s['rivers']} rivers")
    print(f"  highest: {s['highest']['name']} at {s['highest']['m']:,.0f} m")
    print(f"  gazetteer: {len(text.split()):,} words")
    print(f"  built in {time.time() - t0:.0f}s (seed {seed})")


if __name__ == "__main__":
    main()
