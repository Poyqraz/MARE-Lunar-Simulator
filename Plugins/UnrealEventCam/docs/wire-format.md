# Wire format and ROS

## Wire format

TCP, little-endian, one packet per frame **that produced events** (frames with
no events send nothing). A 24-byte header, then `count` 9-byte records:

```
header  'EVT0' | ver u8 | cam_id u8 | width u16 | height u16
        | t0_ns u64 | count u32 | pad u16
event   x u16 | y u16 | t_rel_ns u32 | pol u8      (pol: 1 = +, 0 = -)
```

Each event's absolute timestamp is `t0_ns + t_rel_ns`. Events within a packet
are sorted by time.

## Consuming the events in ROS

`component_event_camera` in
[GNC-Moon-Simulator](https://github.com/raulcastar/GNC-Moon-Simulator) listens on
`ServerPort` (3005), reads the 24-byte header then `count × 9` bytes, and
publishes a rolling event-frame image (colour by polarity) on
`event_camera/image_events` and the event rate on `event_camera/event_rate`.
Any other consumer can do the same, e.g. republish the events as
[`dvs_msgs/EventArray`](https://github.com/uzh-rpg/rpg_dvs_ros).
