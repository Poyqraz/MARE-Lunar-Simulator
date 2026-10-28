"""
align_labels.py: the central camera's labels on the SPAD and event camera grids.

    python align_labels.py <dataset folder> [...]     # every episode under <folder>/samples

On Leo_Raph the SPAD (256 x 256) and the event camera (346 x 260) sit at the
central navcam's position and orientation, with the same 90 degree horizontal
field of view; only their resolution differs. A pixel of theirs therefore looks
along the same ray as the central pixel at the same angle, and the object ids,
shadow ids and depth of the central camera map onto their grid exactly
(nearest pixel; depth is planar along the shared optical axis). The SPAD sees
higher and lower than the central camera (90 x 90 degrees against 90 x 74):
those rows get NO_LABEL (255) and NaN depth.

Per episode, for each sample that has a SPAD or event image:
    spad_object/, spad_shadow/  uint8 ids on the SPAD grid (255 = outside the central camera)
    spad_depth_m/               float32 metres (.npy; inf = sky, NaN = outside)
    events_object/, events_shadow/, events_depth_m/   the same on the event camera grid
    preview/spad_object/, preview/events_object/       class colours, for viewing

The labels are those of the central frame; the SPAD and event images are paired
with it within pair_tolerance_s (their stamps are in frames.csv).
"""
import argparse
import json
import math
import os

import numpy as np
from PIL import Image

NO_LABEL = 255
CENTRAL_HFOV_DEG = 90.0
CAMERAS = {"spad": (256, 256), "events": (346, 260)}      # width, height; same pose and hfov as the central


def pixel_map(size, central_size, hfov_deg=CENTRAL_HFOV_DEG):
    """For each pixel of a camera of `size` (w, h): the central pixel (rows, cols) it looks at, and
    whether that pixel exists (pinhole cameras with one optical centre, axis and horizontal FOV)."""
    w, h = size
    cw, ch = central_size
    f = (w / 2) / math.tan(math.radians(hfov_deg) / 2)
    cf = (cw / 2) / math.tan(math.radians(hfov_deg) / 2)
    u = (np.arange(w) + 0.5 - w / 2) / f * cf + cw / 2      # pixel centres, central pixel coordinates
    v = (np.arange(h) + 0.5 - h / 2) / f * cf + ch / 2
    cols, rows = np.meshgrid(np.floor(u).astype(int), np.floor(v).astype(int))
    inside = (cols >= 0) & (cols < cw) & (rows >= 0) & (rows < ch)
    return np.clip(rows, 0, ch - 1), np.clip(cols, 0, cw - 1), inside


def _palette(classes):
    lut = np.zeros((256, 3), np.uint8)
    for c in classes:
        lut[c["id"]] = c["rgb"]
    lut[NO_LABEL] = (60, 60, 60)
    return lut


def align_episode(ep_dir, previews=True):
    """Writes the aligned labels of one episode folder. Returns {camera: frames written}."""
    meta_path = os.path.join(ep_dir, "episode.json")
    with open(meta_path) as f:
        meta = json.load(f)
    central = meta.get("camera_info", {}).get("central")
    if central is None:
        return {}
    central_size = (central["width"], central["height"])
    lut = _palette(meta.get("object_classes", []))
    done = {}
    for cam, size in CAMERAS.items():
        src = os.path.join(ep_dir, cam)
        if not os.path.isdir(src):
            continue
        rows, cols, inside = pixel_map(size, central_size)
        outs = [f"{cam}_object", f"{cam}_shadow", f"{cam}_depth_m"] + ([f"preview/{cam}_object"] if previews else [])
        for o in outs:
            os.makedirs(os.path.join(ep_dir, o), exist_ok=True)
        n = 0
        for name in sorted(os.listdir(src)):
            stem = name.rsplit(".", 1)[0]
            img = Image.open(os.path.join(src, name))
            if img.size != size:
                raise ValueError(f"{src}/{name} is {img.size}, expected {size}")
            obj = np.asarray(Image.open(os.path.join(ep_dir, "object", stem + ".png")))
            sh = np.asarray(Image.open(os.path.join(ep_dir, "shadow", stem + ".png")))
            o = np.where(inside, obj[rows, cols], NO_LABEL).astype(np.uint8)
            s = np.where(inside, sh[rows, cols], NO_LABEL).astype(np.uint8)
            Image.fromarray(o).save(os.path.join(ep_dir, f"{cam}_object", stem + ".png"))
            Image.fromarray(s).save(os.path.join(ep_dir, f"{cam}_shadow", stem + ".png"))
            depth_path = os.path.join(ep_dir, "depth_m", stem + ".npy")
            if os.path.isfile(depth_path):
                d = np.load(depth_path)
            else:                                       # only the millimetre PNG: 0 = none
                mm = np.asarray(Image.open(os.path.join(ep_dir, "depth", stem + ".png"))).astype(np.float32)
                d = np.where(mm > 0, mm / 1000.0, np.inf).astype(np.float32)
            np.save(os.path.join(ep_dir, f"{cam}_depth_m", stem + ".npy"),
                    np.where(inside, d[rows, cols], np.nan).astype(np.float32))
            if previews:
                Image.fromarray(lut[o]).save(os.path.join(ep_dir, "preview", f"{cam}_object", stem + ".png"))
            n += 1
        done[cam] = n
    meta["aligned_labels"] = {cam: {"width": CAMERAS[cam][0], "height": CAMERAS[cam][1],
                                    "hfov_deg": CENTRAL_HFOV_DEG, "no_label": NO_LABEL}
                              for cam in done}
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)
    return done


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("datasets", nargs="+", help="dataset folders (with samples/)")
    parser.add_argument("--no-previews", action="store_true")
    args = parser.parse_args()
    for root in args.datasets:
        samples = os.path.join(root, "samples")
        for ep in sorted(os.listdir(samples)):
            done = align_episode(os.path.join(samples, ep), previews=not args.no_previews)
            print(f"{ep}: {done}")


if __name__ == "__main__":
    main()
