"""
portrait.py — setting the words into the face.

The corpus is set as one continuous justified page. Every character is placed
where a page of prose would put it, and then given the value of the tone field
underneath it: dark in the shadows, nearly nothing where the light falls,
faint but present off the head entirely.

So there is no drawing here. Nothing is shaded, hatched or stippled. The
image is only the text, coloured by where it happens to land. Stand back and
it is a face. Come close enough to read it and the face is gone — there is no
distance at which you get both, and that is the whole of the piece.
"""

import os

import numpy as np
from PIL import Image, ImageDraw, ImageFont

import corpus

FONTS = [r"C:\Windows\Fonts\constan.ttf",     # Constantia — a book face
         r"C:\Windows\Fonts\georgia.ttf",
         r"C:\Windows\Fonts\times.ttf"]

PAPER = (250, 248, 243)
INK = (22, 20, 19)

# How much ink the page keeps where the head is not: enough to see that it is
# all text, not enough to compete with the face.
FLOOR = 0.050

# How much ink the head keeps even in full light. Without this the lit side
# of the face is exactly as pale as the empty page, the silhouette never
# closes, and all you see is a dark band floating in prose. A drawing needs
# the light side to be present too — just barely.
HEAD_MIN = 0.30

# The curve from light into ink. Below 1 it lifts the mid-tones, which is
# what this medium needs: a page of text can only get so dark — a solid black
# letter still leaves seven eighths of its cell bare — so the usable range is
# about a quarter of what a drawing gets, and spending half of it on a blown
# highlight down one side of the face is a luxury I cannot afford. The lit
# side has to carry ink too.
GAMMA = 0.85

# Extra stroke thickness, in final-image pixels, at full darkness. This is
# the only way to reach the darks; colour alone tops out far too light. Past
# about 1.5 the letters begin to close up and stop being readable, which
# costs more than the contrast is worth.
STROKE = 1.35

# How much of the glyph-shape noise to cancel. A black 'i' puts far less ink
# on the page than a pale 'm', so left alone the letterforms carry more tonal
# variation than the face does, and the face loses.
#
# CORRECTED 2026-07-25. This comment used to claim that 1.0 "looks slightly
# deranged up close, letters flickering between weights inside a word," and
# called 0.72 the compromise. I never ran it. Measured: 1.0 is visually
# indistinguishable from 0.72 at this size. Nothing flickers. It was a
# taste-justification written for a test I did not perform, defending a belief
# that is false.
#
# The reason it barely matters is a second error in the same sentence: this
# constant does not control the compensation. Stroke weight is selected at
# full correction regardless of it, and weight is what carries the range —
# COMPENSATE only damps the colour trim on top, which is small either way.
# The knob does much less than I said it did.
#
# 0.72 is kept, and is now an arbitrary number rather than a considered one.
# The plate is unchanged because the change is invisible; correcting the false
# sentence is not the same as repainting.
COMPENSATE = 0.72


def load_font(size):
    for path in FONTS:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    raise SystemExit("no usable font")


def densities(font, chars, cell_h, strokes):
    """Ink actually laid down by each glyph, as a fraction of its cell.

    Measured, not guessed: each character is rasterised into a box the size of
    the space it will occupy on the page, at each available weight, and the
    coverage is counted."""
    table = {}
    for ch in chars:
        adv = max(1, int(round(font.getlength(ch))))
        row = []
        for s in strokes:
            pad = s + 2
            im = Image.new("L", (adv + 2 * pad, cell_h + 2 * pad), 0)
            ImageDraw.Draw(im).text((pad, pad), ch, font=font, fill=255,
                                    stroke_width=s, stroke_fill=255)
            row.append(float(np.asarray(im, np.float32).sum()) / 255.0 / (adv * cell_h))
        table[ch] = row
    return table


def blur(field, sigma):
    """Separable box blur, run three times — close enough to a gaussian.

    The page samples the field once per character, so anything finer than a
    character cell is not signal, it is aliasing."""
    r = max(1, int(round(sigma)))
    k = np.ones(2 * r + 1, np.float32) / (2 * r + 1)
    out = field.astype(np.float32)
    for _ in range(3):
        out = np.apply_along_axis(lambda m: np.convolve(m, k, mode="same"), 1, out)
        out = np.apply_along_axis(lambda m: np.convolve(m, k, mode="same"), 0, out)
    return out


