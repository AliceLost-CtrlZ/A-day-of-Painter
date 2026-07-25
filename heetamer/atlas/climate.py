"""Climate: moisture carried inland by a prevailing wind, and what grows.

Rain is not painted on. A band of moist air is advected across the grid from
the west; it gains water over sea and loses it where the ground rises. The dry
country east of the mountains is therefore a consequence of the mountains, and
moves if they move.
"""

import numpy as np

# Biome codes
ICE, ALPINE, TUNDRA, TAIGA, FOREST, WOODLAND, STEPPE, SCRUB, DESERT, MARSH = range(10)

BIOME_NAMES = {
    ICE: "permanent snow", ALPINE: "alpine barrens", TUNDRA: "cold heath",
    TAIGA: "black-pine forest", FOREST: "mixed broadleaf forest",
    WOODLAND: "open oak woodland", STEPPE: "grass steppe",
    SCRUB: "thorn scrub", DESERT: "stone desert", MARSH: "reed marsh",
}


def temperature(shape, z, lat_north=55.0, lat_south=37.0, metres_per_unit=700.0):
    """Mean annual degrees C: a latitude gradient with a 6.4 C/km lapse."""
    h, w = shape
    lat = np.linspace(lat_north, lat_south, h)[:, None] * np.ones((1, w))
    t = 34.0 - 0.47 * lat                        # 8.2 C at 55N, 16.6 C at 37N
    t -= 6.4e-3 * metres_per_unit * z            # elevation lapse
    return t, lat


def rainfall(z, land, temp, drift=0.30, evap=0.16, oro=1.35, base=0.020,
             recycle=0.50, mm_at_p90=1400.0):
    """Advect moisture eastward, raining it out on windward slopes.

    Returned in mm/year, calibrated so the 90th percentile of land rainfall
    sits at a wet-temperate value.
    """
    h, w = z.shape
    rows = np.arange(h)
    cap = np.clip(0.45 + 0.055 * temp, 0.15, 2.2)  # warm air holds more water

    m = cap[:, 0].copy()
    precip = np.zeros((h, w))
    carry = 0.0
    for x in range(w):
        # WSW wind: the parcel slides north-to-south a little as it travels.
        carry += drift
        if carry >= 1.0:
            shift = int(carry)
            carry -= shift
            m = np.roll(m, shift)
            m[:shift] = m[shift] if shift else m[0]

        col_land = land[:, x]
        col_z = z[:, x]
        # Sea surface feeds the parcel.
        m = np.where(col_land, m, m + evap * np.maximum(cap[:, x] - m, 0))

        if x > 0:
            rise = np.maximum(col_z - z[:, x - 1], 0.0)
        else:
            rise = np.zeros(h)

        # Rain-out: a steady drizzle plus a strong orographic term.
        frac = np.clip(base + oro * rise + 0.35 * np.clip(m / cap[:, x] - 0.9, 0, None), 0, 0.85)
        p = np.where(col_land, m * frac, m * 0.012)
        m = m - p
        # Continental recycling: much of what falls on land is transpired
        # back into the same air mass, so the interior is not a dead shadow.
        m = m + np.where(col_land, recycle * p, 0.0)
        # Descending air re-absorbs: the lee is dry twice over.
        fall = np.maximum(z[:, x - 1] - col_z, 0.0) if x > 0 else np.zeros(h)
        m = m + np.where(col_land, np.minimum(3.0 * fall * m, m * 0.5), 0.0)
        m = np.minimum(m, cap[:, x])
        precip[:, x] = p

    # A little lateral mixing: weather fronts are not knife-edged.
    for _ in range(4):
        precip = (precip
                  + 0.25 * np.roll(precip, 1, 0) + 0.25 * np.roll(precip, -1, 0)
                  + 0.15 * np.roll(precip, 1, 1) + 0.15 * np.roll(precip, -1, 1)) / 1.80
    if land.any():
        precip *= mm_at_p90 / (np.percentile(precip[land], 90) + 1e-12)
    return precip


def classify(z, land, temp, precip, slope, water_dist):
    """Assign a biome to every land cell from temperature and moisture."""
    p, t = precip, temp
    b = np.full(z.shape, -1, dtype=int)

    b = np.where(land & (p < 220), DESERT, b)
    b = np.where(land & (p >= 220) & (p < 430), SCRUB, b)
    b = np.where(land & (p >= 430) & (p < 680), STEPPE, b)
    b = np.where(land & (p >= 680) & (p < 1000), WOODLAND, b)
    b = np.where(land & (p >= 1000), FOREST, b)

    b = np.where(land & (t < 5.0) & (p >= 300), TAIGA, b)
    b = np.where(land & (t < 0.0), TUNDRA, b)
    b = np.where(land & (t < -4.0), ALPINE, b)
    b = np.where(land & (t < -9.0), ICE, b)
    # Low, flat, wet ground near standing water becomes fen.
    b = np.where(land & (z < 0.07) & (slope < 0.010) & (p > 600) & (water_dist < 5),
                 MARSH, b)
    return b
