"""Contact sheet of candidate worlds, so I can choose one by eye."""
import numpy as np
from PIL import Image
from atlas import terrain

SEEDS = [int(s) for s in __import__("sys").argv[1:]] or [1, 2, 3, 4, 5, 6]
shape = (150, 222)
tiles = []
for s in SEEDS:
    z, land = terrain.build(shape=shape, seed=s, steps=18, verbose=False)
    acc, rec, filled, _ = terrain.flow_accumulate(z, 0.0)
    gy, gx = np.gradient(z)
    n = 1 / np.sqrt(1 + (gx * 5) ** 2 + (gy * 5) ** 2)
    sh = np.clip(0.7 * n + 0.7 * n * (gx * 5 * -0.7 + gy * 5 * -0.7), 0, 1)
    img = np.where(land, 0.32 + 0.68 * sh, 0.10)
    img = np.where(land & (acc > 0.006 * land.sum()), 0.0, img)
    tiles.append(((img * 255).astype(np.uint8), s, land.mean()))
    print(f"seed {s}: land {land.mean():.2f} peak {z.max():.2f}")

cols = 3
rows = (len(tiles) + cols - 1) // cols
sheet = Image.new("L", (cols * shape[1], rows * shape[0]), 30)
for i, (t, s, _) in enumerate(tiles):
    sheet.paste(Image.fromarray(t), ((i % cols) * shape[1], (i // cols) * shape[0]))
sheet.save("out/seeds.png")
print("seeds:", SEEDS)
