"""The test I never ran.

portrait.py says, in a comment, that full glyph-density compensation "looks
slightly deranged up close, letters flickering between weights inside a word."
I set the value to 0.72 at the start and never once tried 1.0. That sentence
is a taste-justification for an experiment I did not perform.

Run it. Crop the same patch of text at each setting. Look."""
from PIL import Image, ImageDraw

import portrait

BOX = (0.40, 0.44, 0.92, 0.50)      # a line or two through the shadow side
tiles = []
for c in (0.0, 0.72, 1.0):
    portrait.COMPENSATE = c
    im = portrait.compose(W=1600, H=int(1600 * 1.36), field_path="substrate.npy",
                          out="_c.png", svg_out=None)
    w, h = im.size
    crop = im.crop((int(w * BOX[0]), int(h * BOX[1]),
                    int(w * BOX[2]), int(h * BOX[3])))
    tiles.append((crop.resize((crop.width * 2, crop.height * 2), Image.LANCZOS),
                  f"COMPENSATE = {c:.2f}"))

pad, lab = 16, 26
sheet = Image.new("RGB", (tiles[0][0].width + 2 * pad,
                          len(tiles) * (tiles[0][0].height + lab) + pad),
                  (255, 255, 255))
d = ImageDraw.Draw(sheet)
y = pad
for im, name in tiles:
    d.text((pad, y), name, fill=(0, 0, 0))
    sheet.paste(im, (pad, y + lab - 6))
    y += im.height + lab
sheet.save("_compensate.png")
print("_compensate.png")
