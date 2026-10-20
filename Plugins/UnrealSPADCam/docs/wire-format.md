# Wire format

TCP, little-endian, one packet per sampled frame: a 24-byte header then the
8-bit grayscale image (row-major, `width*height` bytes).

```
'SPD0' | ver u8 | cam_id u8 | width u16 | height u16
       | t_ns u64 | payload u32 (= width*height) | pad u16
```

`component_spad_camera` reads this, runs the spadSim photon model per frame, and
publishes the single-photon binary frames plus a digitised reconstruction.
