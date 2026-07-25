"""
head.py — the substrate.

A head built from implicit surfaces and lit, producing two fields: how bright
each point is, and whether there is anything there at all. Nothing here is
drawn; it is all solved for. The surface is the set of points where a
function changes sign, found by walking toward it in steps no longer than the
distance to it. Normals come from finite differences. Occlusion is sampled.

The eyes are closed. That wasn't a compositional decision.

This field is never shown on its own. It is only ever the thing the words
arrange themselves into.
"""

import numpy as np
from PIL import Image

F = np.float32

# ---------------------------------------------------------------- primitives

def ell(x, y, z, c, r):
    """Signed distance to an ellipsoid (IQ's approximation). Accurate near the
    surface, unreliable far from it — and since everything here gets smoothly
    blended, a primitive that lies at a distance smears its lie across the
    whole face. So: nothing below is allowed to be much more than 3:1. Anything
    thinner than that is a capsule instead."""
    qx = (x - c[0]) * (1.0 / r[0])
    qy = (y - c[1]) * (1.0 / r[1])
    qz = (z - c[2]) * (1.0 / r[2])
    k0 = np.sqrt(qx * qx + qy * qy + qz * qz)
    a = qx * (1.0 / r[0]); b = qy * (1.0 / r[1]); c_ = qz * (1.0 / r[2])
    k1 = np.sqrt(a * a + b * b + c_ * c_)
    return k0 * (k0 - 1.0) / np.maximum(k1, F(1e-9))


def cap(x, y, z, a, b, r):
    """Capsule: exact distance to a segment, thickened. Used for the incisions —
    the seam of a closed eye, the line between the lips — because a very thin
    ellipsoid is a very bad description of a line."""
    bx, by, bz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
    bb = bx * bx + by * by + bz * bz
    px, py, pz = x - a[0], y - a[1], z - a[2]
    h = np.clip((px * bx + py * by + pz * bz) / bb, 0.0, 1.0)
    dx = px - bx * h; dy = py - by * h; dz = pz - bz * h
    return np.sqrt(dx * dx + dy * dy + dz * dz) - F(r)


def smin(a, b, k):
    """Polynomial smooth minimum — union with a fillet."""
    h = np.clip(0.5 + (0.5 / k) * (b - a), 0.0, 1.0)
    return b + (a - b) * h - k * h * (1.0 - h)


def ssub(a, b, k):
    """Smooth subtraction: a minus b."""
    h = np.clip(0.5 - (0.5 / k) * (b + a), 0.0, 1.0)
    return a + (-b - a) * h + k * h * (1.0 - h)


# ---------------------------------------------------------------- the anatomy
#
# y up, x right, z toward the viewer. Crown near y=+1, chin near y=-1, the
# closed eyes on the midline. Every line below is a decision about a face
# that does not exist and never did.

def pell(x, y, z, c, r):
    """A feature and its reflection. Built from a real left and a real right
    rather than from |x|, because folding the world in half leaves a seam
    down the middle of the face."""
    return np.minimum(ell(x, y, z, c, r), ell(x, y, z, (-c[0], c[1], c[2]), r))


def pcap(x, y, z, a, b, r, k=None):
    l = cap(x, y, z, a, b, r)
    m = cap(x, y, z, (-a[0], a[1], a[2]), (-b[0], b[1], b[2]), r)
    return np.minimum(l, m) if k is None else smin(l, m, F(k))


