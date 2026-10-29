"""Capture a bounded raw rover TCP prefix while sending only zero wheel commands.

Stop Unreal Play and any navigation/bridge service before starting this tool;
start Play only after it reports that the localhost listener is ready.
This is a short diagnostic, not a motion or sensor acceptance test.
"""

import base64
import json
import select
import socket
import time


ZERO_COMMAND = (json.dumps({"FL": 0.0, "FR": 0.0, "BL": 0.0, "BR": 0.0,
                            "headlights_on": False, "headlights_intensity": 0.0}) + "\n").encode("ascii")


def capture(listener, *, timeout_s=60, duration_s=5, max_bytes=2048):
    """Accept one peer, preserve its first bytes exactly, and close after a bounded time."""
    listener.settimeout(timeout_s)
    peer, _address = listener.accept()
    with peer:
        peer.settimeout(0.5)
        data = bytearray()
        end, next_send = time.monotonic() + duration_s, 0.0
        try:
            while len(data) < max_bytes and time.monotonic() < end:
                now = time.monotonic()
                if now >= next_send:
                    # A small packet, once every 50 ms, as in the normal bridge.
                    peer.sendall(ZERO_COMMAND)
                    next_send = now + 0.05
                wait = max(0.0, min(end - now, next_send - now, 0.05))
                readable, _, _ = select.select([peer], [], [], wait)
                if readable:
                    chunk = peer.recv(max_bytes - len(data))
                    if not chunk:
                        break
                    data.extend(chunk)
        finally:
            try:
                peer.sendall(ZERO_COMMAND)
            except OSError:
                pass
    return bytes(data)


def main():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", 3003))
            listener.listen(1)
            print("TCP 3003 hazir. Unreal'a donup 60 saniye icinde Play'e basin.", flush=True)
            data = capture(listener)
        if not data:
            raise RuntimeError("Rover baglandi, fakat telemetri gelmedi")
        print("HAM_TCP_BOYUT:", len(data))
        print("HAM_TCP_BASE64:", base64.b64encode(data).decode("ascii"))
        print("Yakalama bitti. Unreal'da Play'i durdurun.", flush=True)
    except (OSError, RuntimeError) as error:
        raise SystemExit(f"Yakalama basarisiz: {error}") from error


if __name__ == "__main__":
    main()
