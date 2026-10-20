# Wire format

## Wire format

One packet per frame, little-endian, 32-byte header (version 2):

```
'NAVF' | ver u8 = 2 | cam_id u8 | format u8 | pad u8
width u16 | height u16 | frame_id u64 | payload u32 | stamp_ns u64 | pixels (w*h*4)
```

`stamp_ns` is the capture time on the simulation clock (UnrealSimClock: ns since
the Unix epoch), the same for every capture of one tick; the stereo node stamps
everything it publishes from it. Version 1 (24-byte header, no `stamp_ns`) is
still read; its frames are stamped on arrival. The time comes from the plugin's
own `GncSimTime.h` (see [UnrealSimClock](https://github.com/raulcastar/UnrealSimClock/blob/main/docs/sim-time.md)); no other plugin is needed.

`format` 1 is BGRA8 colour; 2 is R32F depth (float32 centimetres of planar
depth, the ground-truth depth above). Both use 4 bytes per pixel.

The socket is non-blocking: when a pump's frames exceed the send buffer, the
sender waits for room and continues; only a real socket error drops the link
(it then redials every 3 s).

## Version notes

Developed and tested with Unreal Engine 5.7, using the RHI readback API
(`FRHIGPUTextureReadback`) that UE 4.26 and later provide. If your
engine version complains about `Lock(int32&)`, the signature varies slightly
across versions (`void* Lock(int32& OutRowPitchInPixels)` vs a `uint32`
variant) — adjust the one call in `PollReadbacks`.
