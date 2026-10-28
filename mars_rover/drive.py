"""Four independent wheel speeds, in m/s at the tyre; no ROS dependency.

Calibration defaults are for the upstream Leo_Raph, NOT the user's CAD rover.
MARE's Blueprint expects negative wheel inputs for forward motion.
"""
from dataclasses import dataclass
import math
import threading
import time

WHEELS = ("FL", "FR", "BL", "BR")


def number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("Speeds must be finite numbers")
    return float(value)


@dataclass(frozen=True)
class Calibration:
    effective_track_m: float = 0.89
    wheel_speed_scale: float = 1.82
    max_wheel_speed_m_s: float = 0.5

    def __post_init__(self):
        for value in (self.effective_track_m, self.wheel_speed_scale, self.max_wheel_speed_m_s):
            if number(value) <= 0:
                raise ValueError("Calibration values must be positive")


def validate_wheels(speeds, calibration: Calibration) -> dict:
    if not isinstance(speeds, dict) or set(speeds) != set(WHEELS):
        raise ValueError("Supply exactly FL, FR, BL, BR in metres per second")
    checked = {key: number(speeds[key]) for key in WHEELS}
    ratio = max(1, max(abs(value) for value in checked.values()) / calibration.max_wheel_speed_m_s)
    return {key: value / ratio for key, value in checked.items()}


def wheels_from_twist(v, w, calibration: Calibration) -> dict:
    v, w = number(v), number(w)
    left = v - w * calibration.effective_track_m / 2
    right = v + w * calibration.effective_track_m / 2
    return validate_wheels(dict(FL=left, BL=left, FR=right, BR=right), calibration)


def wire_command(speeds, calibration: Calibration) -> dict:
    checked = validate_wheels(speeds, calibration)
    return {**{k: -v * calibration.wheel_speed_scale for k, v in checked.items()},
            "headlights_on": False, "headlights_intensity": 0.0}


class CommandState:
    """Wall-clock watchdog. Connection changes clear commands; stale ones latch stop."""
    def __init__(self, calibration: Calibration, timeout_s=0.3):
        self.calibration = calibration
        self.timeout_s = number(timeout_s)
        if self.timeout_s <= 0:
            raise ValueError("timeout_s must be positive")
        self.lock = threading.RLock()
        self.connected = False
        self.stop()

    def stop(self):
        with self.lock:
            self.speeds = dict.fromkeys(WHEELS, 0.0)
            self.received_at = None

    def connect(self):
        with self.lock:
            self.stop()
            self.connected = True

    def disconnect(self):
        with self.lock:
            self.connected = False
            self.stop()

    def submit_wheels(self, speeds, *, now=None):
        with self.lock:
            try:
                checked = validate_wheels(speeds, self.calibration)
            except ValueError:
                self.stop()
                raise
            if not self.connected:
                raise ConnectionError("Unreal is not connected; start the bridge, then press Play")
            self.speeds = checked
            self.received_at = time.monotonic() if now is None else now

    def submit_twist(self, v, w, *, now=None):
        try:
            speeds = wheels_from_twist(v, w, self.calibration)
        except ValueError:
            self.stop()
            raise
        self.submit_wheels(speeds, now=now)

    def sample(self, *, now=None):
        with self.lock:
            now = time.monotonic() if now is None else now
            if self.received_at is None or now - self.received_at >= self.timeout_s or now < self.received_at:
                self.stop()
            return wire_command(self.speeds, self.calibration)
