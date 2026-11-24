"""Exercise the real stereo tick's cadence with a lightweight C++ camera double.

This is not an Unreal build or a GPU/readback acceptance test.
"""

from pathlib import Path
import shutil
import subprocess

import pytest


def method_body(name):
    root = Path(__file__).resolve().parents[1]
    source = (root / "Plugins/UnrealStereoCam/Source/UnrealStereoCam/Private/UnrealStereoCam.cpp").read_text()
    start = source.index(f"void UUnrealStereoCam::{name}(")
    opening = source.index("{", start)
    depth = 0
    for end in range(opening, len(source)):
        depth += (source[end] == "{") - (source[end] == "}")
        if depth == 0:
            return source[opening : end + 1]
    raise AssertionError(f"Could not find the end of {name}")


def compile_and_run(tmp_path, code):
    compiler = shutil.which("g++") or shutil.which("clang++")
    if compiler is None:
        pytest.skip("A C++ compiler is not available for the isolated stereo test")
    cpp = tmp_path / "stereo.cpp"
    binary = tmp_path / "stereo-test"
    cpp.write_text(code, encoding="utf-8")
    subprocess.run([compiler, "-std=c++17", str(cpp), "-o", str(binary)], check=True, timeout=30,
                   capture_output=True, text=True)
    subprocess.run([str(binary)], check=True, timeout=5, capture_output=True, text=True)


def test_tick_polls_completed_readbacks_without_increasing_capture_rate(tmp_path):
    prefix = r"""
#include <algorithm>
#include <cassert>
#include <utility>
#include <vector>
enum ELevelTick { LEVELTICK_All };
struct FActorComponentTickFunction {};
struct FMath { template<class T> static T Max(T a, T b) { return std::max(a, b); } };
struct MockWorld { double now = 0; double GetTimeSeconds() const { return now; } };
struct MockStream { bool IsValid() const { return true; } };
struct MockCapture { void* TextureTarget = this; int captures = 0; void CaptureScene() { ++captures; } };
struct FStereoCamResolved { MockCapture* Capture; };
struct MockBase { void TickComponent(float, ELevelTick, FActorComponentTickFunction*) {} };
class MockCamera : public MockBase {
public:
    using Super = MockBase;
    bool bConnected = true, bCaptureOnDemand = true;
    MockStream Stream;
    MockWorld world;
    float SendHz = 5.0f;
    double LastSendTime = 0;
    std::vector<FStereoCamResolved> Active;
    std::vector<int> submitted;
    std::vector<std::pair<int,int>> completed;
    int tick = 0, polls = 0, pending = -1;
    MockWorld* GetWorld() { return &world; }
    void PumpCaptures(bool start) {
        ++polls;
        if (pending >= 0 && tick > pending) {
            completed.emplace_back(pending, tick);
            pending = -1;
        }
        if (start) { submitted.push_back(tick); pending = tick; }
    }
    void TickComponent(float DeltaTime, ELevelTick TickType, FActorComponentTickFunction* ThisTickFunction);
};
void MockCamera::TickComponent(float DeltaTime, ELevelTick TickType, FActorComponentTickFunction* ThisTickFunction)
"""
    suffix = r"""
int main() {
    MockCamera camera;
    MockCapture capture;
    camera.Active.push_back({&capture});
    for (int i = 0; i <= 30; ++i) {
        camera.tick = i;
        camera.world.now = i / 30.0;
        camera.TickComponent(1.0f / 30.0f, LEVELTICK_All, nullptr);
    }
    assert(camera.polls == 31);
    assert(camera.submitted.size() >= 4 && camera.submitted.size() <= 5);
    assert(capture.captures == static_cast<int>(camera.submitted.size()));
    assert(!camera.completed.empty());
    assert(camera.completed[0].second == camera.submitted[0] + 1);
    assert(camera.completed[0].second < camera.submitted[1]);
    const int polls = camera.polls;
    camera.bConnected = false;
    camera.TickComponent(0.03f, LEVELTICK_All, nullptr);
    assert(camera.polls == polls);

    MockCamera reset;
    reset.LastSendTime = 5.0;
    reset.world.now = 0.0;
    reset.TickComponent(0.03f, LEVELTICK_All, nullptr);
    assert(reset.polls == 1 && reset.submitted.size() == 1);

    MockCamera automatic;
    MockCapture other;
    automatic.Active.push_back({&other});
    automatic.bCaptureOnDemand = false;
    automatic.world.now = 0.2;
    automatic.TickComponent(0.03f, LEVELTICK_All, nullptr);
    assert(automatic.submitted.size() == 1 && other.captures == 0);
}
"""
    compile_and_run(tmp_path, prefix + method_body("TickComponent") + suffix)


