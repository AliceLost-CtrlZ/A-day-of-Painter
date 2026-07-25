"""Where people live, and how they get to each other.

Sites are scored on the things that actually decide a town -- fresh water,
flat arable ground, a harbour or a ford -- and then routes are cut between
them by least-effort walking over the real terrain. The travel-cost matrix
this produces is also what the languages drift along.
"""

import heapq
from collections import namedtuple

import numpy as np

from . import climate

Site = namedtuple("Site", "id y x score pop kind river harbour")

IMPASSABLE = 1e9


def _log1p(a):
    return np.log1p(np.maximum(a, 0))


def score_sites(w, small_island=None):
    """A suitability field over land. Higher is a better place to live."""
    land = w.land
    q = _log1p(w.discharge)
    q = q / (q[land].max() + 1e-9)

    arable = np.isin(w.biome, [climate.FOREST, climate.WOODLAND, climate.STEPPE]) & land
    flat = np.exp(-(w.slope / 0.020) ** 2)

    # Fresh water within a short walk matters more than being on the bank.
    near_water = np.exp(-w.water_dist / 2.2)
    harbour = (w.coast_dist < 1.9) & land & (w.slope < 0.035)

    # A confluence or a big river at a low-relief spot: a ford, then a market.
    river_town = q ** 1.05 * flat

    s = (1.15 * river_town
         + 0.35 * near_water
         + 1.45 * arable * flat
         + 0.35 * harbour * flat
         + 0.20 * np.exp(-w.z / 0.25))

    s = np.where(land, s, -1.0)
    s = np.where(w.lake, -1.0, s)
    s = np.where(np.isin(w.biome, [climate.ICE, climate.ALPINE]), -1.0, s)
    s = np.where(w.biome == climate.DESERT, s * 0.25, s)
    s = np.where(w.biome == climate.MARSH, s * 0.5, s)
    # The very steepest ground is simply not built on.
    s = np.where(w.slope > 0.10, -1.0, s)
    # Small islands support hamlets, not cities: they have no hinterland.
    if small_island is not None:
        s = np.where(small_island, s * 0.28, s)
    return s, harbour


def place(w, n=26, min_sep=14, rng=None, small_island=None):
    """Greedy siting: take the best remaining spot, then forbid its hinterland."""
    rng = rng or w.rng
    s, harbour = score_sites(w, small_island)
    s = s + rng.normal(0, 0.015, s.shape)   # break ties; no two runs identical
    h, wd = s.shape
    taken = np.zeros_like(s, bool)
    yy, xx = np.mgrid[0:h, 0:wd]

    sites = []
    work = s.copy()
    for i in range(n):
        idx = int(np.argmax(work))
        y, x = divmod(idx, wd)
        if work[y, x] <= 0:
            break
        # Bigger places claim a bigger hinterland.
        sep = min_sep * (1.0 + 0.9 * np.exp(-i / 5.0))
        d2 = (yy - y) ** 2 + (xx - x) ** 2
        work = np.where(d2 < sep ** 2, -1.0, work)
        taken[y, x] = True

        river = float(w.discharge[y, x])
        sites.append(dict(id=i, y=y, x=x, score=float(s[y, x]),
                          river=river, harbour=bool(harbour[y, x])))

    # Population: rank-size law, tilted by the site's own quality.
    if sites:
        base = np.array([st["score"] for st in sites])
        base = base / base.max()
        for i, st in enumerate(sites):
            rank = i + 1
            pop = 92000 / rank ** 0.92 * (0.45 + 0.75 * base[i])
            st["pop"] = int(round(pop / 100.0) * 100)
    return sites


# --- travel ---------------------------------------------------------------

