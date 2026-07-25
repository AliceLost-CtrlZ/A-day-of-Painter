"""Draw the survey as a map.

Rendered at 2x and downsampled, so the hairlines and the type stay clean.
Conventions are the ordinary ones: italic for water, roman for settlement,
letter-spaced small caps for regions, contours in a dry ochre.
"""

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from . import climate
from .world import KM_PER_CELL, METRES_PER_UNIT

FONTS = {
    "town": r"C:\Windows\Fonts\BOOKOS.TTF",
    "town_b": r"C:\Windows\Fonts\BOOKOSB.TTF",
    "water": r"C:\Windows\Fonts\BOOKOSI.TTF",
    "note": r"C:\Windows\Fonts\constan.ttf",
    "note_i": r"C:\Windows\Fonts\constani.ttf",
}

PAPER = (238, 230, 213)
INK = (58, 48, 40)
SEA = (176, 196, 203)
SEA_DEEP = (140, 166, 179)
RIVER = (104, 137, 156)
ROAD = (150, 106, 74)
HEARTH_COLOURS = [(150, 96, 84), (96, 118, 92), (98, 106, 140)]

BIOME_COLOUR = {
    climate.ICE:      (247, 245, 240),
    climate.ALPINE:   (214, 206, 195),
    climate.TUNDRA:   (204, 202, 178),
    climate.TAIGA:    (150, 168, 141),
    climate.FOREST:   (158, 176, 133),
    climate.WOODLAND: (185, 190, 141),
    climate.STEPPE:   (207, 199, 148),
    climate.SCRUB:    (213, 194, 148),
    climate.DESERT:   (223, 205, 168),
    climate.MARSH:    (176, 186, 152),
}


def _font(key, size):
    return ImageFont.truetype(FONTS[key], size)


def _hillshade(z, land, az=315, alt=38, exag=11.0):
    gy, gx = np.gradient(z * exag)
    az_r, alt_r = np.deg2rad(az), np.deg2rad(alt)
    slope = np.arctan(np.hypot(gx, gy))
    aspect = np.arctan2(-gx, gy)
    sh = (np.sin(alt_r) * np.cos(slope)
          + np.cos(alt_r) * np.sin(slope) * np.cos(az_r - aspect))
    return np.clip(sh, 0, 1)


