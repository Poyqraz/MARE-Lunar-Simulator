"""
extract.py: turns the episode rosbags into dataset samples.

    python extract.py --config config.yaml          # every recorded episode not extracted yet

Each sample is one navigation-camera frame: the central, left and right RGB
images, the central camera's ground-truth depth, object mask and shadow label
(same rendered frame), and the event and SPAD images, lidar scan and odometry
nearest in time. The lidar scan is also projected into the central camera as a
sparse depth image (corrected for the rover's motion between the two stamps),
and preview/ holds colour copies of depth, lidar depth and masks for viewing.
When the bag has them, the glare-free copy of the central image (same rendered
frame) and the rear camera with its object mask and shadow label (nearest in
time) are written too. Frames are kept once the rover has moved min_spacing_m, or max_gap_s of
simulation time has passed, so consecutive samples are not near-duplicates.

Two passes per bag: the first reads only header stamps (a few bytes of each
message) to choose the frames, the second decodes only the chosen ones.
"""
import argparse
import bisect
import csv
import glob
import json
import os
import shutil
import struct

import numpy as np
from PIL import Image

from mcap.reader import make_reader
from mcap_ros2.decoder import DecoderFactory

CENTRAL = "/navcam/central/image_color"
EXACT = {  # same rendered frame as the central image (matched within 20 ms)
    "rgb_left": "/navcam/left/image_color",
    "rgb_right": "/navcam/right/image_color",
    "depth": "/navcam/central/depth_ground_truth",
    "object": "/navcam/central/object_mask",
    "shadow": "/navcam/central/shadow_label",
}
NEAREST = {"events": "/event_camera/image_events", "spad": "/spad/image"}
NOGLARE = "/navcam/central_noglare/image_color"          # optional: the central image without bloom or lens flares
REAR = "/rear_cam/image_color"                          # optional: the rear camera ...
REAR_MASKS = {"rear_object": "/rear_cam/object_mask",    # ... and its labels (same rendered frame as it)
              "rear_shadow": "/rear_cam/shadow_label"}
LIDAR = "/lidar/points"
CAMERA_FRAME = "navcam_central"
PREVIEW_DEPTH_M = (0.5, 60.0)                          # log colour scale of the depth previews (near red, far blue)
SHADOW_PALETTE = {0: (0, 0, 0), 1: (40, 120, 255), 2: (0, 0, 0),   # as the dashboard's shadow feed
                  3: (128, 128, 128), 4: (0, 0, 0), 5: (255, 140, 0)}
INFO = {"central": "/navcam/central/camera_info", "left": "/navcam/left/camera_info",
        "right": "/navcam/right/camera_info", "rear": "/rear_cam/camera_info"}
LEGENDS = {"object_mask_classes": "/navcam/central/object_mask_classes",
           "shadow_label_mapping": "/navcam/central/shadow_label_mapping",
           "rear_object_mask_classes": "/rear_cam/object_mask_classes"}
SAME_FRAME_S = 0.02


def _stamp(raw):
    """Header stamp of a CDR-serialized message whose first field is a std_msgs/Header."""
    sec, nsec = struct.unpack_from("<iI", raw, 4)
    return sec + 1e-9 * nsec