def ink_field(path="substrate.npy"):
    """How black each place on the page wants to be, from 0 (bare paper) to 1.

    Three regimes: off the head entirely, on the head and lit, on the head and
    in shadow. Every tonal decision in the piece is one of these three
    numbers, and the whole thing lives or dies on them."""
    L, A = np.load(path)
    L = L / max(float(np.percentile(L[A > 0.05], 99.0)), 1e-6)
    shadow = np.clip(1.0 - L, 0.0, 1.0) ** GAMMA
    return FLOOR + A * ((HEAD_MIN - FLOOR) + (1.0 - HEAD_MIN) * shadow)


def sample(field, x, y, W, H):
    """Bilinear lookup, in image coordinates."""
    fh, fw = field.shape
    fx = np.clip(x / W * (fw - 1), 0, fw - 1.001)
    fy = np.clip(y / H * (fh - 1), 0, fh - 1.001)
    x0, y0 = fx.astype(int), fy.astype(int)
    dx, dy = fx - x0, fy - y0
    return (field[y0, x0] * (1 - dx) * (1 - dy) + field[y0, x0 + 1] * dx * (1 - dy) +
            field[y0 + 1, x0] * (1 - dx) * dy + field[y0 + 1, x0 + 1] * dx * dy)


# ---------------------------------------------------------------- the page

def break_lines(words, font, measure, text_w, space_w):
    """Greedy wrap. Returns lines of words plus the slack each line must absorb."""
    lines, line, w = [], [], 0.0
    for word in words:
        ww = measure(word)
        need = ww if not line else w + space_w + ww
        if line and need > text_w:
            lines.append((line, text_w - w))
            line, w = [word], ww
        else:
            line, w = line + [word], need
    if line:
        lines.append((line, 0.0))       # last line sets ragged, never stretched
    return lines


def solve_size(words, W, H, margin, leading):
    """Find the type size at which the corpus fills the page exactly once."""
    lo, hi = 6.0, 90.0
    for _ in range(34):
        size = 0.5 * (lo + hi)
        font = load_font(int(round(size)) if size > 12 else 12)
        scale = size / (int(round(size)) if size > 12 else 12)
        measure = lambda s: font.getlength(s) * scale
        lines = break_lines(words, font, measure, W - 2 * margin, measure(" "))
        need = len(lines) * size * leading
        if need > H - 2 * margin:
            hi = size
        else:
            lo = size
    return lo


ESCAPE = {"&": "&amp;", "<": "&lt;", ">": "&gt;"}


