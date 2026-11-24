"""An aligned turn requires an unambiguous matching PIE log record."""

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import run_aligned_mars_turn as wrapper  # noqa: E402

SESSION = "13470f98-25ec-4c90-8fe5-63b9975067fa"


def alignment(session=SESSION):
    return {"world": "/Game/Mars/UEDPIE_0_JezeroRover_5c8b3fa632eb.JezeroRover_5c8b3fa632eb",
            "rover": "Leo_Raph_C_0", "session_id": session,
            "groups": {"actor": {"after": "<TickingGroup.TG_POST_PHYSICS: 4>"},
                       "lidar": {"after": "<TickingGroup.TG_POST_UPDATE_WORK: 5>"},
                       "camera": {"after": "<TickingGroup.TG_POST_UPDATE_WORK: 5>"}}}


def line(data):
    return "[date][frame]LogPython: MARS_TICK_ALIGNMENT: " + json.dumps(data) + "\n"


class TestAlignedTurnWrapper(unittest.TestCase):
    def test_reads_latest_valid_alignment_for_same_pie(self):
        older = alignment("f57b3886-394e-463c-83ac-522b9adeafff")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Unreal.log"
            path.write_text(line(older) + line(alignment()), encoding="utf-8")
            result = wrapper.alignment_session(path)
        self.assertEqual(result["session_id"], SESSION)
        self.assertEqual(result["rover"], "Leo_Raph_C_0")

    def test_missing_invalid_or_wrong_group_cannot_fall_back_to_older_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Unreal.log"
            path.write_text("no alignment\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "bulunamadi"):
                wrapper.alignment_session(path)
            wrong = alignment()
            wrong["groups"]["lidar"]["after"] = "<TickingGroup.TG_POST_PHYSICS: 4>"
            path.write_text(line(alignment()) + line(wrong), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "gecersiz"):
                wrapper.alignment_session(path)
            path.write_text(line(alignment()) + wrapper.PREFIX + "{broken\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "gecersiz"):
                wrapper.alignment_session(path)

    def test_utf16_and_read_only_event_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Unreal.log"
            path.write_bytes(line(alignment()).encode("utf-16"))
            self.assertEqual(wrapper.alignment_session(path)["session_id"], SESSION)
        calls = []

        def get(path):
            calls.append(path)
            return {"session_id": SESSION, "truncated": False,
                    "events": [{"kind": "session_started", "reason": "new_connection"},
                               {"kind": "goal_accepted"}]}

        result = wrapper.recent_session_events(get=get)
        self.assertEqual(calls, ["/mission/events"])
        self.assertEqual([e["kind"] for e in result["events"]], ["session_started"])

    def test_main_never_invokes_turn_without_a_valid_alignment(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            log = root / "Saved/Logs/Moon_Simulator.log"
            log.parent.mkdir(parents=True)
            log.write_text("no alignment\n", encoding="utf-8")
            with patch.object(wrapper, "ROOT", root), patch.object(wrapper.turn, "main") as turn:
                with self.assertRaisesRegex(SystemExit, "HIZALAMA_KONTROLU_BASARISIZ"):
                    wrapper.main()
                turn.assert_not_called()
            log.write_text(line(alignment()), encoding="utf-8")
            with (patch.object(wrapper, "ROOT", root), patch.object(wrapper.turn, "main") as turn,
                  patch.object(wrapper, "recent_session_events", return_value={"events": []}),
                  redirect_stdout(io.StringIO())):
                wrapper.main()
            turn.assert_called_once_with(expected_session=SESSION)


if __name__ == "__main__":
    unittest.main()
