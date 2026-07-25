"""Terrain generation: fractal uplift shaped by fluvial erosion.

The landscape is not drawn, it is grown. A rough uplift field is subjected to
repeated rounds of stream-power incision and hillslope diffusion until the
drainage network organises itself. Everything downstream in this atlas --
rivers, roads, towns, names -- is read off the result rather than invented.
"""

import heapq

import numpy as np

# 8-neighbour offsets and their planform distances (in cell widths).
NB = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]
NB_DIST = np.array([np.hypot(dy, dx) for dy, dx in NB])


def _fade(t):
    return t * t * t * (t * (t * 6 - 15) + 10)


def _perlin(shape, res, rng):
    """Classic gradient noise on a `res` lattice, sampled at `shape`."""
    h, w = shape
    rh, rw = res
    ang = rng.uniform(0, 2 * np.pi, (rh + 1, rw + 1))
    gy, gx = np.sin(ang), np.cos(ang)

    ys = np.linspace(0, rh, h, endpoint=False)
    xs = np.linspace(0, rw, w, endpoint=False)
    yi, xi = np.floor(ys).astype(int), np.floor(xs).astype(int)
    yf, xf = ys - yi, xs - xi

    yf2, xf2 = yf[:, None], xf[None, :]
    yi2, xi2 = yi[:, None], xi[None, :]

    def dot(dy, dx):
        g_y = gy[yi2 + dy, xi2 + dx]
        g_x = gx[yi2 + dy, xi2 + dx]
        return g_y * (yf2 - dy) + g_x * (xf2 - dx)

    u, v = _fade(xf2), _fade(yf2)
    n00, n10 = dot(0, 0), dot(0, 1)
    n01, n11 = dot(1, 0), dot(1, 1)
    top = n00 + u * (n10 - n00)
    bot = n01 + u * (n11 - n01)
    return top + v * (bot - top)


def fbm(shape, rng, octaves=7, res=(3, 4), lacunarity=2, gain=0.5):
    out = np.zeros(shape)
    amp, total = 1.0, 0.0
    ry, rx = res
    for _ in range(octaves):
        out += amp * _perlin(shape, (ry, rx), rng)
        total += amp
        amp *= gain
        ry, rx = int(ry * lacunarity), int(rx * lacunarity)
    return out / total


def continent(shape, rng, land_fraction=0.46):
    """A base height field whose zero contour is the coast.

    Rather than stamping an island shape, low-frequency noise is offset until
    the requested fraction of the map stands above sea level. The coastline is
    then a contour of a noise field -- bays, capes and offshore islands come
    for free -- with only a soft frame falloff to keep land off the border.
    """
    h, w = shape
    yy, xx = np.mgrid[0:h, 0:w]
    ny, nx = (yy / h - 0.5) * 2, (xx / w - 0.5) * 2

    # Domain warp: displace the sample grid by another noise field so the
    # contour folds back on itself and makes peninsulas.
    base = (0.62 * fbm(shape, rng, octaves=6, res=(2, 3))
            + 0.30 * fbm(shape, rng, octaves=7, res=(4, 6))
            + 0.16 * fbm(shape, rng, octaves=4, res=(7, 10)))

    r = np.sqrt(((nx + 0.05) / 1.06) ** 2 + ((ny - 0.03) / 0.98) ** 2)
    # No radial bias in the interior at all -- only a penalty near the frame,
    # so the outline (and any inland sea) is the noise's business, not mine.
    frame = -1.30 * np.clip(r - 0.66, 0, None) ** 1.5
    field = base + frame
    return field - np.quantile(field, 1 - land_fraction)


def _priority_flood(z, sea):
    """Fill closed basins so every land cell has a path to the sea.

    Barnes et al. priority-flood with an epsilon gradient, which leaves lakes
    as near-flat surfaces that still route water outward.
    """
    h, w = z.shape
    filled = z.copy()
    seen = np.zeros((h, w), bool)
    heap = []
    eps = 1e-5

    edge = np.zeros((h, w), bool)
    edge[0, :] = edge[-1, :] = True
    edge[:, 0] = edge[:, -1] = True
    starts = np.argwhere((z <= sea) | edge)
    for y, x in starts:
        seen[y, x] = True
        heapq.heappush(heap, (filled[y, x], int(y), int(x)))

    push, pop = heapq.heappush, heapq.heappop
    while heap:
        zc, y, x = pop(heap)
        for dy, dx in NB:
            ny, nx = y + dy, x + dx
            if 0 <= ny < h and 0 <= nx < w and not seen[ny, nx]:
                seen[ny, nx] = True
                nz = filled[ny, nx]
                if nz <= zc:
                    nz = zc + eps
                    filled[ny, nx] = nz
                push(heap, (nz, ny, nx))
    return filled


