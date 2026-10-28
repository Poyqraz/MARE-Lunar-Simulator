// UnrealStereoCam: streams stereo/navcam frames to ROS without stalling the game.
//
// The captures render on the render thread, their readback is asynchronous
// (FRHIGPUTextureReadback, polled until ready, never flushed), and finished
// frames go out over TCP from a worker thread. The game thread only queues work.
//
// All captures enqueued in one tick share a frame id (GFrameCounter), which is
// what lets the ROS side pair left/right images from the same world state.
//
// Wire format, little-endian, one packet per frame:
//   offset size  field
//   0      4     magic 'NAVF'
//   4      1     version = 2
//   5      1     cam_id            (matches ids in component_stereo_depth params)
//   6      1     format            1 = BGRA8 colour, 2 = R32F depth: centimetres along
//                                  the camera axis (Unreal scene depth); payload =
//                                  width*height*4 either way
//   7      1     reserved
//   8      2     width  (u16)
//   10     2     height (u16)
//   12     8     frame_id (u64)    (GFrameCounter at capture)
//   20     4     payload size (u32)
//   24     8     stamp_ns (u64)    capture time: simulation time (GncSimTime.h),
//                                  ns since the Unix epoch
//   32     ...   pixels
// (Version 1 had no stamp_ns; its pixels started at offset 24.)

#pragma once

#include "CoreMinimal.h"
#include "Components/ActorComponent.h"
#include "Components/SceneCaptureComponent2D.h"
#include "Engine/EngineTypes.h"
#include "Engine/Scene.h"
#include "Engine/TextureRenderTarget2D.h"
#include "RHIGPUReadback.h"
#include "HAL/Runnable.h"
#include "HAL/RunnableThread.h"
#include "HAL/ThreadSafeBool.h"
#include "Containers/Queue.h"
#include "UnrealStereoCam.generated.h"

class FSocket;

// A capture resolved and validated at BeginPlay, ready to stream.
USTRUCT()
struct UNREALSTEREOCAM_API FStereoCamResolved
{
	GENERATED_BODY()

	UPROPERTY(Transient)
	USceneCaptureComponent2D* Capture = nullptr;

	int32 CamId = 0;
	uint8 Format = 1;               // Wire format: 1 BGRA8, 2 R32F depth
};

// One in-flight asynchronous readback. Touched only on the render thread.
struct FPendingReadback
{
	TUniquePtr<FRHIGPUTextureReadback> Readback;
	int32 CamId = 0;
	uint8 Format = 1;
	int32 Width = 0;
	int32 Height = 0;
	uint64 FrameId = 0;
	int64 StampNs = 0;              // Capture time, simulation clock
};

// Shared by the component, the in-flight render commands and the sender thread
// through a ref-counted pointer, so teardown never has to block:
//   - Pending: readbacks, created, polled, locked and freed only on the render
//     thread (touching them from another thread is unsafe).
//   - Ready: lock-free handoff of finished frames, render thread -> sender.
// The last holder frees it, and with it the readbacks; for an in-flight render
// command that is the render thread. No FlushRenderingCommands or fence needed.
struct FStereoCamStreamState
{
	TArray<FPendingReadback> Pending;                      // render thread only
	TQueue<TArray<uint8>, EQueueMode::Mpsc> Ready;         // render -> sender
};

UCLASS(ClassGroup = (Custom), meta = (BlueprintSpawnableComponent))
class UNREALSTEREOCAM_API UUnrealStereoCam : public UActorComponent, public FRunnable
{
	GENERATED_BODY()

public:
	UUnrealStereoCam();

	// Where the ROS stereo node listens (see stream_port in its params.yaml).
	UPROPERTY(EditAnywhere, Category = "StereoCam|Network")
	FString ServerIp = TEXT("127.0.0.1");

	UPROPERTY(EditAnywhere, Category = "StereoCam|Network")
	int32 ServerPort = 3004;

