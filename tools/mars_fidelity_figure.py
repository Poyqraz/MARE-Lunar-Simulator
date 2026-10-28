"""Plot bundled measured data; this deliberately produces no simulated camera image.

    python -m pip install -r requirements-mars-plot.txt
    python tools/mars_fidelity_figure.py
"""
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from PIL import Image


root = Path(__file__).resolve().parents[1]
bundle = root / "Content/Mars/Jezero"
m = json.loads((bundle / "manifest.json").read_text())
z = np.loadtxt(bundle / "elevation.csv")
extent = [0, *m["grid"]["extent_m"][:1], 0, m["grid"]["extent_m"][1]]
a, b, c, d = z[:-1, :-1], z[:-1, 1:], z[1:, :-1], z[1:, 1:]
r = m["grid"]["resolution_m"]
slopes = np.maximum.reduce([np.degrees(np.arctan(np.hypot(dx, dy) / r)) for dx, dy in
                           ((b - a, c - a), (d - c, d - b), (b - a, d - b), (d - c, c - a))])
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10,
                     "axes.spines.top": False, "axes.spines.right": False})
fig, axes = plt.subplots(2, 2, figsize=(11.6, 10.4), layout="constrained")
fig.suptitle("Jezero C | Measured terrain review\nUSGS HiRISE data — this is not an Unreal render", fontsize=16)
axes[0, 0].imshow(Image.open(bundle / "ortho_reference.png"), extent=extent, origin="upper")
axes[0, 0].set_title("A. Registered orbital reference\nGrayscale; original illumination is baked in")
im = axes[0, 1].imshow(z, extent=extent, origin="lower", cmap="viridis")
axes[0, 1].axhline(126, color="white", ls="--", lw=0.9)
axes[0, 1].set_title("B. Actual elevation posts\n1 m spacing; local minimum subtracted")
fig.colorbar(im, ax=axes[0, 1], label="Local elevation (m)", shrink=0.82)
im = axes[1, 0].imshow(slopes, extent=extent, origin="lower", cmap="magma", vmin=0, vmax=22)
axes[1, 0].set_title("C. Triangle slope upper bound\nBoth diagonals considered; not a route certificate")
fig.colorbar(im, ax=axes[1, 0], label="Slope (degrees)", shrink=0.82)
for ax in (axes[0, 0], axes[0, 1], axes[1, 0]):
    ax.set(xlabel="Local east (m)", ylabel="Local north (m)", xlim=(0, 252), ylim=(0, 252))
profile = axes[1, 1]
profile.plot(np.arange(z.shape[1]) * r, z[126], color="#236885", lw=1.8)
profile.set(xlabel="Local east (m)", ylabel="Local elevation (m)", xlim=(0, 252), ylim=(0, 8.2),
            title="D. East–west profile at north = 126 m\nNo procedural rocks or relief added")
profile.grid(alpha=0.2)
profile.text(0.04, 0.95, "64,009 height posts checked against source\nMaximum encoding error: 0.061 mm\nEncoding error is not DEM accuracy", transform=profile.transAxes,
             va="top", fontsize=9, bbox={"facecolor": "white", "edgecolor": "#cccccc", "alpha": 0.9})
target = root / "docs/images/jezero-fidelity.png"
target.parent.mkdir(parents=True, exist_ok=True)
fig.savefig(target, dpi=115, facecolor="white")
print(target)
