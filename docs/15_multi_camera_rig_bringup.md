# 15. Bringing up a four-camera rig: USB bandwidth, stable device paths, and a table frame

Adding cameras to an SO-101 bench looks like plugging in more USB cables. In
practice the cameras starve each other of bandwidth, swap device numbers on
reboot, and silently repeat frames. This doc covers the checks that make a
multi-camera rig reliable under LeRobot 0.6.1, how to confirm a robot plugin is
really loaded, and how to calibrate the fixed cameras to one table frame so
drift can be measured instead of guessed.

Companion docs: `02_hardware_setup.md` (arm and camera setup),
`13_policy_rollout_custom_sensor_robot.md` (rollout on a plugin robot),
`14_rig_drift_and_eval_hygiene.md` (why a rig needs a per-session check).

---

## 1. Layout

Four cameras, two roles.

- Policy cameras: one on the wrist, one egocentric view looking down at the
  workspace. These are the views a pretrained VLA expects.
- Reconstruction cameras: two side cameras facing each other across the table,
  aimed at the same point. A wide baseline between them helps 3D reconstruction.
  They stay out of the policy input.

Mark the table center with tape. Every fixed camera is aimed at that mark.

## 2. Address every device by a stable path

`/dev/video0` is assigned in plug order and changes across reboots. Use the
by-id links instead.

```bash
ls -l /dev/v4l/by-id/        # one link per camera, named by model and serial
ls -l /dev/serial/by-id/     # same idea for the arm controller boards
v4l2-ctl --list-devices
```

Each camera exposes two video nodes. The one ending in `video-index0` carries
images. Two cameras of the same model are told apart by the serial in the link
name. If a camera has no serial in its name, give it its own USB port and use
`/dev/v4l/by-path/` for that one.

## 3. USB bandwidth: set MJPG explicitly

Symptom: one camera shows no image, or cameras reset each other, as soon as
three or four run together.

Cause: an uncompressed 640x480 stream at 30 fps needs about 150 Mbit/s. A USB 2
bus carries 480 Mbit/s in total, and on many PCs every USB 2 port is the same
bus. LeRobot 0.6.1 sets no pixel format by default, so most webcams start
uncompressed.

Check what the bus looks like and what the camera offers:

```bash
lsusb -t                                        # speed per device, 480M = USB 2
v4l2-ctl -d /dev/v4l/by-id/<camera>-video-index0 --list-formats-ext
```

Fix: plug cameras directly into the PC, not through a chain of hubs, and ask
for MJPG in the camera config.

```yaml
cameras:
  wrist:
    type: opencv
    index_or_path: /dev/v4l/by-id/<wrist-camera>-video-index0
    width: 640
    height: 480
    fps: 30
    fourcc: MJPG
  ego:
    type: opencv
    index_or_path: /dev/v4l/by-id/<ego-camera>-video-index0
    width: 640
    height: 480
    fps: 30
    fourcc: MJPG
```

Repeat for the two side cameras.

## 4. Measure the real frame rate

LeRobot 0.6.1 reads the latest available frame. A camera that delivers 15 fps
does not raise an error. The dataset just contains every frame twice. So the
frame rate has to be measured with all cameras running together.

```python
import hashlib, sys, time, cv2

paths = sys.argv[1:]
caps = []
for p in paths:
    c = cv2.VideoCapture(p, cv2.CAP_V4L2)
    c.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    c.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    c.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    c.set(cv2.CAP_PROP_FPS, 30)
    caps.append(c)

seconds = 60
unique = [0] * len(caps)
last = [None] * len(caps)
t0 = time.time()
while time.time() - t0 < seconds:
    for i, c in enumerate(caps):
        ok, frame = c.read()
        if not ok:
            continue
        h = hashlib.md5(frame[::8, ::8].tobytes()).hexdigest()
        if h != last[i]:
            unique[i] += 1
            last[i] = h
for p, n in zip(paths, unique):
    print(f"{n / seconds:5.1f} unique fps  {p}")
```