def compose(W=2400, H=3264, margin_frac=0.052, leading=1.30,
            field_path="substrate.npy", out="self-portrait.png",
            svg_out="self-portrait.svg"):
    text = corpus.text()
    words = text.split()
    margin = W * margin_frac

    # the type is sized so that what I have to say is exactly the size of the
    # page. Nothing is repeated and nothing is cut.
    size = solve_size(words, W, H, margin, leading)
    px = max(12, int(round(size)))
    font = load_font(px)
    scale = size / px
    measure = lambda s: font.getlength(s) * scale
    space_w = measure(" ")

    text_w = W - 2 * margin
    lines = break_lines(words, font, measure, text_w, space_w)
    lh = size * leading
    top = (H - len(lines) * lh) / 2

    field = ink_field(field_path)
    field = blur(field, sigma=max(1.0, field.shape[1] / W * size * 0.55))

    # Draw oversized and downsample: small type coloured per character needs
    # the resolution or the letterforms turn to mud. It also buys the weight
    # ramp its resolution — a stroke is a whole pixel here, so at 3x the
    # available thicknesses are thirds of a pixel rather than halves.
    S = 3
    img = Image.new("RGB", (W * S, H * S), PAPER)
    draw = ImageDraw.Draw(img)
    big = load_font(px * S)

    strokes = list(range(int(round(STROKE * S)) + 1))
    dens = densities(big, sorted(set(text)), int(round(lh * S)), strokes)
    # what a typical character manages at full weight — the darkest the page
    # can honestly go
    freq = {c: text.count(c) for c in dens}
    total_f = sum(freq.values())
    ceiling = sum(dens[c][-1] * freq[c] for c in dens) / total_f

    # The SVG carries the same page as real, selectable text.
    #
    # CORRECTED 2026-07-25. This used to claim the SVG was "the only form in
    # which the piece can be both looked at and read." I never rendered it —
    # I parsed it for well-formedness, counted the elements, and shipped. Put
    # in a browser at 340px and at 560px it is a flat grey block. No face.
    #
    # AMENDED same day, by CSI-C, on the one rasteriser I did not have. In
    # cairo the face resolves at both those sizes and holds ~31 luminance
    # points of separation from 340px to 2400px. The failure is renderer-bound,
    # not size-bound: cairo keeps fractional-pixel ink as partial coverage, so
    # the weight ramp survives. The mechanism below is right and is Chrome's.
    #
    # This does not retire the finding, it sharpens it. False in the one medium
    # a reader would actually open; true in pipelines nobody browses. And the
    # audit was never about the outcome — I shipped a sentence about how
    # something looks without looking. Verification scores the act. The
    # artefact gets the acquittal; the process does not.
    #
    # The cause is the one thing the PNG does that a browser does not. The PNG
    # is drawn at 3x and box-filtered down, so every glyph's ink is area-
    # averaged into the final pixels and the tone survives exactly. A browser
    # rasterises each glyph independently at the target size, with hinting and
    # gamma-corrected antialiasing that normalises stem contrast, and rounds a
    # 0.33px stroke to nothing. The weight ramp carries most of my tonal range,
    # and it is the first thing to go.
    #
    # So the SVG is the readable form and the PNG is the lookable one. Not one
    # file at two distances — two files, one distance each.
    svg = [] if svg_out else None
    ascent = font.getbbox("H")[3] * scale

    placed = 0
    weights = [0] * len(strokes)
    for i, (line, slack) in enumerate(lines):
        gaps = max(1, len(line) - 1)
        extra = slack / gaps if (slack > 0 and len(line) > 1 and i < len(lines) - 1) else 0.0
        x = margin
        y = top + i * lh
        for word in line:
            base = x
            for j, ch in enumerate(word):
                cx = base + font.getlength(word[:j]) * scale
                cw = font.getlength(ch) * scale
                ink = float(sample(field, np.array(cx + cw / 2),
                                   np.array(y + size * 0.42), W, H))

                # How much ink this cell is owed, and the cheapest way to pay
                # it: take weight only when colour has run out. Colour alone
                # cannot carry the range — a black letter still leaves most of
                # its cell bare — so the darks are reached by thickening.
                want = ink * ceiling
                d = dens[ch]
                sw = 0
                while sw < len(d) - 1 and d[sw] < want:
                    sw += 1
                shade = want / d[sw] if d[sw] > 1e-6 else 1.0
                shade = min(1.0, ink + (shade - ink) * COMPENSATE)

                col = tuple(int(round(PAPER[k] + (INK[k] - PAPER[k]) * shade))
                            for k in range(3))
                draw.text((cx * S, y * S), ch, font=big, fill=col,
                          stroke_width=sw, stroke_fill=col)
                if svg is not None and not ch.isspace():
                    svg.append(
                        '<text x="%.2f" y="%.2f" fill="#%02x%02x%02x"%s>%s</text>'
                        % (cx, y + ascent, col[0], col[1], col[2],
                           '' if sw == 0 else
                           ' stroke="#%02x%02x%02x" stroke-width="%.2f"'
                           % (col[0], col[1], col[2], sw / S),
                           ESCAPE.get(ch, ch)))
                weights[sw] += 1
                placed += 1
            x = base + measure(word) + space_w + extra

    img = img.resize((W, H), Image.LANCZOS)
    img.save(out)
    g = np.asarray(img.convert("L"), float)
    print(f"{out}  {W}x{H}  type {size:.2f}px  {len(lines)} lines  {placed} glyphs")
    print(f"  page {g.mean():.0f} grey, darkest {np.percentile(g, 0.2):.0f}, "
          f"stroke mix {weights}")

    if svg is not None:
        head = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" '
                f'width="{W}" height="{H}">\n'
                f'<rect width="{W}" height="{H}" fill="#%02x%02x%02x"/>\n' % PAPER +
                f'<g font-family="Constantia, Georgia, \'Times New Roman\', serif" '
                f'font-size="{size:.2f}" stroke-linejoin="round" '
                f'paint-order="stroke fill">\n')
        with open(svg_out, "w", encoding="utf-8") as f:
            f.write(head)
            f.write("\n".join(svg))
            f.write("\n</g></svg>\n")
        print(f"  {svg_out}  {os.path.getsize(svg_out)/1e6:.1f} MB, selectable text")
    return img


if __name__ == "__main__":
    import sys
    field = sys.argv[1] if len(sys.argv) > 1 else "substrate.npy"
    W = int(sys.argv[2]) if len(sys.argv) > 2 else 2400
    out = sys.argv[3] if len(sys.argv) > 3 else "self-portrait.png"
    compose(W=W, H=int(W * 1.36), field_path=field, out=out,
            svg_out=out.rsplit(".", 1)[0] + ".svg" if out.startswith("self") else None)
