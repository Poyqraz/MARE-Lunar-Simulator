# In ROS

`component_lidar` (`config/params.yaml`: `bind_ip`, `port`, `topic`, `frame_id`) publishes each scan on **`lidar/points`**, frame `lidar`:

- organized: height = channels, width = columns; row 0 is the top channel,
  column 0 the leftmost beam;
- fields `x`, `y`, `z`, `intensity` (float32) and `ring`, `column` (uint16);
- sensor frame with the ROS convention (x forward, y left, z up), metres;
- NaN coordinates where a beam returns nothing (`is_dense` = false).

It replaces MetaLidar (the Velodyne VLP-16 over UDP), which the simulator no
longer uses.