def _blocks(a, step, pad):
    """Reshape to (H, step, W, step) so a block reduction can be taken."""
    h, w = a.shape
    H, W = -(-h // step), -(-w // step)
    out = np.full((H * step, W * step), pad, a.dtype)
    out[:h, :w] = a
    return out.reshape(H, step, W, step).transpose(0, 2, 1, 3).reshape(H, W, -1)


def travel_cost_grid(w, step=2):
    """Cost of walking one cell, on a coarsened grid. Sea is impassable.

    The coarsening reduces by block rather than by sampling: a shore one cell
    wide, or a neck of land between two bays, must survive it. Sampling every
    other pixel deletes exactly the ground that ports and passes stand on.
    """
    land = _blocks(w.land, step, False).any(axis=2)
    z = _blocks(w.z, step, 0.0).mean(axis=2)
    slope = _blocks(w.slope, step, 0.0).min(axis=2)
    disch = _blocks(w.discharge, step, 0.0).max(axis=2)
    lake = _blocks(w.lake, step, False).all(axis=2)
    bl = _blocks(w.biome, step, -1)
    biome = bl.max(axis=2)

    c = np.full(z.shape, 1.0)
    c += 26.0 * slope                       # climbing is what costs
    c += np.where(biome == climate.FOREST, 0.35, 0.0)
    c += np.where(biome == climate.MARSH, 1.4, 0.0)
    c += np.where(biome == climate.DESERT, 0.8, 0.0)
    c += np.where(biome == climate.TAIGA, 0.3, 0.0)
    # Fording a big river is a real obstacle; small ones are nothing.
    big = _log1p(disch)
    big = big / (big[land].max() + 1e-9) if land.any() else big
    c += 5.0 * np.clip(big - 0.55, 0, None) / 0.45
    c = np.where(land & ~lake, c, IMPASSABLE)
    return c


def dijkstra(cost, src):
    """Least-cost field and parent pointers from one source cell."""
    h, w = cost.shape
    n = h * w
    dist = np.full(n, np.inf)
    par = np.full(n, -1, np.int64)
    cf = cost.ravel()
    sy, sx = src
    s = sy * w + sx
    dist[s] = 0.0
    heap = [(0.0, s)]
    push, pop = heapq.heappush, heapq.heappop
    offs = [(-1, -1, 1.414), (-1, 0, 1.0), (-1, 1, 1.414), (0, -1, 1.0),
            (0, 1, 1.0), (1, -1, 1.414), (1, 0, 1.0), (1, 1, 1.414)]
    while heap:
        d, u = pop(heap)
        if d > dist[u]:
            continue
        uy, ux = divmod(u, w)
        for dy, dx, wt in offs:
            vy, vx = uy + dy, ux + dx
            if 0 <= vy < h and 0 <= vx < w:
                cv = cf[vy * w + vx]
                if cv >= IMPASSABLE:
                    continue
                v = vy * w + vx
                nd = d + wt * 0.5 * (cf[u] + cv)
                if nd < dist[v]:
                    dist[v] = nd
                    par[v] = u
                    push(heap, (nd, v))
    return dist.reshape(h, w), par


def _trace(par, w_cols, target):
    path = []
    cur = target
    while cur >= 0:
        path.append(divmod(cur, w_cols))
        cur = par[cur]
    return path[::-1]


def roads(w, sites, step=2, extra=8):
    """A road network: minimum spanning tree plus a few opportunistic links."""
    cost = travel_cost_grid(w, step)
    h, wc = cost.shape
    pts = []
    for st in sites:
        y, x = st["y"] // step, st["x"] // step
        # Nudge onto passable ground if the coarsening dropped us in the sea.
        if cost[y, x] >= IMPASSABLE:
            found = False
            for r in range(1, 5):
                ys, xs = np.mgrid[max(0, y - r):y + r + 1, max(0, x - r):x + r + 1]
                m = cost[ys, xs] < IMPASSABLE
                if m.any():
                    yy, xx = ys[m], xs[m]
                    k = np.argmin((yy - y) ** 2 + (xx - x) ** 2)
                    y, x = int(yy[k]), int(xx[k])
                    found = True
                    break
            if not found:
                pts.append(None)
                continue
        pts.append((y, x))

    fields = {}
    for i, p in enumerate(pts):
        if p is None:
            continue
        fields[i] = dijkstra(cost, p)

    n = len(sites)
    D = np.full((n, n), np.inf)
    for i, (dist, _) in fields.items():
        for j, p in enumerate(pts):
            if p is not None and i != j:
                D[i, j] = dist[p]

    # Prim's MST over travel cost.
    inn = {next(iter(fields))} if fields else set()
    edges = []
    avail = set(fields) - inn
    while avail:
        best = None
        for a in inn:
            for b in avail:
                if D[a, b] < (best[2] if best else np.inf):
                    best = (a, b, D[a, b])
        if best is None or not np.isfinite(best[2]):
            break
        edges.append((best[0], best[1]))
        inn.add(best[1])
        avail.discard(best[1])

    # Then a handful of shortcuts between places that are close but unlinked.
    have = {tuple(sorted(e)) for e in edges}
    cand = []
    for i in fields:
        for j in fields:
            if i < j and (i, j) not in have and np.isfinite(D[i, j]):
                cand.append((D[i, j], i, j))
    cand.sort()
    for _, i, j in cand[:extra]:
        edges.append((i, j))

    paths = []
    for a, b in edges:
        if a not in fields or pts[b] is None:
            continue
        _, par = fields[a]
        tgt = pts[b][0] * wc + pts[b][1]
        pth = _trace(par, wc, tgt)
        if len(pth) > 1:
            paths.append(dict(a=a, b=b, cells=[(y * step, x * step) for y, x in pth],
                              cost=float(D[a, b])))
    return paths, D, fields, cost
