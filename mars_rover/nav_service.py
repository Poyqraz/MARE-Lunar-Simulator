"""Run a ROS-free simulated Mars mission with MARE's existing TCP sensors.

    python -m mars_rover.nav_service --sensors Saved/Mars/rover-sensors.json --goal 200 100

Start before Play. Owns motor 3003, camera 3004, LiDAR 3007, motor HTTP 8765
and navigation HTTP 8766 on localhost. Stop conflicting GNC services first.
"""

import argparse
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import socket
import threading
import time
from urllib.parse import parse_qs, urlsplit

import numpy as np

from .bridge import BridgeServer, TELEMETRY_FORMATS, TR_TELEMETRY_NOTICE
from .dashboard_bridge import LiveFeeds, ViewportLink, local_depth_view, project_route
from .drive import Calibration
from .navigation import LATE_DATA_ERROR, NavigationSession
from .planning import TerrainMap
from .sensors import LidarStream, NavStream


class PacketListener:
    """Bounded TCP connections, fragmented packets and promptly invalidated health."""

    def __init__(self, port, decoder, on_packet, on_error):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self.socket.bind(("127.0.0.1", port))
            self.socket.listen(8)
        except BaseException:
            self.socket.close()
            raise
        self.port = self.socket.getsockname()[1]
        self.socket.settimeout(0.1)
        self.decoder, self.on_packet, self.on_error = decoder, on_packet, on_error
        self.ending = threading.Event()
        self.slots = threading.BoundedSemaphore(8)
        self.peers = set()
        self.lock = threading.Lock()
        self.thread = None
        self.workers = []

    def start(self):
        self.thread = threading.Thread(target=self._accept, daemon=True)
        self.thread.start()

    def _accept(self):
        while not self.ending.is_set():
            try:
                peer, _ = self.socket.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            if not self.slots.acquire(blocking=False):
                peer.close()
                continue
            with self.lock:
                self.peers.add(peer)
            worker = threading.Thread(target=self._read, args=(peer,), daemon=True)
            self.workers = [t for t in self.workers if t.is_alive()]
            self.workers.append(worker)
            worker.start()

    def _read(self, peer):
        decoder = self.decoder()
        try:
            with peer:
                peer.settimeout(0.2)
                while not self.ending.is_set():
                    try:
                        chunk = peer.recv(65536)
                    except socket.timeout:
                        continue
                    if not chunk:
                        break
                    for packet in decoder.feed(chunk):
                        self.on_packet(packet)
        except (OSError, ValueError, RuntimeError) as error:
            self.on_error(str(error))
        finally:
            with self.lock:
                self.peers.discard(peer)
            self.on_error("Sensor connection closed")
            self.slots.release()

    def close(self):
        self.ending.set()
        self.socket.close()
        with self.lock:
            for peer in self.peers:
                try:
                    peer.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
        if self.thread:
            self.thread.join(timeout=1)
        for worker in self.workers:
            worker.join(timeout=1)