	// Frames per simulated (game) second sent to ROS, so the rate holds when the
	// editor runs below real time. Keep it slightly above the rate the ROS node
	// consumes: the receiver still parses every extra frame (about 3.7 MB/s per
	// Hz for three 640x480 cameras).
	UPROPERTY(EditAnywhere, Category = "StereoCam", meta = (ClampMin = "0.5", ClampMax = "30"))
	float SendHz = 2.0f;

	// Render the captures only when a frame is sent (SendHz) instead of every
	// engine frame, saving a full scene render per camera on the other frames.
	// The captures keep their rendering state (exposure, temporal AA, Lumen)
	// between renders.
	UPROPERTY(EditAnywhere, Category = "StereoCam")
	bool bCaptureOnDemand = true;

	// The three navcam SceneCapture2Ds, chosen by name from every SceneCapture2D
	// in reach (this Blueprint's components, or the world when placed in a
	// level). Names rather than object pointers, because the details panel
	// cannot point a component property at a per-instance component. Resolved
	// at BeginPlay, with a log line per camera.
	UPROPERTY(EditAnywhere, Category = "StereoCam|Cameras",
	          meta = (GetOptions = "GetSceneCaptureNames"))
	FName LeftCaptureName = TEXT("NavcamLeft");

	UPROPERTY(EditAnywhere, Category = "StereoCam|Cameras",
	          meta = (GetOptions = "GetSceneCaptureNames"))
	FName RightCaptureName = TEXT("NavcamRight");

	UPROPERTY(EditAnywhere, Category = "StereoCam|Cameras",
	          meta = (GetOptions = "GetSceneCaptureNames"))
	FName CenterCaptureName = TEXT("NavcamCenter");

	// Optional object-mask capture: a SceneCapture whose post-process material
	// colours each object from the Custom Depth-Stencil buffer. Blank streams no
	// mask. It shares the cameras' frame id, so ROS can overlay it on the
	// central image; the colours come entirely from the material.
	UPROPERTY(EditAnywhere, Category = "StereoCam|Cameras",
	          meta = (GetOptions = "GetSceneCaptureNames"))
	FName MaskCaptureName;

	// Also stream the central camera's ground-truth depth: a depth-only capture
	// created at BeginPlay with the central camera's pose, FOV and size. Each
	// pixel is Unreal's scene depth (cm along the camera axis), sent as float
	// (format 2) on DepthCamId.
	UPROPERTY(EditAnywhere, Category = "StereoCam|Cameras")
	bool bStreamCenterDepth = true;

	// Also stream the central camera without glare: a colour capture created at
	// BeginPlay with the central camera's pose, FOV, size and post-process
	// settings, but no bloom and no lens flares, sent on NoGlareCamId. Same
	// frame id as the other cameras. Costs one more scene render per frame.
	UPROPERTY(EditAnywhere, Category = "StereoCam|Cameras")
	bool bStreamCenterNoGlare = false;

	// Options for the dropdowns above.
	UFUNCTION()
	TArray<FString> GetSceneCaptureNames() const;

	// Size of the RGBA8 render target created for a capture that has none. All
	// stereo captures must share one size: the ROS node rejects mismatched frames.
	UPROPERTY(EditAnywhere, Category = "StereoCam|Cameras")
	int32 CaptureWidth = 640;

	UPROPERTY(EditAnywhere, Category = "StereoCam|Cameras")
	int32 CaptureHeight = 480;

	// Use manual exposure (AEM_Manual) instead of auto-exposure, so both eyes
	// expose identically and saturation is not adapted away (e.g. glare
	// studies). ExposureCompensationEV then sets the brightness: 0 neutral,
	// positive brighter, negative darker.
	UPROPERTY(EditAnywhere, Category = "StereoCam|Cameras")
	bool bLockExposure = false;

	UPROPERTY(EditAnywhere, Category = "StereoCam|Cameras",
	          meta = (EditCondition = "bLockExposure"))
	float ExposureCompensationEV = 0.0f;

