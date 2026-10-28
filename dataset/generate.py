"""
generate.py: builds the MARE training dataset, reproducibly, from config.yaml.

    python generate.py maps      # Terrain Studio: terrains, rock fields, crater masks (offline)
    python generate.py plan      # spawns, goals and suns of every episode -> plan.json (offline)
    python generate.py record    # Unreal + GNC: drive and record each episode, extract its samples
    python generate.py status    # what is done
    python generate.py all       # maps, plan, record

Every random choice derives from the config's seed, so the same config gives the
same maps and plan. Each stage resumes where it stopped: finished maps, episodes
and samples are skipped. `record` stops once target_samples samples exist.

`record` needs the Unreal Editor open on the dataset level (a copy of
Lunar_Terrain_Raph, see README.md) with Remote Execution on, not in Play, and
the GNC stack running. It replaces that level's Landscape and rocks for each map
and saves it; no other level is touched.
"""
import argparse
import json
import os
import shutil
import sys
import time
import traceback

import numpy as np
import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import dataset_maps  # noqa: E402


def _abs(path, base=HERE):
    return path if os.path.isabs(path) else os.path.normpath(os.path.join(base, path))


class Run:
    def __init__(self, config_path, output=None):
        with open(config_path) as f:
            self.cfg = yaml.safe_load(f)
        if output:
            self.cfg["output_dir"] = output
        self.out = _abs(self.cfg["output_dir"])
        self.studio = _abs(self.cfg["paths"]["terrain_studio"])
        self.models = _abs(self.cfg["paths"]["rock_models"] or os.path.join(self.studio, "input_rocks"))
        self.maps_dir = os.path.join(self.out, "maps")
        self.bags_dir = os.path.join(self.out, "bags")
        self.episodes_dir = os.path.join(self.out, "episodes")
        self.samples_dir = os.path.join(self.out, "samples")
        for d in (self.maps_dir, self.bags_dir, self.episodes_dir, self.samples_dir):
            os.makedirs(d, exist_ok=True)
        self.state_path = os.path.join(self.out, "state.json")
        with open(os.path.join(self.out, "config_used.yaml"), "w") as f:
            yaml.safe_dump(self.cfg, f, sort_keys=False)

    def log(self, text):
        line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {text}"
        print(line, flush=True)
        with open(os.path.join(self.out, "log.txt"), "a", encoding="utf-8") as f:
            f.write(line + "\n")

    def state(self):
        if os.path.isfile(self.state_path):
            with open(self.state_path) as f:
                return json.load(f)
        return {}

    def save_state(self, **kw):
        s = self.state()
        s.update(kw)
        with open(self.state_path, "w") as f:
            json.dump(s, f, indent=2)

    # --- stage 1: maps ---------------------------------------------------------------
    def map_names(self):
        return [f"map_{i:03d}" for i in range(self.cfg["maps"]["count"])]

    def map_meta(self, name):
        path = os.path.join(self.maps_dir, name, "map.json")
        if not os.path.isfile(path):
            return None
        with open(path) as f:
            return json.load(f)

    def build_maps(self):
        mc = self.cfg["maps"]
        rng = np.random.default_rng(self.cfg["seed"])
        for name in self.map_names():
            # Draw every map's parameters even when it exists, so later maps do not change.
            overrides = {k: float(rng.uniform(lo, hi)) for k, (lo, hi) in mc["vary"].items()}
            terrain_seed = int(rng.integers(1, 2**31 - 1))
            rock_preset = str(rng.choice(mc["rock_presets"]))
            rock_seed = int(rng.integers(1, 2**31 - 1))
            # Drawn after the others, so a config without rock_vary reproduces the same maps.
            rock_overrides = {k: float(rng.uniform(lo, hi)) for k, (lo, hi) in (mc.get("rock_vary") or {}).items()}
            if self.map_meta(name):
                continue
            t0 = time.time()
            for attempt in range(5):        # the rock planner may fail to connect the corridors
                meta = dataset_maps.build_map(self.studio, self.maps_dir, name, mc["size_m"], mc["terrain_preset"],
                                              overrides, terrain_seed, rock_preset, rock_seed + attempt, log=self.log,
                                              rock_overrides=rock_overrides)
                if meta:
                    break
            if not meta:
                raise RuntimeError(f"{name}: no connected rock field in 5 attempts")
            self.log(f"{name}: {meta['craters']} craters, {meta['rocks']} rocks ({rock_preset}), "
                     f"{meta['drivable_pct']}% drivable, {time.time() - t0:.0f} s")

    # --- stage 2: plan ------------------------------------------------------------------
    def plan_path(self):
        return os.path.join(self.out, "plan.json")

    def make_plan(self):
        ec = self.cfg["episodes"]
        plan = []
        for m, name in enumerate(self.map_names()):
            meta = self.map_meta(name)
            if meta is None:
                raise RuntimeError(f"{name} is not built: run `generate.py maps` first")
            points = dataset_maps.corridor_points(meta, ec["edge_margin_m"], ec["max_slope_deg"])
            rng = np.random.default_rng([self.cfg["seed"], m])
            lo, hi = ec["goal_distance_m"]
            # feature_bias > 0 draws spawns and goals near rocks and craters more often, so the
            # cameras, looking ahead at the goal, see more of them: weight exp(bias * z), z the
            # point's score in standard deviations above the map's mean.
            bias = float(ec.get("feature_bias", 0.0))
            weight = None
            if bias > 0:
                score = dataset_maps.feature_score(meta, points, ec.get("feature_radius_m", 15.0))
                weight = np.exp(bias * (score - score.mean()) / max(score.std(), 1e-9))

            def pick(indices, spawn=False):
                if weight is None:                     # the unweighted draws, as before
                    return rng.integers(len(points)) if spawn else rng.choice(indices)
                p = weight[indices] / weight[indices].sum()
                return rng.choice(indices, p=p)

            for e in range(ec["per_map"]):
                spawn = points[pick(np.arange(len(points)), spawn=True)]
                goals, here = [], spawn
                for _ in range(ec["goals"]):
                    d = np.linalg.norm(points - here, axis=1)
                    near = (d >= lo) & (d <= hi)
                    if weight is not None:              # also away from the spawn and earlier goals, so
                        for p in [spawn] + goals:       # the weighting does not shuttle between two spots
                            near &= np.linalg.norm(points - np.asarray(p, float), axis=1) >= lo
                    candidates = np.flatnonzero(near)
                    if not len(candidates):
                        break
                    here = points[pick(candidates)]
                    goals.append([round(float(here[0]), 2), round(float(here[1]), 2)])
                plan.append({
                    "id": f"{name}_ep{e:02d}", "map": name,
                    "spawn": [round(float(spawn[0]), 2), round(float(spawn[1]), 2)],
                    "yaw_deg": round(float(rng.uniform(0, 360)), 1),
                    "goals": goals,
                    "sun": {"azimuth_deg": round(float(rng.uniform(*ec["sun_azimuth_deg"])), 1),
                            "elevation_deg": round(float(rng.uniform(*ec["sun_elevation_deg"])), 1)},
                })
        with open(self.plan_path(), "w") as f:
            json.dump(plan, f, indent=2)
        self.log(f"plan: {len(plan)} episodes on {len(self.map_names())} maps -> {self.plan_path()}")
        return plan

    def plan(self):
        if not os.path.isfile(self.plan_path()):
            return self.make_plan()
        with open(self.plan_path()) as f:
            return json.load(f)

    # --- stage 3: record (and extract) ------------------------------------------------
    def samples_count(self):
        total = 0
        for path in os.listdir(self.samples_dir):
            meta = os.path.join(self.samples_dir, path, "episode.json")
            if os.path.isfile(meta):
                with open(meta) as f:
                    total += json.load(f)["samples"]
        return total

    def recording_order(self, plan):
        """The plan's episodes in recording order: round-robin over the maps (interleaved) or map by map."""
        if self.cfg["episodes"].get("order", "by_map") != "interleaved":
            return plan
        maps = self.map_names()
        index = {}
        keyed = []
        for ep in plan:
            k = index[ep["map"]] = index.get(ep["map"], -1) + 1
            keyed.append(((k, maps.index(ep["map"])), ep))
        return [ep for _, ep in sorted(keyed, key=lambda kv: kv[0])]

    def episode_done(self, ep):
        return os.path.isfile(os.path.join(self.episodes_dir, f"{ep['id']}.json"))

    def record(self):
        import dataset_gnc
        import dataset_unreal
        uc, ec, target = self.cfg["unreal"], self.cfg["episodes"], self.cfg["target_samples"]
        unreal = dataset_unreal.Unreal(self.studio, uc["level"], uc["rover_actor"])
        gnc = dataset_gnc.Gnc(self.cfg["gnc"])
        unreal.require_dataset_level()
        unreal.configure_streamers(uc.get("streamer") or {})
        gnc.require_running()
        gnc.apply_node_params()
        total = self.extract_pending()
        planner_map = None
        for ep in self.recording_order(self.plan()):
            if total >= target:
                break
            if self.episode_done(ep):
                continue
            meta = self.map_meta(ep["map"])
            if self.state().get("unreal_map") != ep["map"]:
                self.log(f"{ep['map']}: building it in Unreal (Landscape, rocks, crater mask)")
                t0 = time.time()
                unreal.stop()
                unreal.build_map(meta, self.models, rock_collision=uc.get("rock_collision", True))
                self.save_state(unreal_map=ep["map"])
                self.log(f"{ep['map']}: built in {time.time() - t0:.0f} s")
            if planner_map != ep["map"]:
                gnc.set_planner_maps(ep["map"], meta["files"]["elevation_csv"], meta["files"]["soil_csv"])
                planner_map = ep["map"]
            gnc.apply_avoidance()                       # also after the planner restarted on a new map
            total += self._episode(ep, unreal, gnc, uc, ec)
            self.log(f"{total} / {target} samples")
        self.log(f"record: {total} samples" + (" (target reached)" if total >= target else ""))

    def _episode(self, ep, unreal, gnc, uc, ec):
        self.log(f"{ep['id']}: sun {ep['sun']['azimuth_deg']} / {ep['sun']['elevation_deg']} deg, "
                 f"spawn {ep['spawn']}, {len(ep['goals'])} goals")
        unreal.stop()
        unreal.set_sun(ep["sun"]["azimuth_deg"], ep["sun"]["elevation_deg"])
        unreal.place_rover(ep["spawn"][0], ep["spawn"][1], ep["yaw_deg"], uc["spawn_height_m"])
        results, proc, bag, t0 = [], None, None, time.time()
        try:
            unreal.play(uc.get("console_variables"))
            gnc.wait_landed(uc["landing_timeout_s"])
            proc, bag = gnc.record_start(ep["id"], ec["max_record_s"])
            for x, y in ep["goals"]:
                budget = ec["max_record_s"] - (time.time() - t0) - 30
                if budget < 30:
                    break
                state, reason, secs = gnc.drive_to(x, y, min(ec["goal_timeout_s"], budget))
                results.append({"goal": [x, y], "state": state, "reason": reason, "seconds": secs})
                self.log(f"  goal {x:.1f}, {y:.1f}: {state} in {secs} s {reason}")
                if state == "aborted" and "tilt" in reason.lower():
                    break
        finally:
            if proc is not None:
                gnc.record_stop(proc)
            unreal.stop()
        gnc.fetch_bag(bag, self.bags_dir)
        record = {**ep, "goal_results": results, "wall_seconds": round(time.time() - t0, 1)}
        with open(os.path.join(self.episodes_dir, f"{ep['id']}.json"), "w") as f:
            json.dump(record, f, indent=2)
        return self._extract(ep["id"])

    # --- extraction --------------------------------------------------------------------
    def _extract(self, ep_id):
        import extract
        bag_dir = os.path.join(self.bags_dir, ep_id)
        out_dir = os.path.join(self.samples_dir, ep_id)
        with open(os.path.join(self.episodes_dir, f"{ep_id}.json")) as f:
            record = json.load(f)
        meta = self.map_meta(record["map"])
        episode_meta = {"episode": ep_id, "map": {k: meta[k] for k in ("name", "terrain_seed", "rock_preset",
                                                                         "rock_seed", "craters", "rocks")},
                        "sun": record["sun"], "spawn": record["spawn"], "goal_results": record["goal_results"]}
        if os.path.isdir(out_dir):
            shutil.rmtree(out_dir)                      # a half-written episode from an interrupted run
        n = extract.extract_episode(bag_dir, out_dir, self.cfg["frames"], episode_meta)
        keep = self.cfg["frames"]["keep_bags"]
        if keep == "no_images":
            extract.strip_images(bag_dir)
        elif not keep:
            shutil.rmtree(bag_dir)
        self.log(f"  {ep_id}: {n} samples")
        return n

    def extract_pending(self):
        """Extracts recorded episodes whose samples are missing (e.g. after an interruption)."""
        for name in sorted(os.listdir(self.episodes_dir)):
            ep_id = name[:-5]
            done = os.path.isfile(os.path.join(self.samples_dir, ep_id, "episode.json"))
            if not done and os.path.isdir(os.path.join(self.bags_dir, ep_id)):
                self._extract(ep_id)
        return self.samples_count()

    def status(self):
        built = [n for n in self.map_names() if self.map_meta(n)]
        plan = self.plan() if os.path.isfile(self.plan_path()) else []
        done = [ep for ep in plan if self.episode_done(ep)]
        print(f"maps built: {len(built)} / {len(self.map_names())}")
        print(f"episodes recorded: {len(done)} / {len(plan)}")
        print(f"samples: {self.samples_count()} / {self.cfg['target_samples']}  ({self.samples_dir})")
        print(f"map in the Unreal level: {self.state().get('unreal_map')}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("stage", choices=["maps", "plan", "record", "status", "all"])
    parser.add_argument("--config", default=os.path.join(HERE, "config.yaml"))
    parser.add_argument("--output", help="output folder (overrides the config's output_dir)")
    args = parser.parse_args()
    run = Run(args.config, args.output)
    try:
        if args.stage in ("maps", "all"):
            run.build_maps()
        if args.stage in ("plan", "all"):
            run.plan()
        if args.stage in ("record", "all"):
            run.record()
        if args.stage == "status":
            run.status()
    except Exception:
        run.log("stopped with an error:\n" + traceback.format_exc())
        sys.exit(1)


if __name__ == "__main__":
    main()
