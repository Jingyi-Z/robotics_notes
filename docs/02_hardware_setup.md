# SO-ARM 101 Hardware Setup

This doc tracks how to bring up the SO-ARM 101 (one **leader** + one
**follower** arm + a USB webcam) from a freshly assembled state to working
teleoperation. The flow mirrors the
[official SO-101 page](https://huggingface.co/docs/lerobot/so101) and the
[Cameras](https://huggingface.co/docs/lerobot/cameras) page, with my own
per-arm port table at the end.

> Authoritative source: <https://huggingface.co/docs/lerobot/so101>
> Camera reference: <https://huggingface.co/docs/lerobot/cameras>
> Assembly + 3D-print parts: <https://github.com/TheRobotStudio/SO-ARM100>

I have notes for two vendor variants of the SO-101 — **WOWROBO** and
**SEEED** — because that's what's on my desk. The actual port strings,
gear ratios, and assembly steps are the same.

---

## 1. What you need

- 1× leader arm (the smaller, hand-driven arm)
- 1× follower arm (the one that mirrors the leader / runs the policy)
- 2× USB cables (one per motor bus)
- 2× power supplies (one per arm)
- 1× USB webcam (I use a 1080p USB camera for the `front` view)
- A computer with LeRobot installed —
  see [`01_environment_setup.md`](01_environment_setup.md)
- The `[feetech]` extra: `pip install -e ".[feetech]"`

### Motor table (per the official SO-101 page)

| Leader-Arm Axis | Motor | Gear Ratio |
|---|---|---|
| Base / Shoulder Pan | 1 | 1 / 191 |
| Shoulder Lift | 2 | 1 / 345 |
| Elbow Flex | 3 | 1 / 191 |
| Wrist Flex | 4 | 1 / 147 |
| Wrist Roll | 5 | 1 / 147 |
| Gripper | 6 | 1 / 147 |

The follower uses six **STS3215** motors all with **1/345** gearing.

---

## 2. Step-by-step bring-up (official flow)

The SO-101 page walks through it in this order — I follow the same:

1. **Source / 3D-print the parts** ([README](https://github.com/TheRobotStudio/SO-ARM100))
2. **Find the USB ports for the two arms** — `lerobot-find-port`
3. **Set the motors' ids + baudrate** — `lerobot-setup-motors`
4. **Assemble the joints** (videos on the SO-101 page)
5. **Calibrate** — `lerobot-calibrate`
6. **Teleoperate** — `lerobot-teleoperate`

### 2.1 Find the USB ports

Plug the **first** arm and run:

```bash
lerobot-find-port
```

The script prints all current serial ports, asks you to **unplug** the arm,
and reports which port disappeared — that's the port belonging to the arm you
just unplugged.

Example output on Mac:

```text
Finding all available ports for the MotorBus.
['/dev/tty.usbmodem575E0032081', '/dev/tty.usbmodem575E0031751']
Remove the USB cable from your MotorsBus and press Enter when done.

[...disconnect, press Enter...]

The port of this MotorsBus is /dev/tty.usbmodem575E0032081
```

Repeat for the second arm. Record both ports.

### 2.2 Set motor IDs + baudrate (one-time, per arm)

Brand-new STS3215 motors all ship with id `1`. They live on one shared
half-duplex bus, so every motor on a single arm needs a unique id (1..6). The
ids + baudrate get written to the motor's EEPROM, so this is a one-time setup
per motor.

**Follower:**

```bash
lerobot-setup-motors \
  --robot.type=so101_follower \
  --robot.port=/dev/tty.usbmodem585A0076841   # the port from `lerobot-find-port`
```

You'll be prompted in this order: `gripper` (id=6), `wrist_roll`,
`wrist_flex`, `elbow_flex`, `shoulder_lift`, `shoulder_pan` (id=1). For each
prompt, plug **only** that one motor into the controller board and press Enter.

**Leader:**

```bash
lerobot-setup-motors \
  --teleop.type=so101_leader \
  --teleop.port=/dev/tty.usbmodem575E0031751
```

After both arms are done, daisy-chain the motors back together; the controller
board talks to motor id 1 (shoulder pan) and forwards through the chain.

Troubleshooting (from the SO-101 page):

- Re-check the power supply, the USB cable, and the 3-pin cable between board
  and motor before pressing Enter.
- On Waveshare controller boards, both jumpers must be on the **B** (USB)
  channel.

### 2.3 Assemble the joints

The SO-101 page has a per-joint video walkthrough (Joints 1–5 + Gripper). I'm
not duplicating screw-by-screw counts here — go look at the video. Two things
worth noting once you've done one:

- Install one 3-pin cable into each motor **before** placing it in its joint.
  Plugging cables in after assembly is painful.
- Pre-clean every 3D-printed part of support material. A small flat-head
  screwdriver works.

### 2.4 Calibrate

Calibration aligns the leader and follower so they read identical joint
positions in identical poses. It's required before the first useful teleop /
record session, and required whenever you change motor mounts.

**Follower:**

```bash
lerobot-calibrate \
  --robot.type=so101_follower \
  --robot.port=/dev/tty.usbmodem58760431551 \
  --robot.id=my_awesome_follower_arm
```

**Leader:**

```bash
lerobot-calibrate \
  --teleop.type=so101_leader \
  --teleop.port=/dev/tty.usbmodem58760431551 \
  --teleop.id=my_awesome_leader_arm
```

The interactive flow asks you to:

1. Move each joint to the middle of its range, then press Enter.
2. Slowly sweep every joint through its full range while it records the
   limits.

The result lands under `~/.cache/huggingface/lerobot/calibration/<id>/`. The
**`--*.id`** value is what binds the calibration to the arm — pick something
stable and stick to it (see §4).

`lerobot-teleoperate` will auto-trigger calibration if it can't find a saved
file for the given id, so re-running the calibrate command manually is mostly
useful when you want to redo it.

---

## 3. Webcam setup

LeRobot has a discovery helper for OpenCV-class cameras:

```bash
lerobot-find-cameras opencv         # USB / built-in / iPhone Continuity
lerobot-find-cameras realsense      # Intel RealSense
```

My USB webcam shows up like:

```text
--- Detected Cameras ---
Camera #0:
  Name: OpenCV Camera @ 0
  Type: OpenCV
  Id: 0
  Backend api: AVFOUNDATION
  Default stream profile:
    Width: 1920
    Height: 1080
    Fps: 30.00003
```

Use `Id` as `index_or_path` in the camera config dict, like:

```text
--robot.cameras="{ front: {type: opencv, index_or_path: 0, width: 1920, height: 1080, fps: 30} }"
```

On macOS, the **iPhone Continuity Camera** appears as a normal OpenCV device
as long as the Mac is on macOS 13+ and the iPhone is on iOS 16+. Useful if you
want a high-quality wrist cam without buying one. On macOS, Intel RealSense
cameras are unstable — use Linux if you have the choice.

<<<<<<< HEAD
=======
### Resizing the camera frame

`width` / `height` set the **capture** resolution (what the camera streams).
`target_width` / `target_height` set the **output** resolution — LeRobot
resizes each frame to those dims before handing it to the policy or recorder.
Use this when you want to capture at a sane sensor resolution but feed the
policy a smaller square (ACT and most LeRobot policies expect 224×224).

RealSense example — capture 640×480, downscale to 224×224 for the policy:

```bash
--robot.cameras='{top: {"type": "intelrealsense", "serial_number_or_name": "239222300740", "width": 640, "height": 480, "target_width": 224, "target_height": 224, "fps": 30}}' \
```

Same idea with an OpenCV / USB camera:

```bash
--robot.cameras='{front: {"type": "opencv", "index_or_path": 0, "width": 1920, "height": 1080, "target_width": 224, "target_height": 224, "fps": 30}}' \
```

Notes:

- For RealSense, identify the camera with `serial_number_or_name` (from
  `lerobot-find-cameras realsense`), not `index_or_path`.
- The capture (`width`/`height`) must be a resolution the camera actually
  supports; the target dims can be anything — LeRobot resizes in software.
- **Keep `target_width` / `target_height` consistent across record, replay,
  and eval** — switching them mid-dataset breaks ACT, since the policy was
  trained on a specific input size (see `03_record_replay.md` §"Pitfalls").

>>>>>>> bda26fb (add notes)
---

## 4. Conventions for `--robot.id` / `--teleop.id`

The `id` is **how LeRobot looks up the calibration**. Two rules that have
bitten me:

- One stable id per physical arm (e.g. `so101_follower_seeed`). If two arms
  share an id, their calibrations clobber each other.
- The port string can change after a reboot — that's fine, the id is what
  re-finds the saved calibration. Just pass the current port + the same id.

`lerobot-teleoperate` will auto-calibrate if no calibration exists for the
given id, so a fresh arm + fresh id just walks you through the flow.

---

## 5. Teleoperate

Minimum teleop (no cameras):

```bash
lerobot-teleoperate \
  --robot.type=so101_follower \
  --robot.port=/dev/tty.usbmodem58760431541 \
  --robot.id=my_awesome_follower_arm \
  --teleop.type=so101_leader \
  --teleop.port=/dev/tty.usbmodem58760431551 \
  --teleop.id=my_awesome_leader_arm
```

Teleop with a front camera + `rerun` live view:

```bash
lerobot-teleoperate \
  --robot.type=so101_follower \
  --robot.port=/dev/tty.usbmodem58760431541 \
  --robot.id=my_awesome_follower_arm \
  --robot.cameras="{ front: {type: opencv, index_or_path: 0, width: 1920, height: 1080, fps: 30} }" \
  --teleop.type=so101_leader \
  --teleop.port=/dev/tty.usbmodem58760431551 \
  --teleop.id=my_awesome_leader_arm \
  --display_data=true
```

`--display_data=true` opens a `rerun` window with the live joint state and
camera frames. It's how I sanity-check both arms before doing a recording
pass.

---

## 6. Platform-specific notes

### macOS

- The follower draws enough current that hub-powered USB ports sometimes
  flake. Use the included power supply and connect USB to the host directly.
- The OS will prompt for "Camera" / "Input Monitoring" permissions for the
  terminal once.

### Linux

- Add yourself to `dialout` (covered in
  [`01_environment_setup.md`](01_environment_setup.md#3-linux-setup-ubuntu-2204--2404)).
- A `udev` rule keyed on idVendor/idProduct can map an arm to a stable
  `/dev/so101_follower` symlink that survives replug.

### Windows / WSL2

- On native Windows the arm appears as a COM port (`COM3`, `COM4`, ...).
- Inside WSL2 you have to `usbipd attach` first — see
  [`01_environment_setup.md`](01_environment_setup.md#41-recommended-wsl2).
  Also make sure `evdev` is installed via conda-forge in the WSL env.

---

## 7. Per-machine inventory

Snapshot of my desk so I don't have to re-discover ports:

```text
host: jz-macbook (macOS)
vendor: SEEED
  leader   port=/dev/tty.usbmodem5B421385081  id=so101_leader_seeed
  follower port=/dev/tty.usbmodem5B420737901  id=so101_follower_seeed
  camera   opencv index=0  1920x1080 @ 30 FPS

host: jz-macbook (macOS)
vendor: WOWROBO
  leader   port=/dev/tty.usbmodem5B140309361  id=so101_leader_wowrobo
  follower port=/dev/tty.usbmodem5B141118481  id=so101_follower_wowrobo
  camera   opencv index=0
```

---

## 8. References

- SO-101 page (assembly + motor setup + calibration): <https://huggingface.co/docs/lerobot/so101>
- Imitation learning tutorial (teleop section): <https://huggingface.co/docs/lerobot/il_robots>
- Cameras: <https://huggingface.co/docs/lerobot/cameras>

Next: record some demonstrations — [`03_record_replay.md`](03_record_replay.md).
