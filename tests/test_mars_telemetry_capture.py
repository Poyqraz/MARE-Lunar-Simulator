import json
import socket
import threading
from queue import Queue

import pytest

from tools.capture_rover_telemetry import capture


def test_capture_preserves_fragmented_bytes_and_only_sends_zero_commands():
    payload = b'{"time": 0,033, "x": -12.600,019}{"time": 0,067}'
    result = Queue()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)

        def receive():
            try:
                result.put(capture(listener, timeout_s=2, duration_s=2, max_bytes=len(payload)))
            except Exception as error:
                result.put(error)

        thread = threading.Thread(target=receive)
        thread.start()
        with socket.create_connection(listener.getsockname(), timeout=2) as peer:
            peer.settimeout(2)
            command = b""
            while b"\n" not in command:
                command += peer.recv(4096)
            parsed = json.loads(command.split(b"\n", 1)[0])
            assert {key: parsed[key] for key in ("FL", "FR", "BL", "BR")} == dict.fromkeys(
                ("FL", "FR", "BL", "BR"), 0
            )
            peer.sendall(payload[:11])
            peer.sendall(payload[11:])
            thread.join(timeout=3)
            assert not thread.is_alive()
            assert result.get_nowait() == payload


def test_capture_times_out_if_no_rover_connects():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        with pytest.raises(TimeoutError):
            capture(listener, timeout_s=0.05)
