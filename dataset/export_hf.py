"""
export_hf.py: packs a generated dataset for the Hugging Face Hub (WebDataset shards).

    python export_hf.py <dataset folder> <export folder> [--shard-gb 1.0]

Writes, under <export folder>:
    data/{train,validation,test}/shard-00000.tar ...   one sample per key: its files + <key>.json
    episodes/<episode>.json, episodes/<episode>_frames.csv
    maps/<map>/                  DEM (.npy), craters and rocks (.csv), crater mask, map.json
    bags/<episode>.mcap          each episode's rosbag without images or lidar scans
    classes.json                 object and shadow class legends
Splits are by map (no terrain in two splits): see SPLITS. The preview/ folders
are left out (for viewing on disk; the Hub's viewer shows the images). Nothing is
uploaded: the folder is pushed with `huggingface-cli upload` (see the card).
"""
import argparse
import csv
import glob
import io
import json
import os
import shutil
import tarfile

SPLITS = {"train": ["map_000", "map_001", "map_002", "map_003", "map_004", "map_005"],
          "validation": ["map_006"], "test": ["map_007"]}
# Per-sample files: <folder> -> name inside the sample (extension kept)
FOLDERS = ["rgb_central", "rgb_left", "rgb_right", "rgb_central_noglare", "rear_rgb",
           "depth", "depth_m", "object", "shadow", "rear_object", "rear_shadow",
           "events", "spad", "lidar", "lidar_depth", "lidar_depth_m",
           "spad_object", "spad_shadow", "spad_depth_m", "events_object", "events_shadow", "events_depth_m"]
FIRST_COMPLETE = 10       # complete samples opening each split (the Hub's loader reads 5 to infer columns)
MAP_FILES = ("_elevationMap.npy", "_craters.csv", "_rocks.csv", "_craterMask.png", "_craterMask.json",
             "_roverPaths.csv", "_soilMap.csv")


def split_of(map_name):
    return next(s for s, maps in SPLITS.items() if map_name in maps)


class ShardWriter:
    def __init__(self, folder, max_bytes):
        self.folder, self.max_bytes, self.index, self.size, self.tar = folder, max_bytes, 0, 0, None
        self.count = 0
        os.makedirs(folder, exist_ok=True)

    def _open(self):
        self.tar = tarfile.open(os.path.join(self.folder, f"shard-{self.index:05d}.tar"), "w")
        self.size = 0

    def add(self, key, files):
        """files: {name: (path or bytes)}; one sample, kept in one shard."""
        if self.tar is None:
            self._open()
        elif self.size >= self.max_bytes:
            self.tar.close()
            self.index += 1
            self._open()
        for name, src in files.items():
            arc = f"{key}.{name}"
            if isinstance(src, bytes):
                info = tarfile.TarInfo(arc)
                info.size = len(src)
                info.mtime = 0
                self.tar.addfile(info, io.BytesIO(src))
                self.size += len(src)
            else:
                info = self.tar.gettarinfo(src, arc)
                info.mtime, info.uid, info.gid, info.uname, info.gname = 0, 0, 0, "", ""
                with open(src, "rb") as f:
                    self.tar.addfile(info, f)
                self.size += info.size
        self.count += 1

    def close(self):
        if self.tar is not None:
            self.tar.close()


def export(src, dst, shard_gb):
    samples_dir = os.path.join(src, "samples")
    episodes = sorted(os.listdir(samples_dir))
    writers = {s: ShardWriter(os.path.join(dst, "data", s), int(shard_gb * 1e9)) for s in SPLITS}
    os.makedirs(os.path.join(dst, "episodes"), exist_ok=True)
    os.makedirs(os.path.join(dst, "bags"), exist_ok=True)
    legends = None
    for ep in episodes:
        d = os.path.join(samples_dir, ep)
        meta = json.load(open(os.path.join(d, "episode.json")))
        map_name = meta["map"]["name"]
        split = split_of(map_name)
        legends = legends or {"object_classes": meta["object_classes"], "shadow_classes": meta["shadow_classes"]}
        meta["split"] = split
        with open(os.path.join(dst, "episodes", f"{ep}.json"), "w") as f:
            json.dump(meta, f, indent=2)
        shutil.copy(os.path.join(d, "frames.csv"), os.path.join(dst, "episodes", f"{ep}_frames.csv"))
        for bag in glob.glob(os.path.join(src, "bags", ep, "*_no_images.mcap")):
            shutil.copy(bag, os.path.join(dst, "bags", f"{ep}.mcap"))
        present = [f for f in FOLDERS if os.path.isdir(os.path.join(d, f))]
        samples = []
        for row in csv.DictReader(open(os.path.join(d, "frames.csv"))):
            stem = f"{int(row['frame']):06d}"
            files = {}
            for folder in present:
                for ext in (".png", ".npy"):
                    p = os.path.join(d, folder, stem + ext)
                    if os.path.isfile(p):
                        files[folder + ext] = p
            samples.append((row, files))
        if writers[split].count == 0:
            # The Hub's loader infers the columns from a split's first 5 samples and needs
            # them all to have every file (later samples may miss a sensor: None). So the
            # split opens with complete samples; the rest keep their order.
            complete = [i for i, (_, files) in enumerate(samples) if len(files) == len(present)][:FIRST_COMPLETE]
            if len(complete) < FIRST_COMPLETE:
                raise RuntimeError(f"{ep}: only {len(complete)} samples with every file to open the {split} split")
            samples = [samples[i] for i in complete] + [s for i, s in enumerate(samples) if i not in complete]
        for row, files in samples:
            k = int(row["frame"])
            stem = f"{k:06d}"
            info = {"episode": ep, "frame": k, "map": map_name, "split": split,
                    "stamp": float(row["stamp"]),
                    "pose": {key: float(row[key]) for key in ("x", "y", "z", "qx", "qy", "qz", "qw")},
                    "sun": meta["sun"],
                    "stamps": {key[:-6]: (float(v) if v else None) for key, v in row.items() if key.endswith("_stamp")},
                    "files": sorted(files)}
            files["json"] = json.dumps(info).encode()
            writers[split].add(f"{ep}_{stem}", files)
        print(f"{ep}: {split}", flush=True)
    for w in writers.values():
        w.close()

    with open(os.path.join(dst, "classes.json"), "w") as f:
        json.dump(legends, f, indent=2)
    for map_dir in sorted(glob.glob(os.path.join(src, "maps", "map_*"))):
        name = os.path.basename(map_dir)
        out = os.path.join(dst, "maps", name)
        os.makedirs(out, exist_ok=True)
        for suffix in MAP_FILES:
            p = os.path.join(map_dir, name + suffix)
            if os.path.isfile(p):
                shutil.copy(p, out)
        m = json.load(open(os.path.join(map_dir, "map.json")))
        m["files"] = {k: os.path.basename(v) for k, v in m["files"].items()}   # no local paths
        m["landscape"].pop("r16", None)
        m["split"] = split_of(name)
        with open(os.path.join(out, "map.json"), "w") as f:
            json.dump(m, f, indent=2)
    counts = {s: w.count for s, w in writers.items()}
    shards = {s: w.index + 1 if w.count else 0 for s, w in writers.items()}
    with open(os.path.join(dst, "export_summary.json"), "w") as f:
        json.dump({"samples": counts, "shards": shards, "splits": SPLITS}, f, indent=2)
    return counts, shards


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("src")
    parser.add_argument("dst")
    parser.add_argument("--shard-gb", type=float, default=1.0)
    args = parser.parse_args()
    print(export(args.src, args.dst, args.shard_gb))


if __name__ == "__main__":
    main()