	// Clamp the auto-exposure range (EV100), so a dim scene is neither blown to
	// white nor crushed to black. Equal values pin one exposure on both eyes.
	// Sets the captures' Min/Max EV100 post-process overrides; ignored with
	// bLockExposure.
	UPROPERTY(EditAnywhere, Category = "StereoCam|Cameras")
	bool bLimitAutoExposure = false;

	UPROPERTY(EditAnywhere, Category = "StereoCam|Cameras",
	          meta = (EditCondition = "bLimitAutoExposure", DisplayName = "Min EV100"))
	float MinEV100 = -2.0f;

	UPROPERTY(EditAnywhere, Category = "StereoCam|Cameras",
	          meta = (EditCondition = "bLimitAutoExposure", DisplayName = "Max EV100"))
	float MaxEV100 = 4.0f;

	// Ids the ROS side knows the cameras by (left/right/center_camera_id in
	// component_stereo_depth/config/params.yaml). Defaults match its defaults.
	UPROPERTY(EditAnywhere, AdvancedDisplay, Category = "StereoCam|Cameras")
	int32 LeftCamId = 1;

	UPROPERTY(EditAnywhere, AdvancedDisplay, Category = "StereoCam|Cameras")
	int32 RightCamId = 2;

	UPROPERTY(EditAnywhere, AdvancedDisplay, Category = "StereoCam|Cameras")
	int32 CenterCamId = 0;

	// Must match mask_camera_id in component_stereo_depth/config/params.yaml.
	UPROPERTY(EditAnywhere, AdvancedDisplay, Category = "StereoCam|Cameras")
	int32 MaskCamId = 3;

	// Must match depth_ground_truth_camera_id in that file.
	UPROPERTY(EditAnywhere, AdvancedDisplay, Category = "StereoCam|Cameras")
	int32 DepthCamId = 4;

	// The glare-free central camera (bStreamCenterNoGlare); an extra_cameras
	// entry in that file publishes it.
	UPROPERTY(EditAnywhere, AdvancedDisplay, Category = "StereoCam|Cameras")
	int32 NoGlareCamId = 5;

	virtual void BeginPlay() override;
	virtual void EndPlay(const EEndPlayReason::Type Reason) override;
	virtual void TickComponent(float DeltaTime, ELevelTick TickType,
	                           FActorComponentTickFunction* ThisTickFunction) override;

	// FRunnable: the sender thread drains the packet queue into the socket.
	virtual uint32 Run() override;
	virtual void Stop() override;

private:
	void ResolveCapture(const FName& Name, int32 CamId);

	// Creates the centre camera's depth capture (bStreamCenterDepth).
	void AddCenterDepthCapture();

	// Creates the centre camera's glare-free twin (bStreamCenterNoGlare).
	void AddCenterNoGlareCapture();

	// Posts one render command per send: it moves finished readbacks to Ready,
	// then starts this send's readbacks. The game thread never locks, waits on
	// or frees a readback.
	void PumpCaptures();

	// Sender thread only, like all socket I/O: a blocking connect on the game
	// thread would freeze the editor for the OS TCP timeout. Non-blocking, with
	// a bounded wait, so EndPlay's join of the thread stays short too.
	bool TryConnect();

	// Captures found by name at BeginPlay.
	UPROPERTY(Transient)
	TArray<FStereoCamResolved> Active;

	FSocket* Socket = nullptr;                  // Run()'s thread only.
	FRunnableThread* SenderThread = nullptr;
	FThreadSafeBool bStopSender = false;
	// The only socket state the game thread may read. Set/cleared by Run().
	FThreadSafeBool bConnected = false;

	double LastConnectAttempt = 0.0;             // Run()'s thread only.
	bool bLoggedWaiting = false;                 // Run()'s thread only.

	// Readback + ready-frame state, shared with render commands and the sender
	// thread. Created in BeginPlay, released (not blocked-on) in EndPlay.
	TSharedPtr<FStereoCamStreamState, ESPMode::ThreadSafe> Stream;

	double LastSendTime = 0.0;
};
