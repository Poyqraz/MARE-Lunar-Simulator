"""Bounded mission history from observed simulation poses, independent of views.

The owner (NavigationSession) serializes mutations. Records are memory-only;
export is explicit, not a crash-durable journal or an exact continuous odometer.
"""

from collections import deque
import copy
import math
import uuid


class MissionHistory:
    def __init__(self, manifest_sha256, *, max_points=4096, max_missions=8, max_events=256, max_plans=16):
        values = (max_points, max_missions, max_events, max_plans)
        if any(type(v) is not int or not 2 <= v <= 100_000 for v in values):
            raise ValueError("History limits must be integers in 2..100000")
        self.manifest_sha256 = manifest_sha256
        self.max_points, self.max_missions, self.max_events, self.max_plans = values
        self.session_id = str(uuid.uuid4())
        self.records = deque(maxlen=max_missions)
        self.points = deque(maxlen=max_points)
        self.events = deque(maxlen=max_events)
        self.current = None
        self.latest = self.previous_pose = None
        self.speed_estimate = None
        self.seq = self.event_seq = self.revision = self.goal_revision = 0
        self.missions_evicted = self.points_evicted = self.events_evicted = 0
        self.pending_break = True
        self.last_sample_ns = None

    @property
    def active(self):
        return self.current is not None and not self.current["closed"]

    def _event(self, kind, **fields):
        self.event_seq += 1
        self.revision += 1
        self.events_evicted += int(len(self.events) == self.max_events)
        self.events.append(
            {
                "seq": self.event_seq,
                "kind": kind,
                "session_id": self.session_id,
                "mission_id": self.current["mission_id"] if self.current else None,
                "stamp_ns": self.latest["stamp_ns"] if self.latest else None,
                **fields,
            }
        )

    def begin(self, goal):
        self.finish("superseded")
        self.goal_revision += 1
        self.missions_evicted += int(len(self.records) == self.max_missions)
        self.current = {
            "mission_id": str(uuid.uuid4()),
            "session_id": self.session_id,
            "goal_revision": self.goal_revision,
            "goal": tuple(map(float, goal)),
            "start_pose": None,
            "end_pose": None,
            "status": "pending",
            "closed": False,
            "error": None,
            "travelled_xy_m": 0.0,
            "distance_complete": True,
            "initial_plan": (),
            "active_plan": (),
            "plan_revision": 0,
            "progress_index": 0,
            "remaining_route_m": None,
            "trail": deque(maxlen=self.max_points),
            "plans": deque(maxlen=self.max_plans),
            "trail_evicted": 0,
            "plans_evicted": 0,
        }
        self.records.append(self.current)
        self._event("goal_accepted", goal=self.current["goal"])

    def new_session(self, reason):
        self.finish(reason)
        self._event("session_ended", reason=reason)
        self.session_id = str(uuid.uuid4())
        self.current = None
        self.latest = self.previous_pose = None
        self.speed_estimate = None
        self.points.clear()
        self.points_evicted = 0
        self.pending_break, self.last_sample_ns = True, None
        self._event("session_started", reason=reason)

    @staticmethod
    def _point(pose):
        return {
            "stamp_ns": str(pose.stamp_ns),
            "position_m": tuple(map(float, pose.matrix[:3, 3])),
            "heading_rad": pose.xy_heading[2],
        }

    def observe(self, pose):
        previous = self.previous_pose
        if previous and pose.stamp_ns <= previous.stamp_ns:
            if pose.stamp_ns == previous.stamp_ns:
                return  # Repeated status polling is not another observation.
            raise ValueError("Reset the mission session before a backwards simulation clock")
        dt = (pose.stamp_ns - previous.stamp_ns) / 1e9 if previous else None
        gap = dt is not None and dt > 0.25
        distance = math.dist(pose.xy_heading[:2], previous.xy_heading[:2]) if previous else 0.0
        self.speed_estimate = distance / dt if dt and not gap else None
        self.latest, self.previous_pose = self._point(pose), pose
        self.revision += 1
        first = self.active and self.current["start_pose"] is None
        if first:
            self.current["start_pose"] = self.latest
        elif self.active:
            if gap:
                self.current["distance_complete"] = False
            else:
                self.current["travelled_xy_m"] += distance
        if gap:
            self.pending_break = True
            self._event("pose_gap", gap_s=dt)
        if first or self.last_sample_ns is None or pose.stamp_ns - self.last_sample_ns >= 200_000_000:
            self._sample()

    def _sample(self):
        if self.latest is None or (self.points and self.points[-1]["stamp_ns"] == self.latest["stamp_ns"]):
            return
        self.seq += 1
        point = {**self.latest, "seq": self.seq, "break_before": self.pending_break}
        self.points_evicted += int(len(self.points) == self.max_points)
        self.points.append(point)
        if self.active:
            r = self.current
            r["trail_evicted"] += int(len(r["trail"]) == self.max_points)
            r["trail"].append({**point, "break_before": point["break_before"] or not r["trail"]})
        self.pending_break = False
        self.last_sample_ns = int(point["stamp_ns"])

    def finish(self, status, error=None):
        if not self.active:
            return
        started = self.current["start_pose"] is not None
        if started:
            self._sample()  # Retain an observed endpoint even between 5 Hz samples.
        self.current.update(status=status, error=error, closed=True, end_pose=self.latest if started else None)
        if status in ("new_connection", "disconnected", "clock_reset", "teleport"):
            self.current["distance_complete"] = False
        if status == "arrived":
            self.current["remaining_route_m"] = 0.0
        self._event("mission_finished", status=status, error=error)

    def state(self, status, error=None):
        if not self.active:
            return
        if status in ("arrived", "blocked", "stalled_or_timed_out"):
            self.finish(status, error)
        elif self.current["status"] != status or self.current["error"] != error:
            self.current.update(status=status, error=error)
            self._event("state_changed", status=status, error=error)

    def plan(self, route, map_revision):
        if not self.active:
            return
        r = self.current
        route = tuple(tuple(map(float, p)) for p in route)
        if not r["plan_revision"]:
            r["initial_plan"] = route
        r["active_plan"] = route
        r["plan_revision"] += 1
        r["plans_evicted"] += int(len(r["plans"]) == self.max_plans)
        r["plans"].append(
            {
                "revision": r["plan_revision"],
                "map_revision": map_revision,
                "stamp_ns": self.latest["stamp_ns"] if self.latest else None,
                "route": route,
            }
        )
        self._event("plan_created", plan_revision=r["plan_revision"], map_revision=map_revision)

    def progress(self, index, xy):
        if self.active and self.current["active_plan"]:
            r = self.current
            index = min(max(0, index), len(r["active_plan"]) - 1)
            rest = (tuple(xy), *r["active_plan"][index:])
            r["progress_index"] = index
            r["remaining_route_m"] = sum(math.dist(a, b) for a, b in zip(rest, rest[1:]))

    def summary(self):
        if not self.current:
            return None
        return copy.deepcopy({k: v for k, v in self.current.items() if k not in ("trail", "plans")})

    def trail(self, *, after_seq=0, mission_id=None):
        points, evicted = self.points, self.points_evicted
        session_id = self.session_id
        if mission_id is not None:
            r = next((r for r in self.records if r["mission_id"] == mission_id), None)
            if r is None:
                raise KeyError("Mission is not retained")
            points, evicted = r["trail"], r["trail_evicted"]
            session_id = r["session_id"]
        values = [dict(p) for p in points if p["seq"] > after_seq]
        truncated = bool(evicted and points and after_seq < points[0]["seq"] - 1)
        if values and (truncated or after_seq == 0):
            values[0]["break_before"] = True
        return copy.deepcopy(
            {
                "session_id": session_id,
                "mission_id": mission_id,
                "points": values,
                "truncated": truncated,
                "next_seq": points[-1]["seq"] if points else after_seq,
            }
        )

    def event_page(self, *, after_seq=0):
        return copy.deepcopy(
            {
                "events": [e for e in self.events if e["seq"] > after_seq],
                "session_id": self.session_id,
                "truncated": bool(self.events_evicted and self.events and after_seq < self.events[0]["seq"] - 1),
                "next_seq": self.event_seq,
            }
        )

    def capture_export(self):
        # Lists/dicts that mutate are copied here; point/event/route payloads
        # are immutable after creation. Encoding/deep copying can run unlocked.
        def points(values, evicted):
            result = list(values)
            if result and evicted:
                result[0] = {**result[0], "break_before": True}
            return result

        records = [
            {**r, "trail": points(r["trail"], r["trail_evicted"]), "plans": list(r["plans"])} for r in self.records
        ]
        return {
            "schema_version": 1,
            "session_id": self.session_id,
            "terrain_manifest_sha256": self.manifest_sha256,
            "storage": "bounded memory; explicit export",
            "distance_source": "sampled simulation telemetry XY chords; gaps omitted",
            "missions": records,
            "session_trail": points(self.points, self.points_evicted),
            "events": list(self.events),
            "limits": {
                "max_points": self.max_points,
                "max_missions": self.max_missions,
                "max_events": self.max_events,
                "max_plans": self.max_plans,
                "missions_evicted": self.missions_evicted,
                "session_points_evicted": self.points_evicted,
                "events_evicted": self.events_evicted,
            },
            "native_rover_verified": False,
        }

    def export(self):
        return copy.deepcopy(self.capture_export())