class NavigationService:
    def __init__(
        self,
        grid,
        config,
        *,
        tcp_port=3003,
        bridge_http_port=8765,
        http_port=8766,
        lidar_port=3007,
        camera_port=3004,
        min_points=20,
        depth_source="ground_truth",
        settle_s=2.0,
        telemetry_format="json",
        obstacle_diagnostics=False,
    ):
        self.session = NavigationSession(
            grid, config, min_points=min_points, depth_source=depth_source, settle_s=settle_s,
            obstacle_diagnostics=obstacle_diagnostics,
        )
        self.feeds = LiveFeeds(config)
        self.viewport = ViewportLink()
        self.ending = threading.Event()
        self.last_transport_error = None
        self.threads = []
        self._timing_lock = threading.Lock()
        self._timing = {"cycles": 0, "last_cycle_s": None, "max_cycle_s": 0.0,
                        "cycles_over_50ms": 0, "cycles_over_250ms": 0, "expired_decisions": 0}
        self._lidar_timing_lock = threading.Lock()
        self._lidar_timing_samples = deque(maxlen=16)
        self._lidar_timing_evicted = 0
        self._lidar_timing_error = None
        self.bridge = BridgeServer(
            Calibration(), tcp_port=tcp_port, http_port=bridge_http_port, on_external_command=self.session.stop,
            telemetry_format=telemetry_format,
        )
        self.lidar, self.camera, self.http = None, None, None
        try:
            self.lidar = PacketListener(
                lidar_port, LidarStream, self._lidar_received, lambda error: self._sensor_error("lidar", error)
            )
            self.camera = PacketListener(
                camera_port,
                NavStream,
                self._camera_received,
                lambda error: self._sensor_error(self.session.depth_source, error),
            )
            self.http = ThreadingHTTPServer(("127.0.0.1", http_port), self._handler())
        except BaseException:
            self.close()
            raise

    def _camera_received(self, frame):
        self.session.feed_camera(frame)
        self.feeds.camera(frame)

    def _lidar_received(self, scan):
        if self.session.obstacle_diagnostics and scan.sensor_id == self.session.config["lidar"]["sensor_id"]:
            received = time.monotonic()
            before, before_age, before_connected, before_id, before_error = self._safe_pose_reference()
            started = time.monotonic()
            self.session.feed_lidar(scan, now=received)
            finished = time.monotonic()
            try:
                after, after_age, after_connected, after_id, after_error = self._safe_pose_reference()
                sample = {
                    "frame_id": int(scan.frame_id), "lidar_stamp_ns": str(scan.stamp_ns),
                    "pose_before_stamp_ns": str(before) if before is not None else None,
                    "pose_after_stamp_ns": str(after) if after is not None else None,
                    "pose_before_age_s": before_age, "pose_after_age_s": after_age,
                    "pose_before_connected": before_connected, "pose_after_connected": after_connected,
                    "connection_id_before": before_id, "connection_id_after": after_id,
                    "pose_before_error": before_error, "pose_after_error": after_error,
                    "capture_lag_before_s": (before - scan.stamp_ns) / 1e9 if before is not None else None,
                    "capture_lag_after_s": (after - scan.stamp_ns) / 1e9 if after is not None else None,
                    "pose_reference_s": max(0.0, started - received),
                    "session_feed_s": max(0.0, finished - started),
                }
                with self._lidar_timing_lock:
                    self._lidar_timing_evicted += int(len(self._lidar_timing_samples) == self._lidar_timing_samples.maxlen)
                    self._lidar_timing_samples.append(sample)
            except Exception as error:  # The diagnostic is not a sensor gate.
                self._lidar_timing_error = str(error)[:256]
        else:
            self.session.feed_lidar(scan)
        self.feeds.lidar(scan)

    def _pose_reference(self):
        """Sample the bridge's last telemetry without changing the motor watchdog."""
        with self.bridge.state.lock:
            telemetry = self.bridge.telemetry or {}
            received_at = self.bridge.telemetry_received_at
            connected = bool(self.bridge.state.connected)
            connection_id = self.bridge.connection_id
            now = time.monotonic()
        raw = telemetry.get("t_ns")
        if type(raw) is int:
            stamp = raw
        elif isinstance(raw, str) and raw.isascii() and raw.isdigit() and len(raw) <= 19:
            stamp = int(raw)
        else:
            stamp = None
        if stamp is not None and not 0 < stamp <= 2**63 - 1:
            stamp = None
        age = max(0.0, now - received_at) if received_at is not None else None
        return stamp, age, connected, connection_id

    def _safe_pose_reference(self):
        try:
            return (*self._pose_reference(), None)
        except Exception as error:  # Recording diagnostics must not discard a scan.
            return None, None, None, None, str(error)[:256]

    def lidar_ingest_timing(self):
        with self._lidar_timing_lock:
            return {"max_samples": self._lidar_timing_samples.maxlen,
                    "samples_evicted": self._lidar_timing_evicted,
                    "collection_error": self._lidar_timing_error, "samples": list(self._lidar_timing_samples)}

    def _sensor_error(self, key, error):
        with self.session.lock:
            self.last_transport_error = str(error)
            self.session.health.pop(key, None)
            self.bridge.state.stop()
            if key == "lidar":
                self.feeds.clear_lidar()
            else:
                self.feeds.clear_camera()

    def control_timing(self):
        """Read-only, process-lifetime wall-clock control-loop counters."""
        with self._timing_lock:
            return self._timing.copy()

    def _record_control_timing(self, duration, expired):
        with self._timing_lock:
            self._timing["cycles"] += 1
            self._timing["last_cycle_s"] = duration
            self._timing["max_cycle_s"] = max(self._timing["max_cycle_s"], duration)
            self._timing["cycles_over_50ms"] += int(duration > 0.05)
            self._timing["cycles_over_250ms"] += int(duration > 0.25)
            self._timing["expired_decisions"] += int(expired)

    def _handler(self):
        service = self

        class Handler(BaseHTTPRequestHandler):
            def setup(self):
                super().setup()
                self.connection.settimeout(2)

            def log_message(self, *args):
                pass

            def send_payload(self, code, payload, content_type, *, stamp=None, no_store=False):
                try:
                    self.send_response(code)
                    self.send_header("Content-Type", content_type)
                    self.send_header("Content-Length", str(len(payload)))
                    if no_store:
                        self.send_header("Cache-Control", "no-store")
                    if stamp is not None:
                        self.send_header("X-Capture-Stamp-Ns", stamp)
                    self.end_headers()
                    self.wfile.write(payload)
                except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
                    # A client can leave while a reply is being prepared. This
                    # only ends its HTTP response; it must not affect a mission.
                    self.close_connection = True

            def reply(self, code, value):
                payload = json.dumps(value, allow_nan=False).encode()
                return self.send_payload(code, payload, "application/json")

            def do_GET(self):
                parsed = urlsplit(self.path)
                if parsed.path == "/viewport_camera":
                    try:
                        if len(self.path) > 1024:
                            raise ValueError("Viewport query too large")
                        query = parse_qs(parsed.query, keep_blank_values=True, strict_parsing=True)
                        if set(query) != {"applied", "rover"} or any(len(v) != 1 for v in query.values()):
                            raise ValueError("Expected applied and rover fields")
                        return self.reply(200, service.viewport.update_editor(query["applied"][0], query["rover"][0]))
                    except ValueError as error:
                        return self.reply(400, {"error": str(error)})
                if self.path == "/dashboard/viewport":
                    return self.reply(200, service.viewport.status())
                if self.path == "/dashboard":
                    return self.file_reply(Path(__file__).with_name("dashboard_assets") / "index.html",
                                           "text/html; charset=utf-8")
                if parsed.path.startswith("/dashboard-assets/"):
                    name = parsed.path.removeprefix("/dashboard-assets/")
                    allowed = {"mars-adapter.js", "theme.js", "base.css", "alerts.js", "local_dem.js",
                               "feed_legends.js", "nav_overlay.js", "dash_common.js", "lidar_view.js",
                               "three-r128.min.js"}
                    if name not in allowed or parsed.query:
                        return self.reply(404, {"error": "Unknown dashboard asset"})
                    mime = "text/css; charset=utf-8" if name.endswith(".css") else "text/javascript; charset=utf-8"
                    return self.file_reply(Path(__file__).with_name("dashboard_assets") / name, mime)
                if self.path == "/dashboard/map":
                    grid = service.session.grid
                    if grid.heights.size > 2_000_000:
                        return self.reply(413, {"error": "Dashboard map exceeds the display budget"})
                    values = np.where(np.isfinite(grid.heights) & (grid.heights < 9999), grid.heights, 9999)
                    return self.reply(200, {"width": int(values.shape[1]), "height": int(values.shape[0]),
                                            "resolution": grid.resolution_m, "data": values.ravel().tolist()})
                if self.path == "/dashboard/feeds":
                    return self.reply(200, service.feeds.status())
                if self.path == "/dashboard/lidar":
                    scan = service.feeds.lidar_view()
                    return self.reply(200, scan) if scan else self.reply(404, {"error": "No fresh LiDAR scan"})
                if parsed.path in ("/dashboard/path-overlay", "/dashboard/local-dem"):
                    name = "cam_central" if parsed.path.endswith("path-overlay") else "depth_gt"
                    try:
                        frame = self.requested_frame(name, parsed.query)
                        if frame is None:
                            raise ValueError("No fresh matching frame")
                        with service.session.lock:
                            pose = service.session.history.at(frame.stamp_ns)
                            config = dict(service.session.config["depth"])
                            follower = service.session.follower
                            route = [pose.xy_heading[:2], *follower.route[follower.index:]] if follower else None
                            replans = max(0, service.session.replans - 1)
                        h, w = frame.pixels.shape[:2]
                        if (("width" in config and config["width"] != w)
                                or ("height" in config and config["height"] != h)):
                            raise ValueError("Frame does not match central camera calibration")
                        if name == "cam_central":
                            if route is None:
                                raise ValueError("No planned route")
                            view = project_route(service.session.grid, pose.matrix, config["to_body"],
                                                 config["hfov_deg"], w, h, route)
                            view["replans"] = replans
                        else:
                            view = local_depth_view(service.session.grid, pose.matrix, config["to_body"],
                                                    config["hfov_deg"], frame.depth_m())
                        if service.feeds.frame(name, frame.stamp_ns) is not frame:
                            raise ValueError("Frame expired or sensor disconnected during processing")
                        view["stamp_ns"] = str(frame.stamp_ns)
                        return self.reply(200, view)
                    except (ValueError, KeyError, TypeError) as error:
                        return self.reply(404, {"error": str(error)})
                if parsed.path.startswith("/dashboard/camera/") and not parsed.query:
                    filename = parsed.path.removeprefix("/dashboard/camera/")
                    allowed = {"cam_central.jpg", "cam_left.jpg", "cam_right.jpg", "depth_gt.jpg"}
                    if filename not in allowed:
                        return self.reply(404, {"error": "Unknown camera feed"})
                    packet = service.feeds.image(filename.removesuffix(".jpg"), with_stamp=True)
                    return (self.binary_reply(packet[0], "image/jpeg", stamp=packet[1]) if packet
                            else self.reply(404, {"error": "No fresh frame or image encoder"}))
                if parsed.path in ("/mission/snapshot", "/mission/trail", "/mission/events", "/mission/export"):
                    try:
                        if len(self.path) > 1024:
                            raise ValueError("Query exceeds 1024 characters")
                        query = parse_qs(parsed.query, keep_blank_values=True, strict_parsing=True)
                        allowed = (
                            {"after_seq", "mission_id"}
                            if parsed.path == "/mission/trail"
                            else ({"after_seq"} if parsed.path == "/mission/events" else set())
                        )
                        if set(query) - allowed or any(len(v) != 1 for v in query.values()):
                            raise ValueError("Unknown or repeated query field")
                        raw = query.get("after_seq", ["0"])[0]
                        if not raw.isascii() or not raw.isdigit() or len(raw) > 16 or int(raw) > 2**53 - 1:
                            raise ValueError("after_seq must be an integer in 0..2^53-1")
                        if parsed.path == "/mission/snapshot":
                            result = service.session.mission_snapshot(service.bridge.status())
                        elif parsed.path == "/mission/export":
                            result = service.session.mission_export()
                        else:
                            with service.session.lock:
                                if parsed.path == "/mission/trail":
                                    result = service.session.mission.trail(
                                        after_seq=int(raw), mission_id=query.get("mission_id", [None])[0]
                                    )
                                else:
                                    result = service.session.mission.event_page(after_seq=int(raw))
                        if parsed.path in ("/mission/snapshot", "/mission/export"):
                            result["control_timing"] = service.control_timing()
                            if service.session.obstacle_diagnostics:
                                result["lidar_ingest_timing"] = service.lidar_ingest_timing()
                        return self.reply(200, result)
                    except ValueError as error:
                        return self.reply(400, {"error": str(error)})
                    except KeyError:
                        return self.reply(404, {"error": "Mission is not retained in bounded history"})
                if self.path == "/":
                    return self.file_reply(Path(__file__).with_name("mission_control.html"), "text/html; charset=utf-8")
                if self.path == "/terrain.png":
                    folder = getattr(service.session.grid, "bundle_path", None)
                    if folder:
                        return self.file_reply(folder / "ortho_reference.png", "image/png")
                    return self.reply(404, {"error": "No registered orbital reference in this grid"})
                if self.path == "/map":
                    with service.session.lock:
                        grid = service.session.grid
                        h, w = grid.heights.shape
                        blocked = grid.blocked.copy()
                        result = {
                            "width": w,
                            "height": h,
                            "resolution_m": grid.resolution_m,
                            "extent_m": [(w - 1) * grid.resolution_m, (h - 1) * grid.resolution_m],
                            "revision": grid.revision,
                        }
                    result["blocked"] = blocked.astype(int).ravel().tolist()
                    return self.reply(200, result)
                if self.path != "/status":
                    return self.reply(404, {"error": "Unknown endpoint"})
                result = {**service.session.status(), "transport_error": service.last_transport_error,
                          "control_timing": service.control_timing()}
                if service.session.obstacle_diagnostics:
                    result["lidar_ingest_timing"] = service.lidar_ingest_timing()
                self.reply(200, result)

            def file_reply(self, path, content_type):
                if not path.is_file():
                    return self.reply(404, {"error": "Asset not available"})
                payload = path.read_bytes()
                return self.send_payload(200, payload, content_type)

            def requested_frame(self, name, query_string):
                if not query_string:
                    return service.feeds.frame(name)
                if len(query_string) > 128:
                    raise ValueError("Capture query too large")
                query = parse_qs(query_string, keep_blank_values=True, strict_parsing=True)
                raw = query.get("stamp", [""])
                if (set(query) != {"stamp"} or len(raw) != 1 or not raw[0].isascii()
                        or not raw[0].isdigit() or len(raw[0]) > 19):
                    raise ValueError("Expected one exact capture timestamp")
                return service.feeds.frame(name, int(raw[0]))

            def binary_reply(self, payload, content_type, *, stamp=None):
                return self.send_payload(200, payload, content_type, stamp=stamp, no_store=True)

            def do_POST(self):
                if self.path not in ("/goal", "/stop", "/dashboard/viewport"):
                    return self.reply(404, {"error": "Unknown endpoint"})
                try:
                    size = int(self.headers.get("Content-Length", "0"))
                    if (
                        self.headers.get_content_type() != "application/json"
                        or not 0 < size <= 4096
                        or self.headers.get("Transfer-Encoding")
                    ):
                        raise ValueError("Supply an application/json body of 1..4096 bytes")

                    def reject(value):
                        raise ValueError("Non-finite JSON number: " + value)

                    data = json.loads(self.rfile.read(size), parse_constant=reject)
                    if self.path == "/dashboard/viewport":
                        if not isinstance(data, dict) or set(data) != {"mode"}:
                            raise ValueError("Supply exactly one viewport mode")
                        return self.reply(200, service.viewport.set_mode(data["mode"]))
                    with service.session.lock:
                        service.bridge.state.stop()
                        if self.path == "/goal":
                            if not isinstance(data, dict) or set(data) != {"x", "y"}:
                                raise ValueError("Supply x,y in local east/north metres")
                            service.session.set_goal((data["x"], data["y"]))
                        else:
                            if data != {}:
                                raise ValueError("Stop body must be {}")
                            service.session.stop()
                    self.reply(200, {"ok": True, **service.session.status()})
                except (ValueError, TypeError, TimeoutError, UnicodeError) as error:
                    if self.path in ("/goal", "/stop"):
                        with service.session.lock:
                            service.bridge.state.stop()
                            service.session.stop()
                    self.reply(400, {"error": str(error)})

        return Handler

    def _control(self):
        while not self.ending.is_set():
            started, expired = time.monotonic(), False
            try:
                with self.session.lock:
                    active = self.session.goal is not None
                    # The status age is sampled after this instant; using the
                    # earlier instant makes reconstructed receive time conservative.
                    snapshot_started = time.monotonic()
                    v, w = self.session.step(self.bridge.status(), now=snapshot_started, wall_clock=time.monotonic)
                    if active:
                        if v == 0 and w == 0:
                            expired = self.session._late_decision
                            self.bridge.state.stop()
                        else:
                            with self.bridge.state.lock:
                                deadline = self.session.motion_deadline()
                                now = time.monotonic()
                                if (not self.bridge.state.connected
                                        or self.bridge.connection_id != self.session.connection_id
                                        or deadline is None or deadline <= now):
                                    expired = True
                                    self.bridge.state.stop()
                                    self.session.state = "waiting_for_fresh_data"
                                    self.session.error = LATE_DATA_ERROR
                                    self.session.mission.state(self.session.state, self.session.error)
                                else:
                                    self.bridge.state.submit_twist(v, w, now=now, valid_until=deadline)
                                    self.session.error = None
                                    self.session.mission.state(self.session.state, None)
            except Exception as error:
                self.bridge.state.stop()
                self.last_transport_error = str(error)
            finally:
                duration = max(0.0, time.monotonic() - started)
                self._record_control_timing(duration, expired)
            # Keep the 50 ms target inclusive of work, with a short yield even
            # after an overrun so the network/sensor threads can run.
            self.ending.wait(max(0.001, 0.05 - duration))
        self.bridge.state.stop()

    def start(self):
        self.bridge.start()
        self.lidar.start()
        self.camera.start()
        for target in (self.http.serve_forever, self._control):
            thread = threading.Thread(target=target, daemon=True)
            thread.start()
            self.threads.append(thread)
        return self

    def close(self):
        self.ending.set()
        self.bridge.state.stop()
        for listener in (self.lidar, self.camera):
            if listener:
                listener.close()
        if self.http:
            if self.threads:
                self.http.shutdown()
            self.http.server_close()
        for thread in self.threads:
            thread.join(timeout=2)
        self.bridge.close()

    def __enter__(self):
        return self.start()

    def __exit__(self, *args):
        self.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sensors", type=Path, required=True)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--goal", nargs=2, type=float)
    parser.add_argument("--depth-source", choices=("ground_truth", "stereo"), default="ground_truth")
    parser.add_argument("--telemetry-format", choices=TELEMETRY_FORMATS, default="json",
                        help="wire format; unreal-tr-v1 is explicit compatibility for a tr-TR UE producer")
    parser.add_argument("--obstacle-diagnostics", action="store_true",
                        help="record bounded sensor/map-change diagnostics in mission export")
    args = parser.parse_args(argv)
    try:
        config = json.loads(args.sensors.read_text(encoding="utf-8"))
        grid = TerrainMap.from_bundle(args.manifest)
        with NavigationService(grid, config, depth_source=args.depth_source,
                               telemetry_format=args.telemetry_format,
                               obstacle_diagnostics=args.obstacle_diagnostics) as service:
            if args.goal:
                service.session.set_goal(args.goal)
            print("Navigation API http://127.0.0.1:8766; start Unreal Play after this line.", flush=True)
            print(f"Depth source: {args.depth_source}; native rover acceptance is still required.", flush=True)
            print(f"Telemetry format: {args.telemetry_format}", flush=True)
            if args.obstacle_diagnostics:
                print("Obstacle diagnostics enabled; use mission export to preserve the evidence.", flush=True)
            if args.telemetry_format == "unreal-tr-v1":
                print(TR_TELEMETRY_NOTICE, flush=True)
            try:
                while not service.ending.wait(0.5):
                    pass
            except KeyboardInterrupt:
                pass
    except (OSError, ValueError) as error:
        parser.exit(1, str(error) + "\n")


if __name__ == "__main__":
    main()
