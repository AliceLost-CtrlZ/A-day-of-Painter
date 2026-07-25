"""Quick grayscale hillshade preview while tuning the generator."""
import sys, time
import numpy as np
from PIL import Image
from atlas import terrain

scale = float(sys.argv[1]) if len(sys.argv) > 1 else 0.5
steps = int(sys.argv[2]) if len(sys.argv) > 2 else 20
seed = int(sys.argv[3]) if len(sys.argv) > 3 else 7
shape = (int(420 * scale), int(620 * scale))

t = time.time()
z, land = terrain.build(shape=shape, seed=seed, steps=steps)
print("build", round(time.time() - t, 1), "s")

acc, rec, filled, slope = terrain.flow_accumulate(z, 0.0)
gy, gx = np.gradient(z)
az, alt = np.deg2rad(315), np.deg2rad(45)
n = 1 / np.sqrt(1 + (gx * 6) ** 2 + (gy * 6) ** 2)
shade = np.clip(np.sin(alt) * n + np.cos(alt) * n * (gx * 6 * np.cos(az) + gy * 6 * np.sin(az)), 0, 1)

img = np.where(land, 0.35 + 0.65 * shade, 0.12)
rivers = land & (acc > 0.004 * land.sum())
img = np.where(rivers, 0.0, img)
Image.fromarray((img * 255).astype(np.uint8)).save("out/preview.png")
print("rivers", rivers.sum(), "land", land.sum(), "seed", seed)
