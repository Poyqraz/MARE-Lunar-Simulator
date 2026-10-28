"""Small standard-library adapter to call from an existing Python controller."""
import json
import urllib.request


class RoverClient:
    def __init__(self, base_url="http://127.0.0.1:8765"):
        self.base_url = base_url.rstrip("/")

    def _post(self, path, values):
        request = urllib.request.Request(
            self.base_url + path, method="POST",
            data=json.dumps(values, allow_nan=False).encode("utf-8"),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=2) as response:
            return json.load(response)

    def wheels(self, *, FL, FR, BL, BR):
        """Four independent tyre speeds, in m/s; repeat faster than the watchdog."""
        return self._post("/wheels", dict(FL=FL, FR=FR, BL=BL, BR=BR))

    def twist(self, linear_m_s, angular_rad_s):
        """Positive angular velocity turns left, like ROS REP-103."""
        return self._post("/twist", dict(linear_m_s=linear_m_s, angular_rad_s=angular_rad_s))

    def stop(self):
        return self._post("/stop", {})

    def status(self):
        with urllib.request.urlopen(self.base_url + "/status", timeout=2) as response:
            return json.load(response)