def _matrix(t, q):
    """4x4 transform from a translation (x, y, z) and a quaternion (x, y, z, w)."""
    x, y, z, w = q
    m = np.eye(4)
    m[:3, :3] = [[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                 [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                 [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]]
    m[:3, 3] = t
    return m


def _static_chain(static, frame, root="base_link"):
    """root <- frame transform through the static tf tree (static: child -> (parent, matrix))."""
    m = np.eye(4)
    while frame != root:
        parent, t = static[frame]
        m, frame = t @ m, parent
    return m


def _cloud(msg):
    """Organised PointCloud2 (x, y, z, intensity float32) -> (rows, columns, 4) float32, NaN = no return."""
    off = {f.name: f.offset for f in msg.fields}
    raw = np.frombuffer(bytes(msg.data), np.uint8).reshape(msg.height, msg.row_step)[:, :msg.width * msg.point_step]
    pts = raw.reshape(msg.height, msg.width, msg.point_step)
    return np.stack([np.ascontiguousarray(pts[:, :, off[k]:off[k] + 4]).view("<f4")[:, :, 0]
                     for k in ("x", "y", "z", "intensity")], axis=-1)


def _project(points_cam, K, shape):
    """Points in the camera's optical frame -> sparse depth image (metres, 0 = no point; nearest wins)."""
    p = points_cam[np.isfinite(points_cam).all(axis=1) & (points_cam[:, 2] > 0.05)]
    u = np.floor(K[0] * p[:, 0] / p[:, 2] + K[2]).astype(int)
    v = np.floor(K[4] * p[:, 1] / p[:, 2] + K[5]).astype(int)
    ok = (u >= 0) & (u < shape[1]) & (v >= 0) & (v < shape[0])
    u, v, z = u[ok], v[ok], p[ok, 2]
    order = np.argsort(-z)                              # far first, so the nearest point is written last
    depth = np.zeros(shape, np.float32)
    depth[v[order], u[order]] = z[order]
    return depth


def _jet(values, near_far=PREVIEW_DEPTH_M):
    """Depth -> JET rgb8 on a log scale (near red, far blue); non-finite and 0 black."""
    near, far = near_far
    v = np.clip(np.nan_to_num(values, nan=near, posinf=far), near, far)
    x = 1.0 - np.log(v / near) / np.log(far / near)
    rgb = np.stack([np.clip(1.5 - np.abs(4 * x - c), 0, 1) for c in (3, 2, 1)], axis=-1)
    rgb = (rgb * 255).astype(np.uint8)
    rgb[~(np.isfinite(values) & (values > 0))] = 0
    return rgb


def _image(msg):
    h, w, enc = msg.height, msg.width, msg.encoding
    data = np.frombuffer(bytes(msg.data), np.uint8)
    if enc in ("rgb8", "bgr8"):
        img = data.reshape(h, msg.step)[:, :3 * w].reshape(h, w, 3)
        return img[:, :, ::-1] if enc == "bgr8" else img
    if enc in ("rgba8", "bgra8"):
        img = data.reshape(h, msg.step)[:, :4 * w].reshape(h, w, 4)[:, :, :3]
        return img[:, :, ::-1] if enc == "bgra8" else img
    if enc == "mono8":
        return data.reshape(h, msg.step)[:, :w]
    if enc == "32FC1":
        return np.frombuffer(bytes(msg.data), "<f4").reshape(h, msg.step // 4)[:, :w]
    raise ValueError(f"unsupported encoding {enc}")


class Stamps:
    """A topic's stamps in recording order, searchable by time."""

    def __init__(self, values):
        self.values = list(values)                      # recording order (the second pass counts in it)
        self.order = sorted(range(len(self.values)), key=self.values.__getitem__)
        self.sorted = [self.values[i] for i in self.order]

    def nearest(self, t, tol):
        """Recording-order index of the stamp nearest t, or None if none is within tol."""
        i = bisect.bisect_left(self.sorted, t)
        best = min((j for j in (i - 1, i) if 0 <= j < len(self.sorted)),
                   key=lambda j: abs(self.sorted[j] - t), default=None)
        return self.order[best] if best is not None and abs(self.sorted[best] - t) <= tol else None


def _object_ids(rgb, classes):
    """Object-mask colours (flag bits cleared) to class ids; unknown colours get 0."""
    key = (rgb[:, :, 0].astype(np.uint32) << 16) | (rgb[:, :, 1].astype(np.uint32) << 8) | rgb[:, :, 2]
    ids = np.zeros(key.shape, np.uint8)
    for c in classes:
        r, g, b = c["rgb"]
        ids[key == ((r << 16) | (g << 8) | b)] = c["id"]
    return ids


def _scan(path):
    """First pass: stamps of every image topic, odometry poses, intrinsics and legends."""
    stamps = {t: [] for t in [CENTRAL, *EXACT.values(), *NEAREST.values(), LIDAR, NOGLARE, REAR,
                              *REAR_MASKS.values()]}
    odom, info, legends, static = [], {}, {}, {}
    decoder = DecoderFactory()
    with open(path, "rb") as f:
        reader = make_reader(f, decoder_factories=[decoder])
        for schema, channel, message in reader.iter_messages():
            topic = channel.topic
            if topic in stamps:
                stamps[topic].append(_stamp(message.data))
            elif topic in ("/odom", "/tf_static") or topic in INFO.values() or topic in LEGENDS.values():
                msg = decoder.decoder_for(channel.message_encoding, schema)(message.data)
                if topic == "/tf_static":
                    for tf in msg.transforms:
                        t, q = tf.transform.translation, tf.transform.rotation
                        static[tf.child_frame_id] = (tf.header.frame_id,
                                                     _matrix((t.x, t.y, t.z), (q.x, q.y, q.z, q.w)))
                elif topic == "/odom":
                    p, q = msg.pose.pose.position, msg.pose.pose.orientation
                    odom.append((_stamp(message.data), p.x, p.y, p.z, q.x, q.y, q.z, q.w))
                elif topic in INFO.values():
                    name = next(k for k, v in INFO.items() if v == topic)
                    info.setdefault(name, {"width": msg.width, "height": msg.height, "K": list(msg.k),
                                           "P": list(msg.p), "frame_id": msg.header.frame_id})
                else:
                    name = next(k for k, v in LEGENDS.items() if v == topic)
                    legends.setdefault(name, json.loads(msg.data))
    odom.sort()
    return {topic: Stamps(v) for topic, v in stamps.items()}, odom, info, legends, static


def _select(stamps, odom, fcfg):
    """Central-camera stamps to keep: complete frames, spaced in distance or time."""
    tol = fcfg["pair_tolerance_s"]
    odom_stamps = Stamps(o[0] for o in odom)          # odom is sorted: indices match
    chosen, last_t, last_p = [], None, None
    for i in stamps[CENTRAL].order:                    # in time order
        t = stamps[CENTRAL].values[i]
        if any(stamps[topic].nearest(t, SAME_FRAME_S) is None for topic in EXACT.values()):
            continue
        j = odom_stamps.nearest(t, tol)
        if j is None:
            continue
        p = np.array(odom[j][1:4])
        if last_t is None or np.linalg.norm(p - last_p) >= fcfg["min_spacing_m"] or t - last_t >= fcfg["max_gap_s"]:
            chosen.append((i, t, j))
            last_t, last_p = t, p
    return chosen


def extract_episode(bag_dir, out_dir, fcfg, episode_meta):
    """Writes the samples of one episode bag to out_dir. Returns the number of samples."""
    path = glob.glob(os.path.join(bag_dir, "*.mcap"))[0]
    stamps, odom, info, legends, static = _scan(path)
    odom_stamps = Stamps(o[0] for o in odom)
    lidar_tol = fcfg.get("lidar_tolerance_s", 0.2)
    previews = fcfg.get("previews", True)
    chosen = _select(stamps, odom, fcfg)
    tol = fcfg["pair_tolerance_s"]
    optional = {t: bool(stamps[t].values) for t in (NOGLARE, REAR, *REAR_MASKS.values())}
    wanted = {}                                         # topic -> {stamp index -> [frame numbers]}
    rows = []
    for k, (ci, t, j) in enumerate(chosen):
        wanted.setdefault(CENTRAL, {}).setdefault(ci, []).append(k)
        for topic in EXACT.values():
            wanted.setdefault(topic, {}).setdefault(stamps[topic].nearest(t, SAME_FRAME_S), []).append(k)
        row = {"frame": k, "stamp": round(t, 6)}
        for name, topic in NEAREST.items():
            i = stamps[topic].nearest(t, tol)
            row[f"{name}_stamp"] = round(stamps[topic].values[i], 6) if i is not None else ""
            if i is not None:
                wanted.setdefault(topic, {}).setdefault(i, []).append(k)
        i = stamps[LIDAR].nearest(t, lidar_tol)
        row["lidar_stamp"] = round(stamps[LIDAR].values[i], 6) if i is not None else ""
        if i is not None:
            wanted.setdefault(LIDAR, {}).setdefault(i, []).append(k)
        if optional[NOGLARE]:
            i = stamps[NOGLARE].nearest(t, SAME_FRAME_S)
            row["noglare_stamp"] = round(stamps[NOGLARE].values[i], 6) if i is not None else ""
            if i is not None:
                wanted.setdefault(NOGLARE, {}).setdefault(i, []).append(k)
        if optional[REAR]:
            i = stamps[REAR].nearest(t, tol)
            row["rear_stamp"] = round(stamps[REAR].values[i], 6) if i is not None else ""
            if i is not None:
                wanted.setdefault(REAR, {}).setdefault(i, []).append(k)
                t_rear = stamps[REAR].values[i]
                for topic in REAR_MASKS.values():
                    if optional[topic]:
                        m = stamps[topic].nearest(t_rear, SAME_FRAME_S)
                        if m is not None:
                            wanted.setdefault(topic, {}).setdefault(m, []).append(k)
        o = odom[j]
        row.update(dict(zip(("x", "y", "z", "qx", "qy", "qz", "qw"), (round(v, 5) for v in o[1:]))))
        rows.append(row)

    folders = {CENTRAL: "rgb_central", **{t: n for n, t in EXACT.items()}, **{t: n for n, t in NEAREST.items()},
               LIDAR: "lidar", NOGLARE: "rgb_central_noglare", REAR: "rear_rgb",
               **{t: n for n, t in REAR_MASKS.items()}}
    folders = {t: n for t, n in folders.items() if optional.get(t, True)}
    depth_npy = fcfg.get("depth_npy", False)           # the exact float32 metres as well
    extra = ["lidar_depth", "lidar_depth_m"] + (["depth_m"] if depth_npy else [])
    shown = ["depth", "lidar_depth", "object", "shadow"] + [n for n, t in REAR_MASKS.items() if t in folders]
    extra += [f"preview/{n}" for n in shown] if previews else []
    for folder in [*folders.values(), *extra]:
        os.makedirs(os.path.join(out_dir, folder), exist_ok=True)
    cam = info.get("central")
    can_project = cam is not None and CAMERA_FRAME in static and "lidar" in static
    if can_project:
        base_cam_inv = np.linalg.inv(_static_chain(static, CAMERA_FRAME))
        base_lidar = _static_chain(static, "lidar")
    lidar_depth = {}                                    # frame -> lidar depth, for its preview over the RGB
    classes = legends.get("object_mask_classes", [])
    object_topics = {EXACT["object"]: ("object", classes),
                     REAR_MASKS["rear_object"]: ("rear_object", legends.get("rear_object_mask_classes", classes))}
    shadow_topics = {EXACT["shadow"]: "shadow", REAR_MASKS["rear_shadow"]: "rear_shadow"}
    palette = np.zeros((256, 3), np.uint8)
    for sid, rgb in SHADOW_PALETTE.items():
        palette[sid] = rgb
    counters = {t: 0 for t in folders}
    decoder = DecoderFactory()
    with open(path, "rb") as f:
        for schema, channel, message in make_reader(f, decoder_factories=[decoder]).iter_messages(topics=list(folders)):
            topic = channel.topic
            index, counters[topic] = counters[topic], counters[topic] + 1
            frames = wanted.get(topic, {}).get(index)
            if not frames:
                continue
            msg = decoder.decoder_for(channel.message_encoding, schema)(message.data)
            if topic == LIDAR:
                cloud = _cloud(msg)
                t_l = _stamp(message.data)
                for k in frames:
                    np.save(os.path.join(out_dir, "lidar", f"{k:06d}.npy"), cloud)
                    if not can_project:
                        continue
                    # lidar -> base (scan time) -> map -> base (camera time) -> camera
                    near = odom_stamps.nearest(t_l, 1.0)
                    o_l, o_c = odom[chosen[k][2] if near is None else near], odom[chosen[k][2]]
                    m = (base_cam_inv @ np.linalg.inv(_matrix(o_c[1:4], o_c[4:8]))
                         @ _matrix(o_l[1:4], o_l[4:8]) @ base_lidar)
                    xyz = cloud[:, :, :3].reshape(-1, 3)
                    depth = _project(xyz @ m[:3, :3].T + m[:3, 3], cam["K"], (cam["height"], cam["width"]))
                    np.save(os.path.join(out_dir, "lidar_depth_m", f"{k:06d}.npy"), depth)
                    mm = np.where(depth < 65.535, np.round(depth * 1000.0), 0).astype(np.uint16)
                    Image.fromarray(mm).save(os.path.join(out_dir, "lidar_depth", f"{k:06d}.png"))
                    lidar_depth[k] = depth
                continue
            img = _image(msg)
            if previews and topic == EXACT["depth"]:
                for k in frames:
                    Image.fromarray(_jet(img)).save(
                        os.path.join(out_dir, "preview", "depth", f"{k:06d}.png"))
            elif previews and topic in object_topics:
                for k in frames:                        # the mask's own class colours
                    Image.fromarray(np.ascontiguousarray(img & np.uint8(0xFE))).save(
                        os.path.join(out_dir, "preview", object_topics[topic][0], f"{k:06d}.png"))
            elif previews and topic in shadow_topics:
                for k in frames:
                    Image.fromarray(palette[img]).save(
                        os.path.join(out_dir, "preview", shadow_topics[topic], f"{k:06d}.png"))
            if topic == EXACT["depth"]:
                if depth_npy:
                    for k in frames:
                        np.save(os.path.join(out_dir, "depth_m", f"{k:06d}.npy"), img.astype(np.float32))
                mm = np.where(np.isfinite(img) & (img > 0) & (img < 65.535), np.round(img * 1000.0), 0)
                img = mm.astype(np.uint16)
            elif topic in object_topics:
                img = _object_ids(img, object_topics[topic][1])
            for k in frames:
                Image.fromarray(img).save(os.path.join(out_dir, folders[topic], f"{k:06d}.png"))

    if previews:                                        # lidar points in colour over the dimmed RGB image
        for k, depth in lidar_depth.items():
            rgb_path = os.path.join(out_dir, "rgb_central", f"{k:06d}.png")
            if not os.path.isfile(rgb_path):
                continue
            base = (np.array(Image.open(rgb_path).convert("RGB")) * 0.4).astype(np.uint8)
            grown = depth.copy()                        # 3 x 3 dots, nearest point wins
            for dv, du in ((-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (-1, 1), (1, -1), (1, 1)):
                shifted = np.roll(np.roll(depth, dv, 0), du, 1)
                take = (shifted > 0) & ((grown == 0) | (shifted < grown))
                grown[take] = shifted[take]
            hit = grown > 0
            base[hit] = _jet(grown)[hit]
            Image.fromarray(base).save(os.path.join(out_dir, "preview", "lidar_depth", f"{k:06d}.png"))

    with open(os.path.join(out_dir, "frames.csv"), "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]) if rows else ["frame"])
        writer.writeheader()
        writer.writerows(rows)
    with open(os.path.join(out_dir, "episode.json"), "w") as f:
        json.dump({**episode_meta, "samples": len(rows), "camera_info": info,
                   "object_classes": classes, "shadow_classes": legends.get("shadow_label_mapping", {})},
                  f, indent=2)
    if fcfg.get("aligned_labels", True):                # the labels on the SPAD and event camera grids
        import align_labels
        align_labels.align_episode(out_dir, previews=previews)
    return len(rows)


def strip_images(bag_dir):
    """
    Rewrites an episode bag without its images and lidar scans (the bulk of it;
    they are in the samples) as bag_dir/<name>_no_images.mcap and deletes the
    original. Odometry, tf, IMU, clock, mission, camera_info and legends stay.
    Returns the new file's path.
    """
    from mcap.writer import Writer
    path = glob.glob(os.path.join(bag_dir, "*.mcap"))[0]
    out_path = os.path.join(bag_dir, os.path.basename(os.path.normpath(bag_dir)) + "_no_images.mcap")
    schemas, channels = {}, {}
    with open(path, "rb") as f, open(out_path + ".part", "wb") as out:
        reader = make_reader(f)
        writer = Writer(out)
        writer.start(profile="ros2", library="mare-dataset")
        for schema, channel, message in reader.iter_messages():
            if schema is not None and schema.name in ("sensor_msgs/msg/Image", "sensor_msgs/msg/PointCloud2"):
                continue
            if schema is not None and schema.id not in schemas:
                schemas[schema.id] = writer.register_schema(schema.name, schema.encoding, schema.data)
            if channel.id not in channels:
                channels[channel.id] = writer.register_channel(
                    channel.topic, channel.message_encoding,
                    schemas.get(schema.id, 0) if schema is not None else 0, channel.metadata)
            writer.add_message(channels[channel.id], message.log_time, message.data,
                               message.publish_time, message.sequence)
        writer.finish()
    for name in os.listdir(bag_dir):                    # the full bag and its metadata.yaml
        if name != os.path.basename(out_path) + ".part":
            os.remove(os.path.join(bag_dir, name))
    os.replace(out_path + ".part", out_path)
    return out_path


def main():
    import generate                                     # shared config and paths
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.yaml"))
    parser.add_argument("--output", help="output folder (overrides the config's output_dir)")
    args = parser.parse_args()
    run = generate.Run(args.config, args.output)
    total = run.extract_pending()
    print(f"{total} samples in {run.samples_dir}")


if __name__ == "__main__":
    main()