def _receivers(z, sea):
    """D8 steepest-descent receiver for every cell, plus a processing order."""
    h, w = z.shape
    zp = np.pad(z, 1, mode="edge")
    best_slope = np.zeros((h, w))
    rec_y = np.tile(np.arange(h)[:, None], (1, w))
    rec_x = np.tile(np.arange(w)[None, :], (h, 1))

    for k, (dy, dx) in enumerate(NB):
        nz = zp[1 + dy:1 + dy + h, 1 + dx:1 + dx + w]
        slope = (z - nz) / NB_DIST[k]
        better = slope > best_slope
        best_slope = np.where(better, slope, best_slope)
        ny = np.clip(rec_y + dy, 0, h - 1)
        nx = np.clip(rec_x + dx, 0, w - 1)
        rec_y = np.where(better, ny, rec_y)
        rec_x = np.where(better, nx, rec_x)

    flat = rec_y * w + rec_x
    # Ocean cells and the frame drain to themselves: they are outlets.
    sink = (z <= sea)
    sink[0, :] = sink[-1, :] = True
    sink[:, 0] = sink[:, -1] = True
    idx = np.arange(h * w).reshape(h, w)
    flat = np.where(sink, idx, flat)
    return flat.ravel(), best_slope


def flow_accumulate(z, sea, weight=None):
    """Drainage area (or accumulated rainfall) per cell, plus receiver graph."""
    h, w = z.shape
    filled = _priority_flood(z, sea)
    rec, slope = _receivers(filled, sea)
    order = np.argsort(filled.ravel())[::-1]  # highest first == topological

    acc = np.ones(h * w) if weight is None else weight.ravel().astype(float).copy()
    for i in order:
        r = rec[i]
        if r != i:
            acc[r] += acc[i]
    return acc.reshape(h, w), rec, filled, slope


def _diffuse(z, land, kd):
    lap = (
        np.roll(z, 1, 0) + np.roll(z, -1, 0) + np.roll(z, 1, 1) + np.roll(z, -1, 1)
        - 4 * z
    )
    return z + kd * lap * land


def _orogen(shape, rng, y0, tilt, width, strength):
    """One mountain belt: a tilted band whose vigour varies along strike."""
    h, w = shape
    yy, xx = np.mgrid[0:h, 0:w]
    u = xx / w - 0.5
    axis = (yy / h - y0) - tilt * u
    # Wander the axis so the range is not a ruled line.
    wander = 0.055 * fbm(shape, rng, octaves=3, res=(1, 4))
    band = np.exp(-((axis + wander) ** 2) / (2 * width ** 2))
    # Along-strike segmentation: real ranges rise and fall into separate massifs.
    seg = 0.55 + 0.75 * np.clip(fbm(shape, rng, octaves=3, res=(1, 5)) * 2.4 + 0.5, 0, 1)
    return strength * band * seg


def build(shape=(420, 620), seed=7, steps=48, verbose=True):
    """Grow a landscape. Returns elevation (sea level == 0) and the land mask."""
    rng = np.random.default_rng(seed)
    h, w = shape
    sea = 0.0

    base = continent(shape, rng)
    land0 = base > 0
    ridged = (1 - np.abs(fbm(shape, rng, octaves=7, res=(5, 7)))) ** 1.6
    rough = fbm(shape, rng, octaves=8, res=(6, 9))

    # Two collision belts at an angle to each other, plus a broad low swell.
    belt = (_orogen(shape, rng, 0.56, 0.34, 0.070, 1.00)
            + _orogen(shape, rng, 0.27, -0.14, 0.045, 0.72)
            + _orogen(shape, rng, 0.80, 0.05, 0.038, 0.40))
    swell = np.clip(0.55 + 1.4 * fbm(shape, rng, octaves=4, res=(3, 4)), 0, None)

    coast_taper = np.clip(base * 9.0, 0, 1)  # no cliffs of uplift at the shore
    uplift = land0 * coast_taper * (0.13 * swell + 1.75 * belt * (0.35 + ridged))

    z = np.where(land0, 0.02 + 0.55 * belt * ridged + 0.22 * np.clip(rough, 0, None), 0.0)
    ocean = ~land0

    dt = 1.0
    k_stream, m = 0.075, 0.5
    for step in range(steps):
        z = z + uplift * dt * 0.050
        acc, rec, filled, _ = flow_accumulate(z, sea)
        area = acc.ravel()
        znew = filled.ravel().copy()
        order = np.argsort(filled.ravel())  # lowest first: receivers settled first
        active = (filled.ravel() > sea) & (~ocean.ravel())
        kfac = k_stream * dt * np.power(area, m)
        for i in order:
            r = rec[i]
            if r == i or not active[i]:
                continue
            f = kfac[i]
            znew[i] = (znew[i] + f * znew[r]) / (1.0 + f)
        z = np.maximum(znew.reshape(h, w), 0.0)
        z = _diffuse(z, land0, 0.045)
        z[ocean] = 0.0
        z = np.maximum(z, 0.0)
        if verbose and (step + 1) % 12 == 0:
            print(f"  erosion step {step + 1}/{steps}  max relief {z.max():.3f}")

    land = land0 & (z > 0)
    z[~land] = 0.0
    return z, land
