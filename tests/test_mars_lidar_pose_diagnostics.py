"""Tests for opt-in request-pose logging and offline same-stamp comparison."""

from contextlib import redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest


ROOT = Path(__file__).resolve().parents[1]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def telemetry(stamp, pitch="0"):
    return ('[date][1]LogBlueprintUserMessages: [Leo_Raph_C_0] '
            '{"time": 1,0, "x" : -100,1, "y": 100,1, "z": 100, '
            '"roll": 0, "pitch": ' + pitch + ', "yaw": 180, "vx": 0, "vy": 0, "vz": 0, '
            '"wx": 0, "wy": 0, "wz": 0, "t_ns": "' + str(stamp) + '"}')


def capture(stamp, pitch=1.5):
    data = {"frame_id": "42", "stamp_ns": str(stamp), "x": -100.1, "y": 100.1, "z": 100,
            "roll": 0, "pitch": pitch, "yaw": 180}
    return "[date][1]LogTemp: MARS_LIDAR_POSE: " + json.dumps(data)


class TestPoseAnalysis(unittest.TestCase):
    def test_same_stamp_turn_discrepancy_is_measured_and_no_log_is_modified(self):
        analyzer = module("analyze_lidar_pose", "tools/analyze_mars_lidar_pose.py")
        stamp = 1_700_000_000_100_000_000
        text = "\n".join((telemetry(stamp + 200), capture(stamp))) + "\n"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Unreal.log"
            path.write_text(text, encoding="utf-8")
            report = analyzer.analyze(path)
            self.assertEqual(path.read_text(encoding="utf-8"), text)
        self.assertEqual(report["matched_frames"], 1)
        self.assertAlmostEqual(report["orientation_difference_deg"]["max_abs"], 1.5, places=7)
        self.assertAlmostEqual(report["up_axis_difference_deg"]["max_abs"], 1.5, places=7)
        self.assertAlmostEqual(report["forward_8m_vertical_difference_m"]["max_abs"],
                               8 * __import__("math").sin(__import__("math").radians(1.5)), places=7)

    def test_unmatched_and_ambiguous_stamps_are_not_silently_paired(self):
        analyzer = module("analyze_lidar_pose", "tools/analyze_mars_lidar_pose.py")
        stamp = 1_700_000_000_100_000_000
        text = "\n".join((telemetry(stamp), telemetry(stamp), capture(stamp), capture(stamp + 20_000_000)))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Unreal.log"
            path.write_text(text, encoding="utf-8")
            report = analyzer.analyze(path)
        self.assertEqual(report["status"], "no_matched_frames")
        self.assertEqual(report["matched_frames"], 0)
        self.assertEqual(report["ambiguous_captures"], 1)
        self.assertEqual(report["unmatched_captures"], 1)

    def test_reads_utf16_log_and_respects_bounded_tail(self):
        analyzer = module("analyze_lidar_pose", "tools/analyze_mars_lidar_pose.py")
        stamp = 1_700_000_000_100_000_000
        text = "old line " * 200 + "\n" + telemetry(stamp) + "\n" + capture(stamp) + "\n"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Unreal.log"
            path.write_bytes(text.encode("utf-16"))
            report = analyzer.analyze(path, max_bytes=2000)
        self.assertTrue(report["log_tail_truncated"])
        self.assertEqual(report["matched_frames"], 1)

    def test_cli_decodes_actual_turkish_grouping_and_signed_angles(self):
        stamp = "1793469936237333872"
        blueprint = ('[date][1]LogBlueprintUserMessages: [Leo_Raph_C_0] '
                     '{"time": 10,333, "x" : -12.600,324, "y": 12.603,581, "z": 542,38, '
                     '"roll": -1,114, "pitch": -0,415, "yaw": -89,194, "vx": 0, '
                     '"vy": 0, "vz": 0, "wx": 0, "wy": 0, "wz": 0, "t_ns": "' + stamp + '"}')
        request = {"frame_id": "7", "stamp_ns": stamp, "x": -12600.324, "y": 12603.581,
                   "z": 542.38, "roll": -1.114, "pitch": -0.415, "yaw": -89.194}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Unreal.log"
            path.write_text(blueprint + "\nLogTemp: MARS_LIDAR_POSE: " + json.dumps(request) + "\n",
                            encoding="utf-8")
            result = subprocess.run([sys.executable, str(ROOT / "tools/analyze_mars_lidar_pose.py"), str(path)],
                                    check=True, capture_output=True, text=True, timeout=10)
        report = json.loads(result.stdout.split("MARS_LIDAR_POSE_ANALYSIS: ", 1)[1])
        self.assertEqual(report["matched_frames"], 1)
        self.assertAlmostEqual(report["translation_m"]["max_abs"], 0)
        self.assertAlmostEqual(report["up_axis_difference_deg"]["max_abs"], 0, places=5)

    def test_explicit_stamp_window_excludes_old_frames(self):
        analyzer = module("analyze_lidar_pose", "tools/analyze_mars_lidar_pose.py")
        stamp = 1_700_000_000_100_000_000
        later = stamp + 2_000_000_000
        text = "\n".join((telemetry(stamp), capture(stamp), telemetry(later), capture(later)))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Unreal.log"
            path.write_text(text, encoding="utf-8")
            report = analyzer.analyze(path, start_stamp_ns=later, end_stamp_ns=later)
        self.assertEqual(report["capture_records"], 1)
        self.assertEqual(report["matched_frames"], 1)
        self.assertEqual(report["first_capture_stamp_ns"], str(later))