def sdf(x, y, z):

    # The ovoid. One egg, tapering downward. Everything after this is a
    # whisper laid on its front, and every depth below was chosen by working
    # out where this surface actually is — not by guessing.
    d = ell(x, y, z, (0, 0.34, -0.04), (0.655, 0.660, 0.780))
    d = smin(d, ell(x, y, z, (0, -0.42, 0.06), (0.605, 0.600, 0.680)), F(0.42))
    d = smin(d, ell(x, y, z, (0, -0.870, 0.300), (0.215, 0.180, 0.250)), F(0.28))
    # jaw corners, to hang the lower face on
    d = smin(d, pell(x, y, z, (0.365, -0.640, 0.140), (0.150, 0.155, 0.235)), F(0.22))

    # brow: one soft ridge, sloping back at the temples so it stays on the head
    d = smin(d, pcap(x, y, z, (0.055, 0.185, 0.660), (0.335, 0.170, 0.545), 0.092, k=0.045), F(0.13))
    # cheekbone: three hundredths proud of the surface. Barely there
    d = smin(d, pell(x, y, z, (0.395, -0.14, 0.22), (0.220, 0.160, 0.240)), F(0.16))

    # a shallow crater, a lid filling it, and the seam where the lid shuts.
    # The crater has to break the surface to leave a mark on it — a hollow
    # that never reaches the skin is just a hollow.
    d = ssub(d, pell(x, y, z, (0.255, 0.020, 0.655), (0.300, 0.185, 0.138)), F(0.10))
    d = smin(d, pell(x, y, z, (0.250, 0.005, 0.380), (0.185, 0.145, 0.150)), F(0.05))
    d = ssub(d, pcap(x, y, z, (0.100, 0.030, 0.540), (0.390, 0.040, 0.505), 0.016), F(0.022))

    # nose — the one thing allowed to leave the face
    d = smin(d, cap(x, y, z, (0, 0.140, 0.665), (0, -0.255, 0.775), 0.062), F(0.10))
    d = smin(d, ell(x, y, z, (0, -0.300, 0.775), (0.095, 0.090, 0.120)), F(0.075))
    d = smin(d, pell(x, y, z, (0.120, -0.320, 0.700), (0.072, 0.060, 0.098)), F(0.050))

    # mouth: two soft tubes and the line between them
    d = smin(d, pcap(x, y, z, (0.020, -0.560, 0.670), (0.200, -0.578, 0.590), 0.058, k=0.03), F(0.075))
    d = smin(d, pcap(x, y, z, (0.020, -0.656, 0.665), (0.185, -0.646, 0.590), 0.066, k=0.03), F(0.075))
    d = ssub(d, pcap(x, y, z, (0.0, -0.602, 0.726), (0.205, -0.620, 0.655), 0.018, k=0.02), F(0.028))

    # ears, small, and actually on the side of the head this time
    d = smin(d, pell(x, y, z, (0.480, -0.08, -0.180), (0.050, 0.160, 0.130)), F(0.12))

    # neck, and shoulders running off the bottom of the frame
    d = smin(d, ell(x, y, z, (0, -1.58, -0.12), (0.340, 0.620, 0.360)), F(0.30))
    d = smin(d, ell(x, y, z, (0, -2.42, -0.22), (1.620, 0.640, 0.620)), F(0.46))
    return d


# ---------------------------------------------------------------- solving it

Z_NEAR, T_MAX = F(1.45), F(2.90)


def _yaw(u, v, w, cs):
    """View coordinates (u right, v up, w toward viewer) into world."""
    c, s = cs
    return c * u + s * w, v, -s * u + c * w


def trace(u, v, cs, steps=120):
    """Sphere-trace toward the front surface: never step further than the
    distance to it, so nothing thin gets stepped over."""
    inf = F(1e9)
    t = np.zeros_like(u)
    t_out = np.zeros_like(u)          # last t known to be outside
    t_in = np.full_like(u, inf)       # first t known to be inside

    for _ in range(steps):
        d = sdf(*_yaw(u, v, Z_NEAR - t, cs))
        searching = t_in >= inf
        inside = d <= 0.0
        t_out = np.where(searching & ~inside, t, t_out)
        t_in = np.where(searching & inside, t, t_in)
        step = np.clip(d * F(0.72), F(0.0012), F(0.05))
        t = t + np.where(searching & (t < T_MAX), step, F(0.0))

    hit = (t_in < inf)
    lo, hi = t_out.copy(), np.where(hit, t_in, t_out)   # lo outside, hi inside
    for _ in range(14):
        mid = 0.5 * (lo + hi)
        ins = sdf(*_yaw(u, v, Z_NEAR - mid, cs)) <= 0.0
        hi = np.where(ins, mid, hi)
        lo = np.where(ins, lo, mid)
    return Z_NEAR - 0.5 * (lo + hi), hit


