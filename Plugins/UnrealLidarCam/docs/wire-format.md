# Wire format

One packet per scan, little-endian:

```
'LIDR' | version u8 = 1 | sensor_id u8 | flags u16 (bit 0: organized)
frame_id u64 | stamp f64 (shared simulation-clock seconds since Unix epoch) | horizontal_fov f32 | vertical_fov f32
columns u32 | rows u32 | point_count u32 | point_step u32 = 20
points: x f32 | y f32 | z f32 | intensity f32 | ring u16 | column u16
```

The packed header is 48 bytes. `stamp` comes from `GncSimTime::Now`, not
`World->GetTimeSeconds()` alone. It shares the NAVF v2 camera/rover `t_ns`
clock; f64 conversion can lose sub-microsecond precision at the present epoch.
XYZ are already **sensor-frame FLU metres**. Do not apply the global Unreal
X mirror to these local coordinates a second time. Apply the measured
sensor-to-body transform and the body pose at capture time.

The point layout is the PointCloud2 layout, so the ROS side republishes a scan
without touching each point. The socket is non-blocking; a full send buffer
waits for room, only a real error drops the link (redialled every 3 s). If the
link is slower than the scans, scans are dropped rather than queued.