def _paper_grain(size, rng, strength=7.0):
    w, h = size
    n = rng.normal(0, 1, (h // 2 + 1, w // 2 + 1))
    im = Image.fromarray(((n * 40) + 128).clip(0, 255).astype(np.uint8))
    im = im.resize((w, h), Image.BICUBIC).filter(ImageFilter.GaussianBlur(0.6))
    a = np.asarray(im).astype(float)
    return (a - a.mean()) / (a.std() + 1e-6) * strength


class MapRenderer:
    def __init__(self, sv, scale=2, margin=54, supersample=2):
        self.sv = sv
        self.w = sv.w
        self.S = scale * supersample
        self.ss = supersample
        self.margin = margin * supersample
        h, wd = self.w.z.shape
        self.mw = wd * self.S + 2 * self.margin
        self.mh = h * self.S + 2 * self.margin
        self.rng = np.random.default_rng(sv.w.seed * 31 + 5)
        self.labels = []          # placed boxes, for collision avoidance

    # -- helpers ------------------------------------------------------
    def px(self, y, x):
        return (self.margin + x * self.S, self.margin + y * self.S)

    # -- raster layers ------------------------------------------------
    def base_raster(self):
        w = self.w
        h, wd = w.z.shape
        img = np.zeros((h, wd, 3), float)

        # Sea: darker with distance from land, plus faint shelf banding.
        d = w.coast_dist_sea if hasattr(w, "coast_dist_sea") else None
        from .world import _chamfer
        dsea = _chamfer(w.land)
        t = np.clip(dsea / 26.0, 0, 1) ** 0.65
        sea = (np.array(SEA)[None, None, :] * (1 - t[..., None])
               + np.array(SEA_DEEP)[None, None, :] * t[..., None])
        band = (np.sin(dsea * 0.85) * 0.5 + 0.5) * np.exp(-dsea / 9.0)
        sea += band[..., None] * 9.0
        img[:] = sea

        land_col = np.zeros((h, wd, 3), float)
        for k, c in BIOME_COLOUR.items():
            m = (w.biome == k)
            land_col[m] = c
        # Height tints the biome colour: uplands go warm-grey, lowlands rich.
        hi = np.clip((w.z - 0.35) / 1.3, 0, 1)[..., None]
        land_col = land_col * (1 - 0.34 * hi) + np.array([203, 194, 180]) * 0.34 * hi
        low = np.clip(1 - w.z / 0.22, 0, 1)[..., None]
        land_col = land_col * (1 - 0.10 * low) + np.array([176, 186, 146]) * 0.10 * low

        sh = _hillshade(w.z, w.land)
        shade = 0.74 + 0.46 * sh
        # A touch of aerial perspective: high ground catches more light.
        land_col = land_col * shade[..., None]
        img = np.where(w.land[..., None], land_col, img)

        img[w.lake] = np.array(SEA) * 0.97
        return np.clip(img, 0, 255)

    def contours(self, draw, interval=0.26):
        """Thin index contours. They support the hillshade, never fight it."""
        w = self.w
        z = w.z
        gentle = w.slope < 0.075          # contours crowd to mud on cliffs
        levels = np.arange(interval, z.max(), interval)
        for li, lv in enumerate(levels):
            major = (li % 2 == 1)
            above = (z >= lv) & w.land
            edge = above ^ np.roll(above, 1, 1)
            edge |= above ^ np.roll(above, 1, 0)
            edge &= w.land & gentle
            ys, xs = np.where(edge)
            col = (146, 118, 84, 62 if major else 34)
            r = self.S * (0.34 if major else 0.26)
            for y, x in zip(ys, xs):
                cx, cy = self.px(y, x)
                draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=col)

    def rivers(self, draw):
        w = self.w
        q = np.where(w.land, w.discharge, 0)
        top = np.percentile(q[w.land], 99.9)
        thr = top * 0.0028
        h, wd = q.shape
        rec = w.rec
        for i in range(h * wd):
            if not w.land.ravel()[i] or q.ravel()[i] < thr:
                continue
            r = rec[i]
            if r == i:
                continue
            y0, x0 = divmod(i, wd)
            y1, x1 = divmod(r, wd)
            f = (q.ravel()[i] / top) ** 0.42
            width = max(self.ss * 0.75, f * 4.6 * self.ss)
            a = self.px(y0, x0)
            b = self.px(y1, x1)
            draw.line([a, b], fill=RIVER + (255,), width=int(round(width)))

    def roads(self, draw):
        for p in self.sv.paths:
            pts = [self.px(y, x) for y, x in p["cells"]]
            if len(pts) < 2:
                continue
            draw.line(pts, fill=(250, 243, 229, 185), width=int(3.2 * self.ss),
                      joint="curve")
            draw.line(pts, fill=ROAD + (205,), width=int(1.35 * self.ss),
                      joint="curve")

    def coastline(self, draw):
        w = self.w
        edge = w.land ^ np.roll(w.land, 1, 1)
        edge |= w.land ^ np.roll(w.land, 1, 0)
        ys, xs = np.where(edge)
        r = self.S * 0.62
        for y, x in zip(ys, xs):
            cx, cy = self.px(y, x)
            draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(64, 72, 74, 235))

    # -- type ---------------------------------------------------------
    def _fits(self, box, pad=2):
        x0, y0, x1, y1 = box
        for (a, b, c, d) in self.labels:
            if not (x1 + pad < a or x0 - pad > c or y1 + pad < b or y0 - pad > d):
                return False
        return not (x0 < self.margin * 0.4 or x1 > self.mw - self.margin * 0.4
                    or y0 < self.margin * 0.4 or y1 > self.mh - self.margin * 0.4)

    def place_label(self, draw, anchor, text, font, colour=INK, halo=True,
                    offsets=None, track=0):
        """Try a ring of offsets; take the first that does not collide."""
        ax, ay = anchor
        if offsets is None:
            offsets = [(9, -4), (-9, -4), (0, -14), (0, 12), (12, 8), (-12, 8),
                       (14, -12), (-14, -12), (0, -22), (0, 20)]
        wtext = self._text_size(draw, text, font, track)
        for ox, oy in offsets:
            sx = ax + ox * self.ss
            sy = ay + oy * self.ss
            if ox < 0:
                sx -= wtext[0]
            elif ox == 0:
                sx -= wtext[0] / 2
            box = (sx, sy - wtext[1] / 2, sx + wtext[0], sy + wtext[1] / 2)
            if self._fits(box):
                self.labels.append(box)
                self._draw_text(draw, (sx, sy - wtext[1] / 2), text, font,
                                colour, halo, track)
                return True
        return False

    def _text_size(self, draw, text, font, track=0):
        if track:
            wsum = sum(draw.textlength(ch, font=font) + track for ch in text)
            bb = font.getbbox(text)
            return wsum, bb[3] - bb[1]
        bb = draw.textbbox((0, 0), text, font=font)
        return bb[2] - bb[0], bb[3] - bb[1]

    def _draw_text(self, draw, xy, text, font, colour, halo, track=0):
        x, y = xy
        if halo:
            for dx in (-2, -1, 0, 1, 2):
                for dy in (-2, -1, 0, 1, 2):
                    if dx or dy:
                        self._raw(draw, (x + dx, y + dy), text, font,
                                  PAPER + (170,), track)
        self._raw(draw, (x, y), text, font, tuple(colour) + (255,), track)

    def _raw(self, draw, xy, text, font, fill, track):
        if not track:
            draw.text(xy, text, font=font, fill=fill)
            return
        x, y = xy
        for ch in text:
            draw.text((x, y), ch, font=font, fill=fill)
            x += draw.textlength(ch, font=font) + track

    # -- furniture ----------------------------------------------------
    def symbols(self, draw):
        for s in sorted(self.sv.sites, key=lambda s: s["pop"]):
            cx, cy = self.px(s["y"], s["x"])
            pop = s["pop"]
            r = (2.2 + 3.4 * (pop / 110000.0) ** 0.45) * self.ss
            if pop > 40000:
                draw.ellipse([cx - r - 1.6 * self.ss, cy - r - 1.6 * self.ss,
                              cx + r + 1.6 * self.ss, cy + r + 1.6 * self.ss],
                             outline=INK + (255,), width=int(1.2 * self.ss))
                draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=INK + (255,))
            elif pop > 12000:
                draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=PAPER + (255,),
                             outline=INK + (255,), width=int(1.4 * self.ss))
                draw.ellipse([cx - r * .4, cy - r * .4, cx + r * .4, cy + r * .4],
                             fill=INK + (255,))
            else:
                draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=PAPER + (255,),
                             outline=INK + (255,), width=int(1.2 * self.ss))

        for p in self.sv.peaks[:8]:
            cx, cy = self.px(p["y"], p["x"])
            hh = 4.2 * self.ss
            draw.polygon([(cx, cy - hh), (cx - hh * .82, cy + hh * .55),
                          (cx + hh * .82, cy + hh * .55)],
                         fill=(92, 78, 66, 235))

    def namer_owner(self):
        """Upsample the coarse tongue-territory map to full resolution."""
        oc = self.sv.namer.owner_c
        step = self.sv.namer.step
        h, wd = self.w.z.shape
        out = np.repeat(np.repeat(oc, step, 0), step, 1)
        return out[:h, :wd]

    def type_pass(self, draw):
        sv = self.sv
        f_big = _font("town_b", int(11.5 * self.ss))
        f_mid = _font("town", int(9.5 * self.ss))
        f_sml = _font("town", int(8.0 * self.ss))
        f_riv = _font("water", int(8.5 * self.ss))
        f_pk = _font("note_i", int(7.6 * self.ss))
        f_sea = _font("water", int(15 * self.ss))
        f_reg = _font("town", int(13 * self.ss))

        # Settlements claim their space first; the big display type has to
        # find room around them, which is the right way round.
        for s in sorted(sv.sites, key=lambda s: -s["pop"]):
            f = f_big if s["pop"] > 40000 else (f_mid if s["pop"] > 12000 else f_sml)
            self.place_label(draw, self.px(s["y"], s["x"]), s["name"], f)

        for sysm, rec in zip(sv.rivers, sv.river_names):
            cells = sysm["cells"]
            for frac in (0.42, 0.62, 0.28, 0.78):
                y, x = cells[int(len(cells) * frac)]
                if self.place_label(draw, self.px(y, x), rec["name"], f_riv,
                                    colour=(74, 104, 122),
                                    offsets=[(7, -7), (-7, -7), (7, 7), (-7, 7),
                                             (0, -11), (0, 11)]):
                    break

        for p in sv.peaks[:7]:
            self.place_label(draw, self.px(p["y"], p["x"]), p["name"], f_pk,
                             colour=(92, 78, 66),
                             offsets=[(7, 5), (-7, 5), (0, 11), (0, -13)])

        for q in sv.seas:
            self.place_label(draw, self.px(q["y"], q["x"]), q["name"].upper(),
                             f_sea, colour=(96, 122, 134),
                             track=int(3.0 * self.ss),
                             offsets=[(0, 0), (0, -16), (0, 16), (0, -30), (0, 30)])

        own = self.namer_owner()
        for i, reg in enumerate(sv.regions):
            m = (own == i) & self.w.land
            if m.sum() < 500:
                continue
            ys, xs = np.where(m)
            span = (xs.max() - xs.min()) * self.S
            txt = reg["name"].upper()
            track = int(3.4 * self.ss)
            if self._text_size(draw, txt, f_reg, track)[0] > span * 0.80:
                continue                      # it will not sit inside its own land
            cy, cx = self.sv.namer._deep_point(list(zip(ys, xs)))
            self.place_label(draw, self.px(cy, cx), txt, f_reg,
                             colour=(126, 108, 90), track=track,
                             offsets=[(0, 0), (0, -26), (0, 26), (0, -46), (0, 46),
                                      (40, 0), (-40, 0)])

    def _upsample(self, a):
        step = self.sv.namer.step
        h, wd = self.w.z.shape
        return np.repeat(np.repeat(a, step, 0), step, 1)[:h, :wd]

    def isoglosses(self, draw):
        """Lines beyond which a given sound change has not travelled.

        Each line is the edge of one increment of the law count, so they
        bunch where travel is hard -- along the ranges -- and spread wide
        across easy country. That bunching is the whole argument of the map.
        """
        k = self._upsample(self.sv.namer.law_field())
        land = self.w.land & (k >= 0)
        edge = ((k != np.roll(k, 1, 1)) | (k != np.roll(k, 1, 0))) & land
        # Territory boundaries are drawn more strongly than internal lines.
        own = self._upsample(self.sv.namer.owner_c)
        border = ((own != np.roll(own, 1, 1)) | (own != np.roll(own, 1, 0))) & land
        ys, xs = np.where(edge & ~border)
        for i, (y, x) in enumerate(zip(ys, xs)):
            if i % 2:
                continue
            cx, cy = self.px(y, x)
            r = 0.85 * self.ss
            draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(142, 104, 118, 132))
        ys, xs = np.where(border)
        for y, x in zip(ys, xs):
            cx, cy = self.px(y, x)
            r = 1.5 * self.ss
            draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(136, 84, 100, 190))

    def frame(self, draw):
        m = self.margin
        W, H = self.mw, self.mh
        draw.rectangle([m * .42, m * .42, W - m * .42, H - m * .42],
                       outline=INK + (255,), width=int(1.2 * self.ss))
        draw.rectangle([m * .58, m * .58, W - m * .58, H - m * .58],
                       outline=INK + (255,), width=int(3.0 * self.ss))
        draw.rectangle([m * .74, m * .74, W - m * .74, H - m * .74],
                       outline=INK + (255,), width=int(0.9 * self.ss))
        h, wd = self.w.z.shape
        for x in range(0, wd + 1, 20):
            px = self.px(0, x)[0]
            draw.line([(px, m * .58), (px, m * .74)], fill=INK + (255,),
                      width=int(1.1 * self.ss))
            draw.line([(px, H - m * .58), (px, H - m * .74)], fill=INK + (255,),
                      width=int(1.1 * self.ss))
        for y in range(0, h + 1, 20):
            py = self.px(y, 0)[1]
            draw.line([(m * .58, py), (m * .74, py)], fill=INK + (255,),
                      width=int(1.1 * self.ss))
            draw.line([(W - m * .58, py), (W - m * .74, py)], fill=INK + (255,),
                      width=int(1.1 * self.ss))

    def scalebar(self, draw):
        km = 200
        cells = km / KM_PER_CELL
        L = cells * self.S
        x0 = self.mw - self.margin * 1.15 - L - 62 * self.ss
        y0 = self.mh - self.margin * 1.25
        hbar = 3.2 * self.ss
        n = 4
        for i in range(n):
            a = x0 + L * i / n
            b = x0 + L * (i + 1) / n
            draw.rectangle([a, y0, b, y0 + hbar],
                           fill=(INK if i % 2 == 0 else PAPER) + (255,),
                           outline=INK + (255,), width=int(0.9 * self.ss))
        f = _font("note", int(7.2 * self.ss))
        draw.text((x0, y0 - 11 * self.ss), "0", font=f, fill=INK + (255,))
        draw.text((x0 + L - 8 * self.ss, y0 - 11 * self.ss), str(km),
                  font=f, fill=INK + (255,))
        draw.text((x0 + L + 5 * self.ss, y0 - 2 * self.ss), "kilometres",
                  font=f, fill=INK + (255,))

    def compass(self, draw):
        cx = self.margin * 1.5
        cy = self.mh - self.margin * 1.5
        r = 13 * self.ss
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=INK + (200,),
                     width=int(1.0 * self.ss))
        draw.polygon([(cx, cy - r * 1.28), (cx - r * .30, cy), (cx, cy - r * .30)],
                     fill=INK + (255,))
        draw.polygon([(cx, cy - r * 1.28), (cx + r * .30, cy), (cx, cy - r * .30)],
                     fill=(150, 138, 124, 255))
        draw.polygon([(cx, cy + r * 1.05), (cx - r * .22, cy), (cx, cy + r * .22)],
                     fill=(150, 138, 124, 255))
        draw.polygon([(cx, cy + r * 1.05), (cx + r * .22, cy), (cx, cy + r * .22)],
                     fill=INK + (200,))
        f = _font("note", int(7.5 * self.ss))
        draw.text((cx - 3 * self.ss, cy - r * 2.0), "N", font=f, fill=INK + (255,))

    def cartouche(self, draw):
        sv = self.sv
        x0 = self.margin * 1.15
        y0 = self.margin * 1.15
        pad = 11 * self.ss
        f_t = _font("town_b", int(20 * self.ss))
        f_s = _font("note_i", int(8.4 * self.ss))
        f_n = _font("note", int(7.6 * self.ss))

        title = sv.title.upper()
        sub = "a survey of the country and its names"
        smry = sv.summary()
        lines = [
            "{:,} sq. km   {:,} souls".format(smry["area_km2"], smry["population"]),
            "{} settlements   {} rivers surveyed".format(smry["towns"], smry["rivers"]),
            "highest ground {}, {:,.0f} m".format(smry["highest"]["name"],
                                                 smry["highest"]["m"]),
        ]
        tw = self._text_size(draw, title, f_t, int(4 * self.ss))[0]
        bw = max([tw] + [self._text_size(draw, l, f_n)[0] for l in lines]) + 2 * pad
        bh = (26 + 13 + 11 * len(lines)) * self.ss + pad

        draw.rectangle([x0, y0, x0 + bw, y0 + bh], fill=PAPER + (222,),
                       outline=INK + (255,), width=int(1.1 * self.ss))
        draw.rectangle([x0 + 3 * self.ss, y0 + 3 * self.ss,
                        x0 + bw - 3 * self.ss, y0 + bh - 3 * self.ss],
                       outline=INK + (110,), width=int(0.7 * self.ss))
        self._raw(draw, (x0 + pad, y0 + pad * .8), title, f_t, INK + (255,),
                  int(4 * self.ss))
        yy = y0 + pad * .8 + 25 * self.ss
        draw.text((x0 + pad, yy), sub, font=f_s, fill=(112, 96, 82, 255))
        yy += 14 * self.ss
        for l in lines:
            draw.text((x0 + pad, yy), l, font=f_n, fill=(88, 76, 66, 255))
            yy += 10.5 * self.ss
        self.labels.append((x0, y0, x0 + bw, y0 + bh))

    def legend(self, draw):
        sv = self.sv
        x0 = self.mw - self.margin * 1.15
        y0 = self.margin * 1.15
        f_h = _font("town_b", int(8.6 * self.ss))
        f_n = _font("note", int(7.4 * self.ss))
        f_i = _font("note_i", int(7.2 * self.ss))

        notes = ["Sound change radiates from", "each hearth. Remote valleys",
                 "keep archaic forms; ranges", "hold the changes back."]
        wbox = 126 * self.ss
        hbox = (44 + 11 * len(sv.namer.tongues) + 10 * len(notes)) * self.ss
        draw.rectangle([x0 - wbox, y0, x0, y0 + hbox], fill=PAPER + (222,),
                       outline=INK + (255,), width=int(1.1 * self.ss))
        yy = y0 + 7 * self.ss
        draw.text((x0 - wbox + 8 * self.ss, yy), "THE THREE TONGUES", font=f_h,
                  fill=INK + (255,))
        yy += 13 * self.ss
        for i, tg in enumerate(sv.namer.tongues):
            col = HEARTH_COLOURS[i % 3]
            draw.ellipse([x0 - wbox + 8 * self.ss, yy + 1.5 * self.ss,
                          x0 - wbox + 14 * self.ss, yy + 7.5 * self.ss],
                         fill=tuple(col) + (255,))
            draw.text((x0 - wbox + 19 * self.ss, yy), tg.name, font=f_n,
                      fill=INK + (255,))
            yy += 11 * self.ss
        yy += 3 * self.ss
        draw.line([(x0 - wbox + 8 * self.ss, yy + 4 * self.ss),
                   (x0 - wbox + 16 * self.ss, yy + 4 * self.ss)],
                  fill=(136, 84, 100, 220), width=int(1.8 * self.ss))
        draw.text((x0 - wbox + 19 * self.ss, yy), "limit of a tongue",
                  font=f_i, fill=INK + (255,))
        yy += 13 * self.ss
        for line in notes:
            draw.text((x0 - wbox + 8 * self.ss, yy), line, font=f_i,
                      fill=(96, 84, 74, 255))
            yy += 9.5 * self.ss
        self.labels.append((x0 - wbox, y0, x0, y0 + hbox))

    def hearths(self, draw):
        for i, tg in enumerate(self.sv.namer.tongues):
            hy, hx = tg.hearth
            cx, cy = self.px(hy, hx)
            col = HEARTH_COLOURS[i % 3]
            # A ring around the town that is the tongue's cradle, then the star.
            R = 13 * self.ss
            draw.ellipse([cx - R, cy - R, cx + R, cy + R],
                         outline=tuple(col) + (215,), width=int(1.6 * self.ss))
            r = 6.5 * self.ss
            pts = []
            for k in range(10):
                ang = -np.pi / 2 + k * np.pi / 5
                rr = r if k % 2 == 0 else r * 0.42
                pts.append((cx + rr * np.cos(ang) + R * 1.25,
                            cy + rr * np.sin(ang) - R * 0.9))
            draw.polygon(pts, fill=tuple(col) + (235,), outline=PAPER + (255,))

    # -- compose ------------------------------------------------------
    def render(self, path):
        base = self.base_raster()
        h, wd, _ = base.shape
        im = Image.fromarray(base.astype(np.uint8)).resize(
            (wd * self.S, h * self.S), Image.LANCZOS)
        canvas = Image.new("RGB", (self.mw, self.mh), PAPER)
        canvas.paste(im, (self.margin, self.margin))

        ov = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(ov)
        self.contours(d)
        self.isoglosses(d)
        self.rivers(d)
        self.coastline(d)
        self.roads(d)
        canvas = Image.alpha_composite(canvas.convert("RGBA"), ov)

        ov2 = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        d2 = ImageDraw.Draw(ov2)
        self.cartouche(d2)
        self.legend(d2)
        self.symbols(d2)
        self.hearths(d2)
        self.type_pass(d2)
        self.frame(d2)
        self.scalebar(d2)
        self.compass(d2)
        canvas = Image.alpha_composite(canvas, ov2).convert("RGB")

        arr = np.asarray(canvas).astype(float)
        arr += _paper_grain(canvas.size, self.rng)[..., None]
        yy, xx = np.mgrid[0:canvas.size[1], 0:canvas.size[0]]
        ny = (yy / canvas.size[1] - 0.5) * 2
        nx = (xx / canvas.size[0] - 0.5) * 2
        vig = 1 - 0.11 * np.clip((nx ** 2 + ny ** 2) - 0.25, 0, None)
        arr *= vig[..., None]
        out = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
        out = out.resize((self.mw // self.ss, self.mh // self.ss), Image.LANCZOS)
        out.save(path, quality=96)
        return out
