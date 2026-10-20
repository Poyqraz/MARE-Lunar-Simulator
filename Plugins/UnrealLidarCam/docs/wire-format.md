# Wire format

One packet per scan, little-endian:

```
'LIDR' | version u8 = 1 | sensor_id u8 | flags u16 (bit 0: organized)
frame_id u64 | stamp f64 (world seconds) | horizontal_fov f32 | vertical_fov f32
columns u32 | rows u32 | point_count u32 | point_step u32 = 20
points: x f32 | y f32 | z f32 | intensity f32 | ring u16 | column u16
```

The point layout is the PointCloud2 layout, so the ROS side republishes a scan
without touching each point. The socket is non-blocking; a full send buffer
waits for room, only a real error drops the link (redialled every 3 s). If the
link is slower than the scans, scans are dropped rather than queued.
