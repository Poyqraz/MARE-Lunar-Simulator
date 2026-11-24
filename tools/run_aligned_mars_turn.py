"""Run the supervised simulated turn bound to the latest PIE tick alignment.

This sends a motion goal and a stop through the simulator API. It first reads
the latest logged MARS_TICK_ALIGNMENT and requires its session in both turn
preflight snapshots. Session checks and the later HTTP goal are not atomic;
continue to supervise the simulation and keep Unreal Stop accessible.
"""

import json
from pathlib import Path
import re
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import mars_lidar_turn_probe as turn  # noqa: E402
from tools.analyze_mars_lidar_pose import _tail_lines  # noqa: E402

PREFIX = "LogPython: MARS_TICK_ALIGNMENT: "


def _group(value):
    if not isinstance(value, str):
        return None
    match = re.search(r"(?:^|\.)((?:TG_)[A-Z_]+)(?=[:>]|$)", value)
    return match.group(1) if match else None


def alignment_session(log_path):
    lines, _ = _tail_lines(log_path)
    line = next((line for line in reversed(lines) if PREFIX in line), None)
    if line is None:
        raise ValueError("Hizalama kaydi bulunamadi; Play acikken ta.apply() calistirin")
    try:
        data, _ = json.JSONDecoder().raw_decode(line.split(PREFIX, 1)[1])
        session = str(uuid.UUID(data["session_id"]))
        groups = data["groups"]
        if (not isinstance(data["world"], str) or "/UEDPIE_" not in data["world"]
                or not isinstance(data["rover"], str) or not data["rover"].startswith("Leo_Raph")
                or _group(groups["actor"]["after"]) != "TG_POST_PHYSICS"
                or _group(groups["lidar"]["after"]) != "TG_POST_UPDATE_WORK"
                or _group(groups["camera"]["after"]) != "TG_POST_UPDATE_WORK"):
            raise ValueError("Hizalama gruplari veya PIE rover bilgisi uygun degil")
    except (ValueError, TypeError, KeyError, AttributeError) as error:
        raise ValueError("Son hizalama kaydi okunamadi veya gecersiz: " + str(error)) from error
    return {"session_id": session, "world": data["world"], "rover": data["rover"], "groups": groups}


def recent_session_events(*, get=turn._get):
    """Best-effort read-only context; a missing event history does not grant a goal."""
    try:
        page = get("/mission/events")
        if not isinstance(page, dict) or not isinstance(page.get("events"), list):
            raise ValueError("Oturum olaylari gecersiz")
        events = [e for e in page["events"] if isinstance(e, dict)
                  and e.get("kind") in ("session_started", "session_ended")][-6:]
        return {"session_id": page.get("session_id"), "truncated": page.get("truncated"), "events": events}
    except (OSError, ValueError, TypeError, KeyError) as error:
        return {"error": str(error)[:500]}


def main():
    log = ROOT / "Saved/Logs/Moon_Simulator.log"
    try:
        alignment = alignment_session(log)
    except (OSError, ValueError) as error:
        raise SystemExit("HIZALAMA_KONTROLU_BASARISIZ: " + str(error)) from error
    print("MARS_HIZALAMA_BEKLENTISI:", json.dumps(alignment, ensure_ascii=False), flush=True)
    print("MARS_OTURUM_GECMISI:", json.dumps(recent_session_events(), ensure_ascii=False), flush=True)
    turn.main(expected_session=alignment["session_id"])


if __name__ == "__main__":
    main()
