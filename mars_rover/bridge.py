"""Local Python HTTP -> MARE TCP bridge, replacing the GNC rover node.

Start this BEFORE pressing Play. Do not run component_rover_leo_raph at the
same time: it owns the same TCP endpoint. This bridge transports motor commands
and raw pose telemetry. The optional nav_service adds camera/lidar decoders.
"""

import argparse
import codecs
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import select
import socket
import threading
import time

from .drive import Calibration, CommandState, number


def _bad_constant(value):
    raise ValueError(f"Non-finite JSON value: {value}")


class JsonObjectStream:
    """Unreal sends concatenated JSON objects, sometimes without newlines."""

    def __init__(self):
        self.buffer = ""
        self.utf8 = codecs.getincrementaldecoder("utf-8")()
        self.decoder = json.JSONDecoder(parse_constant=_bad_constant)

    def feed(self, chunk):
        self.buffer += self.utf8.decode(chunk)
        result = []
        while True:
            self.buffer = self.buffer.lstrip(" \r\n\t\x00")
            if not self.buffer:
                return result
            try:
                value, end = self.decoder.raw_decode(self.buffer)
            except json.JSONDecodeError:
                if len(self.buffer) > 65536:
                    raise ValueError("Telemetry exceeded 64 KiB without a complete JSON object")
                return result
            if not isinstance(value, dict):
                raise ValueError("Telemetry must contain JSON objects")
            if end > 65536:
                raise ValueError("Telemetry object exceeded 64 KiB")
            self.buffer = self.buffer[end:]
            result.append(value)