def shade(u, v, w, cs, hit):
    x, y, z = _yaw(u, v, w, cs)
    e = F(0.0022)
    gx = sdf(x + e, y, z) - sdf(x - e, y, z)
    gy = sdf(x, y + e, z) - sdf(x, y - e, z)
    gz = sdf(x, y, z + e) - sdf(x, y, z - e)
    ln = np.maximum(np.sqrt(gx * gx + gy * gy + gz * gz), F(1e-9))
    gx /= ln; gy /= ln; gz /= ln
    c, s = cs
    nx, ny, nz = c * gx - s * gz, gy, s * gx + c * gz   # normal, back into view space

    # ambient occlusion — this is what makes a socket read as a socket.
    # Stepped along the world normal; the view has nothing to do with it.
    ao = np.zeros_like(x); wsum = F(0.0)
    for i in range(1, 6):
        h = F(0.34) * i / 5
        wt = F(1.0) / (2 ** i)
        ao += wt * np.clip((h - sdf(x + gx * h, y + gy * h, z + gz * h)) / h, 0.0, 1.0)
        wsum += wt
    AO = np.clip(1.0 - ao / wsum, 0.0, 1.0)

    def unit(a):
        a = np.array(a, F); return a / np.linalg.norm(a)
    key, fill, bounce = unit((-0.74, 0.44, 0.42)), unit((0.86, -0.10, 0.50)), unit((0.10, -0.90, 0.42))

    kd = np.clip(nx * key[0] + ny * key[1] + nz * key[2], 0.0, 1.0)
    fd = np.clip(nx * fill[0] + ny * fill[1] + nz * fill[2], 0.0, 1.0)
    bd = np.clip(nx * bounce[0] + ny * bounce[1] + nz * bounce[2], 0.0, 1.0)

    # A hard raking key, and occlusion kept as a modifier rather than the main
    # event. I tried it the other way — soft fill, occlusion doing the work —
    # on the theory that a flat lit side was wasting half the face and burying
    # the sockets. It was worse: without the strong light the head stops having
    # a light side and a dark side and becomes an even grey mass, and once the
    # volume goes, no amount of crease contrast puts it back. The drama is
    # load-bearing.
    L = 0.030 + 0.94 * kd ** F(0.86) + 0.150 * fd ** F(1.4) + 0.090 * bd ** F(2.0)
    L *= (0.34 + 0.66 * AO)

    # The head has no outline: where the surface turns away, it stops existing.
    # This is coverage, not tone — kept separate, because the words need to
    # know the difference between a place that is dark and a place that is
    # not there.
    facing = np.clip(nz / F(0.52), 0.0, 1.0) ** F(0.75)
    depth = np.clip((w + F(1.10)) / F(1.70), 0.0, 1.0)
    bottom = np.clip((v + F(2.45)) / F(0.95), 0.0, 1.0)
    A = np.where(hit, facing * (0.30 + 0.70 * depth) * bottom, 0.0)

    return np.clip(L, 0.0, 1.0), np.clip(A, 0.0, 1.0)


def render(W=1000, H=1360, ss=2, yaw=0.0, extent=(1.06, 1.442), center=(0.0, -0.05)):
    """Rendered at ss× and box-filtered down; the tonal field wants to be smooth."""
    Wf, Hf = W * ss, H * ss
    au = np.linspace(-extent[0], extent[0], Wf, dtype=F) + F(center[0])
    av = np.linspace(extent[1], -extent[1], Hf, dtype=F) + F(center[1])
    U, V = np.meshgrid(au, av)

    th = np.radians(yaw)
    cs = (F(np.cos(th)), F(np.sin(th)))

    cand = ((U / 1.05) ** 2 + ((V - 0.05) / 1.35) ** 2 < 1.0) | \
           ((np.abs(V + 2.05) < 1.25) & (np.abs(U) < 2.2))
    u, v = np.ascontiguousarray(U[cand]), np.ascontiguousarray(V[cand])

    w, hit = trace(u, v, cs)
    lum, alpha = shade(u, v, w, cs, hit)

    out = []
    for vals in (lum * alpha, alpha):        # premultiplied, so the box filter is honest
        img = np.zeros((Hf, Wf), F)
        img[cand] = vals
        out.append(img.reshape(H, ss, W, ss).mean(axis=(1, 3)))
    L, A = out
    return np.where(A > 1e-4, L / np.maximum(A, 1e-4), 0.0), A


def contact_sheet(scale=0.34, yaws=(0, 25, 55, 90)):
    """Four views in a row. You cannot fix a profile you have never looked at."""
    W, H = int(1000 * scale), int(1360 * scale)
    tiles = [render(W, H, 1, yaw=a)[0] for a in yaws]
    sheet = np.concatenate(tiles, axis=1)
    Image.fromarray((sheet ** (1 / 1.85) * 255).astype(np.uint8)).save("_views.png")
    return sheet


if __name__ == "__main__":
    import sys, time
    t0 = time.time()
    if len(sys.argv) > 1 and sys.argv[1] == "views":
        contact_sheet()
        print(f"_views.png  {time.time()-t0:.1f}s")
    else:
        s = float(sys.argv[1]) if len(sys.argv) > 1 else 1.0
        ss = int(sys.argv[2]) if len(sys.argv) > 2 else 2
        W, H = int(1000 * s), int(1360 * s)
        L, A = render(W, H, ss)
        np.save("substrate.npy", np.stack([L, A]))
        # tone is what the words will actually be given: ink in the shadows,
        # bare paper in the light, nothing at all off the head
        tone = A * (1.0 - L)
        Image.fromarray(((1.0 - tone) * 255).astype(np.uint8)).save("_substrate.png")
        print(f"{W}x{H} ss{ss}  {time.time()-t0:.1f}s  "
              f"cover={(A>0.02).mean():.3f}  tone={tone.max():.2f}/{tone[A>0.02].mean():.2f}")
