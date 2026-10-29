"""Run a ROS-free simulated Mars mission with MARE's existing TCP sensors.

    python -m mars_rover.nav_service --sensors Saved/Mars/rover-sensors.json --goal 200 100

Start before Play. Owns motor 3003, camera 3004, LiDAR 3007, motor HTTP 8765
and navigation HTTP 8766 on localhost. Stop conflicting GNC services first.
"""

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import socket
import threading
from urllib.parse import parse_qs, urlsplit

from .bridge import BridgeServer, TELEMETRY_FORMATS, TR_TELEMETRY_NOTICE
from .drive import Calibration
from .navigation import NavigationSession
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
    ):
        self.session = NavigationSession(
            grid, config, min_points=min_points, depth_source=depth_source, settle_s=settle_s
        )
        self.ending = threading.Event()
        self.last_transport_error = None
        self.threads = []
        self.bridge = BridgeServer(
            Calibration(), tcp_port=tcp_port, http_port=bridge_http_port, on_external_command=self.session.stop,
            telemetry_format=telemetry_format,
        )
        self.lidar, self.camera, self.http = None, None, None
        try:
            self.lidar = PacketListener(
                lidar_port, LidarStream, self.session.feed_lidar, lambda error: self._sensor_error("lidar", error)
            )
            self.camera = PacketListener(
                camera_port,
                NavStream,
                self.session.feed_camera,
                lambda error: self._sensor_error(self.session.depth_source, error),
            )
            self.http = ThreadingHTTPServer(("127.0.0.1", http_port), self._handler())
        except BaseException:
            self.close()
            raise

    def _sensor_error(self, key, error):
        with self.session.lock:
            self.last_transport_error = str(error)
            self.session.health.pop(key, None)
            self.bridge.state.stop()

    def _handler(self):
        service = self

        class Handler(BaseHTTPRequestHandler):
            def setup(self):
                super().setup()
                self.connection.settimeout(2)

            def log_message(self, *args):
                pass

            def reply(self, code, value):
                payload = json.dumps(value, allow_nan=False).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def do_GET(self):
                parsed = urlsplit(self.path)
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
                self.reply(200, {**service.session.status(), "transport_error": service.last_transport_error})

            def file_reply(self, path, content_type):
                if not path.is_file():
                    return self.reply(404, {"error": "Asset not available"})
                payload = path.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def do_POST(self):
                if self.path not in ("/goal", "/stop"):
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
                    with service.session.lock:
                        service.bridge.state.stop()
                        service.session.stop()
                    self.reply(400, {"error": str(error)})

        return Handler

    def _control(self):
        while not self.ending.is_set():
            try:
                with self.session.lock:
                    active = self.session.goal is not None
                    v, w = self.session.step(self.bridge.status())
                    if active:
                        if v == 0 and w == 0:
                            self.bridge.state.stop()
                        else:
                            self.bridge.state.submit_twist(v, w)
            except Exception as error:
                self.bridge.state.stop()
                self.last_transport_error = str(error)
            self.ending.wait(0.05)
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
    args = parser.parse_args(argv)
    try:
        config = json.loads(args.sensors.read_text(encoding="utf-8"))
        grid = TerrainMap.from_bundle(args.manifest)
        with NavigationService(grid, config, depth_source=args.depth_source,
                               telemetry_format=args.telemetry_format) as service:
            if args.goal:
                service.session.set_goal(args.goal)
            print("Navigation API http://127.0.0.1:8766; start Unreal Play after this line.", flush=True)
            print(f"Depth source: {args.depth_source}; native rover acceptance is still required.", flush=True)
            print(f"Telemetry format: {args.telemetry_format}", flush=True)
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