class TestRuntimeTag(unittest.TestCase):
    def test_toggle_preserves_other_tags_and_requires_one_pie_rover(self):
        helper = module("lidar_toggle", "Content/Python/mars_lidar_pose_diagnostics.py")

        class Rover:
            tags = ["existing"]

            def get_editor_property(self, name):
                return self.tags

            def set_editor_property(self, name, value):
                self.tags = value

            def get_name(self):
                return "Leo_Raph_C_0"

            def get_class(self):
                return SimpleNamespace(get_name=lambda: "Leo_Raph_C")

        rover = Rover()
        world = SimpleNamespace(get_path_name=lambda: "/Game/Mars/UEDPIE_0_Test.Test")
        unreal = SimpleNamespace(EditorLevelLibrary=SimpleNamespace(get_pie_worlds=lambda _: [world]),
                                 GameplayStatics=SimpleNamespace(get_all_actors_of_class=lambda _w, _c: [rover]),
                                 Pawn=object, Name=str)
        with redirect_stdout(io.StringIO()):
            helper.enable(unreal_module=unreal)
            helper.enable(unreal_module=unreal)
            self.assertEqual(rover.tags, ["existing", "MarsLidarPoseProbe"])
            helper.disable(unreal_module=unreal)
        self.assertEqual(rover.tags, ["existing"])
        unreal.EditorLevelLibrary.get_pie_worlds = lambda _: []
        with self.assertRaisesRegex(ValueError, "one local"):
            helper.enable(unreal_module=unreal)


def cpp_helper_body():
    path = ROOT / "Plugins/UnrealLidarCam/Source/UnrealLidarCam/Private/UnrealLidarCam.cpp"
    source = path.read_text(encoding="utf-8")
    start = source.index("void LogMarsLidarPoseIfRequested(")
    opening = source.index("{", start)
    depth = 0
    for end in range(opening, len(source)):
        depth += (source[end] == "{") - (source[end] == "}")
        if depth == 0:
            return source[opening : end + 1]
    raise AssertionError("LiDAR diagnostic helper body is incomplete")


class TestCppRequestPose(unittest.TestCase):
    def test_production_helper_is_silent_without_tag_and_logs_once_when_enabled(self):
        compiler = shutil.which("g++") or shutil.which("clang++")
        if compiler is None:
            self.skipTest("C++ compiler unavailable")
        prefix = r'''
#include <algorithm>
#include <cassert>
#include <cctype>
#include <cstdint>
#include <cstdio>
#include <string>
#include <vector>
using int64 = int64_t; using uint64 = uint64_t;
template<class T> using TArray = std::vector<T>;
#define TEXT(x) x
#define FName(x) std::string(x)
std::vector<std::string> logs;
template<class... A> void Log(const char* f, A... a) { char b[2048]; std::snprintf(b, sizeof(b), f, a...); logs.emplace_back(b); }
#define UE_LOG(category, level, fmt, ...) Log(fmt, ##__VA_ARGS__)
struct FVector { double X, Y, Z; };
struct FRotator { double Roll, Pitch, Yaw; };
struct USceneComponent {
    std::string name;
    std::string GetName() const { return name; }
    FVector GetComponentLocation() const { return {-100.1, 100.1, 100}; }
    FRotator GetComponentRotation() const { return {0, 1.5, 180}; }
};
std::string NormalizeName(std::string s) {
    s.erase(std::remove(s.begin(), s.end(), '_'), s.end());
    std::transform(s.begin(), s.end(), s.begin(), [](unsigned char c){return std::tolower(c);}); return s;
}
struct AActor {
    bool tagged = false;
    std::vector<USceneComponent*> components;
    bool ActorHasTag(const std::string&) const { return tagged; }
    template<class T> void GetComponents(TArray<T*>& out) const { out = components; }
};
void LogMarsLidarPoseIfRequested(const AActor* Owner, double Stamp, uint64 FrameId)
'''
        suffix = r'''
int main() {
    AActor actor; USceneComponent body{"base_link"};
    LogMarsLidarPoseIfRequested(nullptr, 1700000000.1, 42); assert(logs.empty());
    actor.components = {&body};
    LogMarsLidarPoseIfRequested(&actor, 1700000000.1, 42); assert(logs.empty());
    actor.tagged = true;
    LogMarsLidarPoseIfRequested(&actor, 1700000000.1, 42);
    assert(logs.size() == 1 && logs[0].find("MARS_LIDAR_POSE:") != std::string::npos);
    assert(logs[0].find("\"frame_id\":\"42\"") != std::string::npos);
    assert(logs[0].find("\"pitch\":1.500000000") != std::string::npos);
    actor.components = {&body, &body};
    LogMarsLidarPoseIfRequested(&actor, 1700000000.1, 42);
    assert(logs.size() == 2 && logs[1].find("duplicate") != std::string::npos);
    actor.components.clear();
    LogMarsLidarPoseIfRequested(&actor, 1700000000.1, 42);
    assert(logs.size() == 3 && logs[2].find("not found") != std::string::npos);
}
'''
        with tempfile.TemporaryDirectory() as tmp:
            source, binary = Path(tmp) / "pose.cpp", Path(tmp) / "pose-test"
            source.write_text(prefix + cpp_helper_body() + suffix, encoding="utf-8")
            subprocess.run([compiler, "-std=c++17", str(source), "-o", str(binary)], check=True,
                           capture_output=True, text=True, timeout=30)
            subprocess.run([str(binary)], check=True, capture_output=True, text=True, timeout=5)


if __name__ == "__main__":
    unittest.main()
