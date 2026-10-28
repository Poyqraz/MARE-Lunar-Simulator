"""
The Unreal Editor side of the dataset generator, over Remote Execution and with
Terrain Studio's own senders. Every level-changing call first checks that the
dedicated dataset level is the one open and that Play is not running, so the
user's other levels are never touched.
"""
import contextlib
import inspect
import io
import json
import os
import re
import sys
import time

STATE = "DATASET_STATE "


class UnrealError(RuntimeError):
    pass


class Unreal:
    def __init__(self, studio, level, rover_actor, log=print):
        link = os.path.join(studio, "Terrain_Studio", "unreal_link")
        if link not in sys.path:
            sys.path.insert(0, link)
        import send_masks
        import send_rocks
        import send_sun
        import send_terrain
        import unreal_connection
        self.conn, self.send_terrain, self.send_rocks = unreal_connection, send_terrain, send_rocks
        self.send_masks, self.send_sun = send_masks, send_sun
        self.level, self.rover_actor, self.log = level, rover_actor, log

    # --- plumbing -------------------------------------------------------------
    def run(self, code, action="Dataset"):
        lines = []
        ok = self.conn.run_in_unreal(code, lambda t, level=None: lines.append(str(t)), action, 5.0)
        if not ok or any(line.startswith("[-]") for line in lines):
            raise UnrealError(f"{action} failed:\n" + "\n".join(lines[-10:]))
        return lines

    def _json(self, code, action):
        for line in self.run(code, action):
            if line.startswith(STATE):
                return json.loads(line[len(STATE):])
        raise UnrealError(f"{action}: no answer from Unreal")

    def state(self):
        return self._json(
            "import json, unreal\n"
            "les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)\n"
            "w = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()\n"
            f"print({STATE!r} + json.dumps({{'level': w.get_outermost().get_path_name() if w else None,"
            " 'playing': bool(les.is_in_play_in_editor())}))\n", "Reading the editor state")

    def require_dataset_level(self):
        s = self.state()
        if s["level"] != self.level:
            raise UnrealError(f"Open the dataset level {self.level} in Unreal (the open level is {s['level']}).")
        if s["playing"]:
            raise UnrealError("Stop Play in Unreal first.")

    def _quiet(self, fn, *args, **kwargs):
        """Runs a Terrain Studio sender, capturing what it prints; raises on failure."""
        lines, buf = [], io.StringIO()
        with contextlib.redirect_stdout(buf):
            if "log" in inspect.signature(fn).parameters:
                result = fn(*args, log=lambda t, level=None: lines.append(str(t)), **kwargs)
            else:
                result = fn(*args, **kwargs)
        lines += buf.getvalue().splitlines()
        if result is False or any("[-]" in line for line in lines):
            raise UnrealError(f"{fn.__name__} failed:\n" + "\n".join(lines[-12:]))
        return lines

    # --- the map ----------------------------------------------------------------
    def clear_terrain(self):
        """
        Removes the level's Landscapes, Terrain Studio rock fields and other rovers'
        wheel-track decals (the level may be a copy of another rover's) (dataset level only).
        """
        self.require_dataset_level()
        return self._json(
            "import json, unreal\n"
            "actors = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)\n"
            "gone = []\n"
            "for a in actors.get_all_level_actors():\n"
            "    tags = [str(t) for t in a.tags]\n"
            "    rocks = any(t.startswith('LunarRocks') for t in tags)\n"
            f"    foreign_track = 'WheelTrack' in tags and 'owner={self.rover_actor}' not in tags\n"
            "    if isinstance(a, unreal.LandscapeProxy) or rocks or foreign_track:\n"
            "        gone.append(a.get_actor_label())\n"
            "        actors.destroy_actor(a)\n"
            f"print({STATE!r} + json.dumps(gone))\n", "Removing the previous terrain")

    def build_map(self, meta, models_folder, rock_collision=True):
        """Landscape, rocks and crater mask of one map, then saves the dataset level."""
        self.require_dataset_level()
        removed = self.clear_terrain()
        land, files = meta["landscape"], meta["files"]
        group_dir = os.path.dirname(files["dem"])
        layout = tuple(land["layout"])
        self._quiet(self.send_terrain.send_to_unreal, layout, land["resolution"], land["z_scale"], land["r16"],
                    z_offset=land["z_offset"], output_directory=group_dir, save_level=False)
        self._quiet(self.send_rocks.send_rocks_to_unreal, files["rocks_csv"], models_folder, 1.0,
                    landscape_label=land["label"], landscape_width=land["width"], seed=meta["rock_seed"],
                    save_level=False)
        if not rock_collision:
            self.set_rock_collision(False)
        with open(files["crater_mask_json"]) as f:
            mask = json.load(f)
        self._quiet(self.send_masks.send_crater_mask_to_unreal, files["crater_mask_png"], mask["width"],
                    mask["height"], mask["resolution_m"], landscape_label=land["label"],
                    landscape_width=land["width"], supersample=mask.get("supersample", 1),
                    save_level=False, shadows=True, rover_shadow=True, sun=True, wheel_tracks=True)
        self.save_level()
        return removed

    def configure_streamers(self, options):
        """
        Sets UnrealStereoCam options (e.g. {"bStreamCenterNoGlare": true}) on the rover's
        navcam streamer, the one whose centre camera is NavcamCenter, in the editor (never
        during Play), then saves the dataset level. Returns how many streamers changed.
        """
        if not options:
            return 0
        self.require_dataset_level()
        props = {re.sub(r"(?<!^)(?=[A-Z])", "_", k[1:] if k.startswith("b") and k[1:2].isupper() else k).lower():
                 v for k, v in options.items()}         # bStreamCenterNoGlare -> stream_center_no_glare
        n = self._json(
            "import json, unreal\n"
            "actors = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)\n"
            f"rover = [a for a in actors.get_all_level_actors() if a.get_actor_label() == {self.rover_actor!r}]\n"
            "n = 0\n"
            "for c in (rover[0].get_components_by_class(unreal.UnrealStereoCam) if rover else []):\n"
            "    name = str(c.get_editor_property('center_capture_name')).replace('_', '').lower()\n"
            "    if name != 'navcamcenter':                 # Navcam_Center, NavcamCenter\n"
            "        continue\n"
            f"    for k, v in {props!r}.items():\n"
            "        c.set_editor_property(k, v)\n"
            "    n += 1\n"
            f"print({STATE!r} + json.dumps(n))\n", "Setting the navcam streamer options")
        if not n:
            raise UnrealError(f"No navcam streamer (centre camera NavcamCenter) on {self.rover_actor}")
        self.save_level()
        return n

    def set_rock_collision(self, on):
        """Turns the rock fields' collision on or off (they stay rendered and in the masks)."""
        self.require_dataset_level()
        mode = "QUERY_AND_PHYSICS" if on else "NO_COLLISION"
        return self._json(
            "import json, unreal\n"
            "n = 0\n"
            "for a in unreal.get_editor_subsystem(unreal.EditorActorSubsystem).get_all_level_actors():\n"
            "    if any(str(t).startswith('LunarRocks') for t in a.tags):\n"
            "        for c in a.get_components_by_class(unreal.PrimitiveComponent):\n"
            f"            c.set_collision_enabled(unreal.CollisionEnabled.{mode})\n"
            "            n += 1\n"
            f"print({STATE!r} + json.dumps(n))\n", "Setting the rocks' collision")

    def save_level(self):
        self.require_dataset_level()
        self.run(self.conn.unreal_call("save_current_level()", "unreal_level_saver"), "Saving the dataset level")

    def set_sun(self, azimuth_deg, elevation_deg):
        self.require_dataset_level()
        self._quiet(self.send_sun.send_sun_to_unreal, azimuth_deg, elevation_deg, 120000.0, 0.53, save_level=False)

    def place_rover(self, x_m, y_m, yaw_deg, height_m):
        """Moves the rover actor (in the editor, before Play) above map point (x, y)."""
        self.require_dataset_level()
        X, Y = -100.0 * x_m, 100.0 * y_m
        return self._json(
            "import json, unreal\n"
            "world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()\n"
            "actors = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)\n"
            f"rover = [a for a in actors.get_all_level_actors() if a.get_actor_label() == {self.rover_actor!r}]\n"
            "if not rover:\n"
            f"    print('[-] No actor {self.rover_actor} in the level')\n"
            "else:\n"
            f"    hit = unreal.SystemLibrary.line_trace_single(world, unreal.Vector({X}, {Y}, 1e6), unreal.Vector({X}, {Y}, -1e6),\n"
            "        unreal.TraceTypeQuery.TRACE_TYPE_QUERY1, False, rover, unreal.DrawDebugTrace.NONE, True)\n"
            "    if hit is None:\n"
            "        print('[-] No ground under the spawn point')\n"
            "    else:\n"
            "        z = hit.to_tuple()[4].z\n"
            f"        rover[0].set_actor_location_and_rotation(unreal.Vector({X}, {Y}, z + {100.0 * height_m}),\n"
            f"            unreal.Rotator(0.0, 0.0, {yaw_deg}), False, True)\n"
            f"        print({STATE!r} + json.dumps({{'ground_z_cm': z}}))\n", "Placing the rover")

    # --- Play -------------------------------------------------------------------
    def _play(self, begin):
        call = "editor_request_begin_play" if begin else "editor_request_end_play"
        self.run(f"import unreal\nunreal.get_editor_subsystem(unreal.LevelEditorSubsystem).{call}()\n",
                 "Starting Play" if begin else "Stopping Play")
        for _ in range(30):
            time.sleep(1.0)
            if self.state()["playing"] == begin:
                return
        raise UnrealError("Play did not " + ("start" if begin else "stop"))

    def set_console_variables(self, cvars):
        """Console variables (e.g. rendering settings) for this editor session; not saved anywhere."""
        if not cvars:
            return
        code = ("import unreal\n"
                "w = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()\n"
                + "".join(f"unreal.SystemLibrary.execute_console_command(w, {f'{k} {v}'!r})\n"
                          for k, v in cvars.items()))
        self.run(code, "Setting console variables")

    def play(self, cvars=None):
        """Starts Play, after setting `cvars` (they last for the editor session, so a restarted
        editor gets them again with the next episode)."""
        self.require_dataset_level()
        self.set_console_variables(cvars)
        self._play(True)

    def stop(self):
        if self.state()["playing"]:
            self._play(False)