class BridgeServer:
    def __init__(self, calibration, *, tcp_port=3003, http_port=8765, timeout_s=0.3, on_external_command=None):
        self.state = CommandState(calibration, timeout_s)
        self.telemetry = None
        self.telemetry_received_at = None
        self.last_error = None
        self.connection_id = 0
        self.on_external_command = on_external_command
        self.ending = threading.Event()
        self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self.listener.bind(("127.0.0.1", tcp_port))
            self.listener.listen(1)
            self.tcp_port = self.listener.getsockname()[1]
            self.http = ThreadingHTTPServer(("127.0.0.1", http_port), self._handler())
        except BaseException:
            self.listener.close()
            raise
        self.http_port = self.http.server_port
        self.threads = []

    def _handler(self):
        bridge = self

        class Handler(BaseHTTPRequestHandler):
            def setup(self):
                super().setup()
                self.connection.settimeout(2)

            def log_message(self, *args):
                pass

            def reply(self, status, result):
                payload = json.dumps(result, allow_nan=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def do_GET(self):
                if self.path != "/status":
                    self.reply(404, {"error": "Unknown endpoint"})
                    return
                self.reply(200, bridge.status())

            def do_POST(self):
                try:
                    if self.headers.get_content_type() != "application/json":
                        raise ValueError("Content-Type must be application/json")
                    length = int(self.headers.get("Content-Length", "0"))
                    if not 0 < length <= 4096 or self.headers.get("Transfer-Encoding"):
                        raise ValueError("Supply a JSON body of 1..4096 bytes")
                    data = json.loads(self.rfile.read(length), parse_constant=_bad_constant)
                    if not isinstance(data, dict):
                        raise ValueError("Body must be a JSON object")
                    if self.path in ("/wheels", "/twist", "/stop") and bridge.on_external_command:
                        bridge.on_external_command()
                    if self.path == "/wheels":
                        bridge.state.submit_wheels(data)
                    elif self.path == "/twist":
                        if set(data) != {"linear_m_s", "angular_rad_s"}:
                            raise ValueError("Supply linear_m_s and angular_rad_s")
                        bridge.state.submit_twist(data["linear_m_s"], data["angular_rad_s"])
                    elif self.path == "/stop":
                        if data:
                            raise ValueError("Stop body must be {}")
                        bridge.state.stop()
                    else:
                        self.reply(404, {"error": "Unknown endpoint"})
                        return
                    self.reply(200, {"ok": True, "wire_command": bridge.state.sample()})
                except ConnectionError as error:
                    bridge.state.stop()
                    self.reply(409, {"error": str(error)})
                except (ValueError, UnicodeError, TimeoutError) as error:
                    bridge.state.stop()
                    self.reply(400, {"error": str(error)})

        return Handler

    def status(self):
        with self.state.lock:
            telemetry = self.telemetry
            pose = None
            if telemetry and all(k in telemetry for k in ("x", "y", "z", "yaw")):
                try:
                    heading = math.radians(180 - number(telemetry["yaw"]))
                    pose = {
                        "x": -number(telemetry["x"]) / 100,
                        "y": number(telemetry["y"]) / 100,
                        "z": number(telemetry["z"]) / 100,
                        "heading_rad": (heading + math.pi) % (2 * math.pi) - math.pi,
                    }
                except ValueError:
                    pass
            return {
                "connected": self.state.connected,
                "connection_id": self.connection_id,
                "wire_command": self.state.sample(),
                "telemetry_unreal": telemetry,
                "pose_local_m": pose,
                "telemetry_age_s": None
                if self.telemetry_received_at is None
                else time.monotonic() - self.telemetry_received_at,
                "last_error": self.last_error,
            }

    def start(self):
        if self.threads:
            raise RuntimeError("Bridge already started")
        for target in (self.http.serve_forever, self._tcp_loop):
            thread = threading.Thread(target=target, daemon=True)
            thread.start()
            self.threads.append(thread)
        return self

    def _tcp_loop(self):
        self.listener.settimeout(0.1)
        while not self.ending.is_set():
            try:
                peer, _ = self.listener.accept()
            except socket.timeout:
                continue
            with peer:
                peer.settimeout(0.2)
                parser = JsonObjectStream()
                with self.state.lock:
                    self.telemetry = None
                    self.telemetry_received_at = None
                    self.last_error = None
                    self.connection_id += 1
                    self.state.connect()
                try:
                    next_send = time.monotonic()
                    while not self.ending.is_set():
                        now = time.monotonic()
                        if now >= next_send:
                            peer.sendall(json.dumps(self.state.sample(), allow_nan=False).encode() + b"\n")
                            next_send = now + 0.05
                        readable, _, _ = select.select([peer], [], [], max(0, next_send - time.monotonic()))
                        if readable:
                            chunk = peer.recv(4096)
                            if not chunk:
                                break
                            for telemetry in parser.feed(chunk):
                                # Validate serializability before exposing data to HTTP.
                                json.dumps(telemetry, allow_nan=False)
                                with self.state.lock:
                                    self.telemetry = telemetry
                                    self.telemetry_received_at = time.monotonic()
                except (OSError, ValueError, UnicodeError) as error:
                    self.last_error = str(error)
                finally:
                    try:
                        peer.sendall(json.dumps(self._zero()).encode() + b"\n")
                    except OSError:
                        pass
                    self.state.disconnect()

    def _zero(self):
        self.state.stop()
        return self.state.sample()

    def close(self):
        self.state.stop()
        self.ending.set()
        if self.threads:
            self.http.shutdown()
            for thread in self.threads:
                thread.join(timeout=2)
        self.http.server_close()
        self.listener.close()

    def __enter__(self):
        return self.start()

    def __exit__(self, *args):
        self.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tcp-port", type=int, default=3003)
    parser.add_argument("--http-port", type=int, default=8765)
    parser.add_argument("--timeout", type=float, default=0.3, help="command watchdog, wall seconds")
    parser.add_argument("--track", type=float, default=0.89, help="effective track in metres; calibrate for your rover")
    parser.add_argument("--wheel-scale", type=float, default=1.82, help="MARE Blueprint wheel input per m/s")
    parser.add_argument("--max-speed", type=float, default=0.5, help="maximum tyre speed in m/s")
    args = parser.parse_args()
    calibration = Calibration(args.track, args.wheel_scale, args.max_speed)
    with BridgeServer(calibration, tcp_port=args.tcp_port, http_port=args.http_port, timeout_s=args.timeout) as bridge:
        print(f"Waiting for Unreal on 127.0.0.1:{bridge.tcp_port}; API http://127.0.0.1:{bridge.http_port}", flush=True)
        print("Calibration is for upstream Leo_Raph; remeasure for your CAD rover/Mars gravity.", flush=True)
        try:
            while not bridge.ending.wait(0.5):
                pass
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