```bash
python cam_stress.py /dev/v4l/by-id/<cam1>-video-index0 /dev/v4l/by-id/<cam2>-video-index0 ...
```

Every camera should print close to 30. Run it for five minutes once before the
first real recording.

## 5. Pin the camera controls and store them

Auto focus and a frame rate that drops in low light are the two controls that
most often change a camera between sessions.

```bash
D=/dev/v4l/by-id/<camera>-video-index0
v4l2-ctl -d $D --list-ctrls
v4l2-ctl -d $D --set-ctrl=focus_automatic_continuous=0
v4l2-ctl -d $D --set-ctrl=focus_absolute=30
v4l2-ctl -d $D --set-ctrl=exposure_dynamic_framerate=0
v4l2-ctl -d $D --set-ctrl=power_line_frequency=2      # 2 = 60 Hz, 1 = 50 Hz
```

Control names vary by camera, so read them from `--list-ctrls` first. Controls
reset on replug, so apply them at the start of every session. Save the output
of `--list-ctrls` for every camera next to each dataset. Two cameras of the
same model can still render the same object in slightly different colors. That
is fine for training as long as each camera stays consistent with itself.

## 6. Confirm the robot plugin is loaded

LeRobot 0.6.1 discovers third-party robots by scanning installed distributions
whose name starts with `lerobot_robot_`. A package that is only on the Python
path is never loaded.

```bash
pip install -e /path/to/your_plugin_repo/lerobot_robot_myrobot
cd ~
python - <<'PY'
import importlib.metadata as m
print(sorted(d.metadata["Name"] for d in m.distributions()
             if (d.metadata["Name"] or "").startswith("lerobot_robot_")))
PY
```

Two traps:

1. The `pyproject.toml` may sit in a subfolder of the repo. Install that
   subfolder, not the repo root.
2. Run LeRobot commands from your home directory. If the repo's outer folder
   has the same name as the package, Python imports the empty outer folder
   first when you run from inside it, and the robot type disappears.

## 7. Calibrate the fixed cameras to one table frame

Intrinsics: a small ChArUco board, about 25 views per camera, tilted and moved
across the whole image. A reprojection error under 0.5 px is a good result.

Extrinsics: one larger ChArUco board lying flat on the table center mark. All
fixed cameras see it at once, and the board center becomes the table frame.

```python
import cv2, numpy as np

dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_5X5_100)
board = cv2.aruco.CharucoBoard((4, 5), 0.050, 0.037, dictionary)   # squares, meters
detector = cv2.aruco.CharucoDetector(board)

def camera_pose(gray, K, dist):
    corners, ids, _, _ = detector.detectBoard(gray)
    if ids is None or len(ids) < 6:
        return None                       # keep the previous pose, never overwrite it
    obj, img = board.matchImagePoints(corners, ids)
    ok, rvec, tvec = cv2.solvePnP(obj, img, K, dist)
    if not ok:
        return None
    R, _ = cv2.Rodrigues(rvec)
    return R.T, (-R.T @ tvec).ravel()     # camera orientation and position in the board frame
```

Rules that saved a session each:

1. Print the board at 100% scale and measure one square with a ruler. Printers
   shrink pages even at "100%".
2. Tape the board outline onto the table. The board then returns to the same
   place for a two-minute check at the start of every session.
3. A failed detection must leave the saved pose untouched. Writing an empty
   result over a good calibration loses it.
4. Sanity-check with a tape measure. Camera distance to the table center should
   agree with the calibrated distance within a centimeter or two.
5. The wrist camera moves with the arm, so it gets intrinsics only.

## 8. Session opener

About three minutes before any recording or rollout:

1. Apply the camera controls (section 5).
2. Put the board in its taped outline and compare each camera pose with the
   saved one. A shift of a few millimeters is normal. A larger one means a
   camera was bumped.
3. Remove the board and start.