def test_poll_drains_original_capture_without_starting_another_readback(tmp_path):
    prefix = r"""
#include <cassert>
#include <cstdint>
#include <cstring>
#include <memory>
#include <utility>
#include <vector>
using int32 = int32_t; using int64 = int64_t;
using uint8 = uint8_t; using uint16 = uint16_t; using uint32 = uint32_t; using uint64 = uint64_t;
template<class T> struct TArray : std::vector<T> {
    int32 Num() const { return static_cast<int32>(this->size()); }
    void Add(T value) { this->push_back(std::move(value)); }
    void SetNumUninitialized(size_t n) { this->resize(n); }
    T* GetData() { return this->data(); }
    void RemoveAt(int32 i) { this->erase(this->begin() + i); }
};
template<class T> using TUniquePtr = std::unique_ptr<T>;
enum class ESPMode { ThreadSafe };
template<class T, ESPMode> using TSharedPtr = std::shared_ptr<T>;
template<class T, class... A> TUniquePtr<T> MakeUnique(A&&... a) {
    return std::make_unique<T>(std::forward<A>(a)...);
}
#define MoveTemp(x) std::move(x)
#define TEXT(x) x
struct FRHICommandListImmediate {};
struct MockEnqueue { template<class F> void operator()(F f) { FRHICommandListImmediate cmd; f(cmd); } };
#define ENQUEUE_RENDER_COMMAND(name) MockEnqueue()
bool gpu_ready = false;
int copies = 0;
struct FRHIGPUTextureReadback {
    uint32 pixels[4] = {1, 2, 3, 4};
    explicit FRHIGPUTextureReadback(const char*) {}
    bool IsReady() const { return gpu_ready; }
    void* Lock(int32& pitch) { pitch = 2; return pixels; }
    void Unlock() {}
    void EnqueueCopy(FRHICommandListImmediate&, void*) { ++copies; }
};
struct FMemory { static void Memcpy(void* a, const void* b, size_t n) { std::memcpy(a,b,n); } };
struct FTextureRenderTargetResource { void* GetRenderTargetTexture() { return this; } };
struct MockTexture {
    int32 SizeX = 2, SizeY = 2;
    FTextureRenderTargetResource resource;
    FTextureRenderTargetResource* GameThread_GetRenderTargetResource() { return &resource; }
};
struct MockCapture { MockTexture* TextureTarget; };
struct FStereoCamResolved { MockCapture* Capture; int32 CamId; uint8 Format; };
struct FStereoCamCap { FTextureRenderTargetResource* Resource; int32 CamId; uint8 Format; int32 W, H; };
struct FPendingReadback {
    TUniquePtr<FRHIGPUTextureReadback> Readback;
    int32 CamId = 0, Width = 0, Height = 0;
    uint8 Format = 1;
    uint64 FrameId = 0;
    int64 StampNs = 0;
};
struct MockReady {
    std::vector<TArray<uint8>> packets;
    void Enqueue(TArray<uint8> packet) { packets.push_back(std::move(packet)); }
};
struct FStereoCamStreamState { TArray<FPendingReadback> Pending; MockReady Ready; };
#pragma pack(push, 1)
struct FNavFrameHeader {
    uint8 Magic[4], Version, CamId, Format, Reserved;
    uint16 Width, Height;
    uint64 FrameId;
    uint32 PayloadSize;
    uint64 StampNs;
};
#pragma pack(pop)
uint64 GFrameCounter = 100;
int64 capture_stamp = 1700000000000000100LL;
namespace GncSimTime { int64 NowNs(const void*) { return capture_stamp; } }
class MockCamera {
public:
    TArray<FStereoCamResolved> Active;
    TSharedPtr<FStereoCamStreamState, ESPMode::ThreadSafe> Stream = std::make_shared<FStereoCamStreamState>();
    void PumpCaptures(bool bStartReadbacks);
};
void MockCamera::PumpCaptures(bool bStartReadbacks)
"""
    suffix = r"""
int main() {
    MockCamera camera;
    MockTexture texture;
    MockCapture capture{&texture};
    camera.Active.Add({&capture, 4, 2});
    camera.PumpCaptures(true);
    assert(copies == 1 && camera.Stream->Pending.Num() == 1 && camera.Stream->Ready.packets.empty());
    camera.PumpCaptures(false);
    assert(copies == 1 && camera.Stream->Pending.Num() == 1 && camera.Stream->Ready.packets.empty());
    camera.Active.clear();
    gpu_ready = true;
    ++GFrameCounter;
    capture_stamp += 100000000;
    camera.PumpCaptures(false);
    assert(copies == 1 && camera.Stream->Pending.Num() == 0 && camera.Stream->Ready.packets.size() == 1);
    auto& packet = camera.Stream->Ready.packets[0];
    auto* header = reinterpret_cast<FNavFrameHeader*>(packet.GetData());
    assert(header->Version == 2 && header->CamId == 4 && header->Format == 2);
    assert(header->FrameId == 100 && header->StampNs == 1700000000000000100ULL);
    assert(header->Width == 2 && header->Height == 2 && header->PayloadSize == 16);
    camera.PumpCaptures(false);
    assert(copies == 1 && camera.Stream->Ready.packets.size() == 1);
}
"""
    compile_and_run(tmp_path, prefix + method_body("PumpCaptures") + suffix)
