"""Second plate: the wearing of names.

The same country, drawn only for its speech. Shading gives the number of
sound changes that have reached each place; the lines between the bands are
isoglosses. Because distance here is walking effort, the bands crowd against
the ranges and run far up the valleys, and the map becomes an argument: the
shape of the language is the shape of the ground.
"""

import numpy as np
from PIL import Image, ImageDraw

from .render import (HEARTH_COLOURS, INK, PAPER, MapRenderer, _font,
                     _hillshade, _paper_grain)

TONGUE_RAMP = [
    [(246, 233, 226), (150, 96, 84)],     # Ammoric   -- red
    [(233, 241, 231), (72, 100, 68)],     # Vennuk    -- green
    [(230, 234, 245), (74, 84, 128)],     # Selane    -- blue
]


class DialectPlate(MapRenderer):
    def base_raster(self):
        w = self.w
        h, wd = w.z.shape
        img = np.full((h, wd, 3), 226.0)
        img[:] = np.array([214, 219, 222])          # quiet sea

        k = self._upsample(self.sv.namer.law_field()).astype(float)
        own = self._upsample(self.sv.namer.owner_c)

        land_col = np.full((h, wd, 3), 236.0)
        for i in range(len(self.sv.namer.tongues)):
            m = (own == i) & w.land
            if not m.any():
                continue
            kk = k[m]
            lo, hi = kk.min(), max(kk.max(), kk.min() + 1)
            t = (kk - lo) / (hi - lo)
            a, b = np.array(TONGUE_RAMP[i % 3][0]), np.array(TONGUE_RAMP[i % 3][1])
            land_col[m] = a[None, :] * (1 - t[:, None]) + b[None, :] * t[:, None]

        # A whisper of relief, so the reader can see what the lines are avoiding.
        sh = _hillshade(w.z, w.land, exag=9.0)
        land_col *= (0.90 + 0.20 * sh)[..., None]
        img = np.where(w.land[..., None], land_col, img)
        img[w.lake] = np.array([206, 214, 219])
        return np.clip(img, 0, 255)

    def isoglosses(self, draw):
        """Drawn hard here: they are the subject, not a note in the margin."""
        k = self._upsample(self.sv.namer.law_field())
        own = self._upsample(self.sv.namer.owner_c)
        land = self.w.land & (k >= 0)
        edge = ((k != np.roll(k, 1, 1)) | (k != np.roll(k, 1, 0))) & land
        border = ((own != np.roll(own, 1, 1)) | (own != np.roll(own, 1, 0))) & land

        ys, xs = np.where(edge & ~border)
        for y, x in zip(ys, xs):
            cx, cy = self.px(y, x)
            r = 1.0 * self.ss
            draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(86, 74, 68, 165))
        ys, xs = np.where(border)
        for y, x in zip(ys, xs):
            cx, cy = self.px(y, x)
            r = 1.9 * self.ss
            draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(52, 44, 40, 225))

    def symbols(self, draw):
        for s in self.sv.sites:
            cx, cy = self.px(s["y"], s["x"])
            col = HEARTH_COLOURS[s["tongue_idx"] % 3]
            r = (2.0 + 2.6 * (s["pop"] / 110000.0) ** 0.45) * self.ss
            draw.ellipse([cx - r, cy - r, cx + r, cy + r],
                         fill=PAPER + (255,), outline=tuple(col) + (255,),
                         width=int(1.5 * self.ss))

    def type_pass(self, draw):
        sv = self.sv
        f = _font("town", int(8.2 * self.ss))
        f_b = _font("town_b", int(9.6 * self.ss))
        for s in sorted(sv.sites, key=lambda s: -s["pop"]):
            fo = f_b if s["pop"] > 40000 else f
            self.place_label(draw, self.px(s["y"], s["x"]), s["name"], fo,
                             colour=(52, 44, 40))

    def ladder(self, draw):
        """The same word, said at four removes from each hearth."""
        sv = self.sv
        f_h = _font("town_b", int(9.0 * self.ss))
        f_n = _font("note", int(7.6 * self.ss))
        f_i = _font("note_i", int(7.2 * self.ss))
        f_w = _font("town", int(8.4 * self.ss))

        options = [["cold", "ford"], ["stone", "haven"], ["old", "bridge"],
                   ["black", "water"], ["high", "pass"], ["salt", "market"],
                   ["grey", "mouth"], ["new", "hall"], ["deep", "spring"],
                   ["white", "gate"], ["far", "field"], ["red", "mill"]]
        rows = []
        for i, tg in enumerate(sv.namer.tongues):
            root = tg.demo_root(options)
            forms = [tg.name_for(root, fr) for fr in (0.0, 0.34, 0.67, 1.0)]
            rows.append((tg.name, tg.compound(root), tg.gloss(root), forms,
                         HEARTH_COLOURS[i % 3]))

        wbox = 336 * self.ss
        hbox = (64 + 19 * len(rows)) * self.ss
        x0 = self.mw - self.margin * 1.15 - wbox
        y0 = self.mh - self.margin * 1.15 - hbox
        draw.rectangle([x0, y0, x0 + wbox, y0 + hbox], fill=PAPER + (232,),
                       outline=INK + (255,), width=int(1.1 * self.ss))
        self.labels.append((x0, y0, x0 + wbox, y0 + hbox))

        yy = y0 + 8 * self.ss
        draw.text((x0 + 10 * self.ss, yy), "ONE WORD, FOUR DISTANCES",
                  font=f_h, fill=INK + (255,))
        yy += 12 * self.ss
        draw.text((x0 + 10 * self.ss, yy),
                  "One compound per tongue, as it is said at the hearth and at",
                  font=f_i, fill=(104, 92, 82, 255))
        yy += 9.5 * self.ss
        draw.text((x0 + 10 * self.ss, yy),
                  "increasing remove from it. The rim keeps what the centre wore away.",
                  font=f_i, fill=(104, 92, 82, 255))
        yy += 15 * self.ss

        colx = [10, 112, 170, 228, 282]
        draw.text((x0 + colx[0] * self.ss, yy), "tongue / old form", font=f_i,
                  fill=(120, 106, 96, 255))
        for j, lbl in enumerate(["at the hearth", "nearer", "far", "beyond"]):
            draw.text((x0 + colx[j + 1] * self.ss, yy), lbl, font=f_i,
                      fill=(120, 106, 96, 255))
        yy += 11 * self.ss
        draw.line([(x0 + 10 * self.ss, yy), (x0 + wbox - 10 * self.ss, yy)],
                  fill=(168, 154, 142, 255), width=int(0.8 * self.ss))
        yy += 5 * self.ss

        for name, proto, gloss, forms, col in rows:
            draw.ellipse([x0 + 10 * self.ss, yy + 3 * self.ss,
                          x0 + 15 * self.ss, yy + 8 * self.ss],
                         fill=tuple(col) + (255,))
            draw.text((x0 + 19 * self.ss, yy), name, font=f_n, fill=INK + (255,))
            draw.text((x0 + 19 * self.ss, yy + 8.5 * self.ss),
                      proto + "  '" + gloss + "'", font=f_i,
                      fill=(126, 112, 100, 255))
            for j, form in enumerate(forms):
                draw.text((x0 + colx[j + 1] * self.ss, yy + 1 * self.ss), form,
                          font=f_w, fill=(52, 44, 40, 255))
            yy += 19 * self.ss

    def scalebar(self, draw):
        from .render import MapRenderer as _MR
        save_w = self.mw
        self.mw = int(self.mw * 0.52)      # park it clear of the ladder panel
        _MR.scalebar(self, draw)
        self.mw = save_w

    def key(self, draw):
        f_h = _font("town_b", int(8.6 * self.ss))
        f_i = _font("note_i", int(7.2 * self.ss))
        x0 = self.mw - self.margin * 1.15
        y0 = self.margin * 1.15
        wbox, hbox = 152 * self.ss, 104 * self.ss
        draw.rectangle([x0 - wbox, y0, x0, y0 + hbox], fill=PAPER + (232,),
                       outline=INK + (255,), width=int(1.1 * self.ss))
        self.labels.append((x0 - wbox, y0, x0, y0 + hbox))
        yy = y0 + 8 * self.ss
        draw.text((x0 - wbox + 9 * self.ss, yy), "THE WEARING OF NAMES",
                  font=f_h, fill=INK + (255,))
        yy += 14 * self.ss
        for i, tg in enumerate(self.sv.namer.tongues):
            a, b = TONGUE_RAMP[i % 3]
            bw = 96 * self.ss
            for t in range(48):
                f = t / 47
                c = tuple(int(a[q] * (1 - f) + b[q] * f) for q in range(3))
                draw.rectangle([x0 - wbox + 9 * self.ss + bw * t / 48, yy,
                                x0 - wbox + 9 * self.ss + bw * (t + 1) / 48,
                                yy + 6 * self.ss], fill=c + (255,))
            draw.text((x0 - wbox + 110 * self.ss, yy - 1 * self.ss), tg.name,
                      font=f_i, fill=INK + (255,))
            yy += 11 * self.ss
        yy += 4 * self.ss
        for line in ["pale: few changes have reached —",
                     "the old forms survive.",
                     "deep: at the hearth, where every",
                     "change has run its course."]:
            draw.text((x0 - wbox + 9 * self.ss, yy), line, font=f_i,
                      fill=(104, 92, 82, 255))
            yy += 9.2 * self.ss

    def cartouche(self, draw):
        sv = self.sv
        x0, y0 = self.margin * 1.15, self.margin * 1.15
        pad = 11 * self.ss
        f_t = _font("town_b", int(17 * self.ss))
        f_s = _font("note_i", int(8.2 * self.ss))
        title = "ISOGLOSSES OF " + sv.title.upper()
        sub = "where each sound change stopped travelling"
        tw = self._text_size(draw, title, f_t, int(3 * self.ss))[0]
        bw = max(tw, self._text_size(draw, sub, f_s)[0]) + 2 * pad
        bh = 42 * self.ss
        draw.rectangle([x0, y0, x0 + bw, y0 + bh], fill=PAPER + (232,),
                       outline=INK + (255,), width=int(1.1 * self.ss))
        self._raw(draw, (x0 + pad, y0 + pad * .7), title, f_t, INK + (255,),
                  int(3 * self.ss))
        draw.text((x0 + pad, y0 + pad * .7 + 22 * self.ss), sub, font=f_s,
                  fill=(112, 96, 82, 255))
        self.labels.append((x0, y0, x0 + bw, y0 + bh))

    def render(self, path):
        base = self.base_raster()
        h, wd, _ = base.shape
        im = Image.fromarray(base.astype(np.uint8)).resize(
            (wd * self.S, h * self.S), Image.LANCZOS)
        canvas = Image.new("RGB", (self.mw, self.mh), PAPER)
        canvas.paste(im, (self.margin, self.margin))

        ov = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(ov)
        self.isoglosses(d)
        self.coastline(d)
        self.roads(d)
        canvas = Image.alpha_composite(canvas.convert("RGBA"), ov)

        ov2 = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        d2 = ImageDraw.Draw(ov2)
        blank = ImageDraw.Draw(Image.new("RGBA", canvas.size, (0, 0, 0, 0)))
        self.cartouche(blank)          # reserve the panel rectangles only
        self.key(blank)
        self.ladder(blank)
        self.symbols(d2)
        self.hearths(d2)
        self.type_pass(d2)
        self.frame(d2)
        self.cartouche(d2)             # now paint them, over everything
        self.key(d2)
        self.ladder(d2)
        self.scalebar(d2)
        canvas = Image.alpha_composite(canvas, ov2).convert("RGB")

        arr = np.asarray(canvas).astype(float) + _paper_grain(canvas.size, self.rng)[..., None]
        out = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
        out = out.resize((self.mw // self.ss, self.mh // self.ss), Image.LANCZOS)
        out.save(path, quality=96)
        return out
