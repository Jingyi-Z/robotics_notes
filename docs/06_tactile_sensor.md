# MLX90393 Hall Sensor Integration for LeRobot
This document describes how the SO-101 follower arm in our lab is augmented with an MLX90393 Hall-effect magnetometer mounted near the gripper, how its data is streamed into the LeRobot recording pipeline, and how the framework is extended to accept new sensor types in the future.
The Hall sensor measures a small permanent magnet mounted on the soft gripper pad. As the pad deforms under contact, the magnet shifts relative to the chip, and the resulting field change encodes tactile information.

> Empirical noise behavior of this exact setup is characterized separately in
> [`07_sensor_noise_findings.md`](07_sensor_noise_findings.md).

---
## 1. Hardware overview
The sensing chain has four components in series:
```
[MLX90393 chip on breakout board]  ──I2C──>  [Teensy 4.1]  ──USB serial──>  [MacBook]  ──Python driver──>  [LeRobot]
```
### Components
| Component | Role | Notes |
|---|---|---|
| MLX90393 breakout (Adafruit) | 3-axis Hall measurement | I2C interface; built-in pull-up resistors |
| Small permanent magnet | Field source mounted on gripper pad | Magnet-to-chip distance determines signal range |
| Teensy 4.1 | Reads MLX chip at fixed rate, streams over USB | Acts as a real-time bridge |
| USB cable (Teensy → Mac) | Power + data | Appears on macOS as `/dev/cu.usbmodem*` |
### Wiring
| MLX90393 pin | Teensy 4.1 pin |
|---|---|
| VIN | 3.3V |
| GND | GND |
| SDA | pin 18 |
| SCL | pin 19 |
I2C is bidirectional; the library handles the protocol so wiring is the only manual step.
---
## 2. Teensy firmware
The Teensy continuously samples the MLX chip and forwards each reading to the Mac as a binary frame over USB serial.
### Sample rate and sensor configuration
- Sample rate: 100 Hz (10 ms between samples)
- Gain: `MLX90393_GAIN_5X` (wide-range setting — `5X` denotes lower internal amplification, ~±2600 μT range)
- Resolution: 16-bit on all three axes
- Oversampling: `OSR_2` (4 internal samples averaged)
- Filter: `FILTER_2` (light digital low-pass)

These settings prioritize a fast loop while keeping noise low enough for tactile use. We previously used `GAIN_2_5X` (~±1300 μT range), but observed Bx saturating against the int16 rail because of a strong static field at the sensor location (~-1100 μT at rest). At `GAIN_5X` the chip operates well clear of saturation; the cost is ~2× larger LSB (about 2.4 μT σ noise floor, sufficient for tactile signals that reach hundreds to thousands of μT during grasp).

Increase oversampling/filter if you ever need lower noise at the cost of throughput.

### Wire format
Each sample is transmitted as 8 bytes:
```
Byte:     0     1     2 3     4 5     6 7
Content:  0xAA  0x55  Bx_lo Bx_hi By_lo By_hi Bz_lo Bz_hi
          ─sync─pair──  ──int16──  ──int16──  ──int16──
```
The `0xAA 0x55` sync pattern is an alternating-bit marker that lets the receiver realign if it loses byte position. Each axis is a signed 16-bit integer, little-endian. The firmware scales the chip's μT reading by ×10 before packing, so 1 LSB ≈ 0.1 μT in the wire format.
### Timing
The sketch uses an absolute-deadline scheduling pattern (rather than `delay()`) to maintain a stable 100 Hz cadence without drifting:
```cpp
unsigned long now_us = micros();
if ((long)(now_us - next_sample_us) < 0) return;
next_sample_us += SAMPLE_INTERVAL_US;
```
This anchors the next sample to a fixed timeline rather than "now + 10 ms," so jitter in any one read doesn't accumulate.
### Full sketch location
The complete Teensy sketch lives in the project's `firmware/` directory (or wherever you keep it). It depends on the Adafruit MLX90393 library, installable from the Arduino Library Manager.
### Verifying the firmware
Before testing the LeRobot side:
1. Compile and flash the sketch via Arduino IDE.
2. Open the Serial Monitor at 2,000,000 baud — you should see continuous binary gibberish (rendering as `?` and `0` characters).
3. Close the Serial Monitor (only one process at a time can hold the port).
4. Run a brief Python verification script:
```python
import serial, struct
ser = serial.Serial("/dev/cu.usbmodem197004501", 2_000_000, timeout=1)
for _ in range(50):
    while True:
        b = ser.read(1)
        if b and b[0] == 0xAA:
            b2 = ser.read(1)
            if b2 and b2[0] == 0x55:
                break
    payload = ser.read(6)
    bx, by, bz = struct.unpack("<hhh", payload)
    print(f"Bx={bx:6d}  By={by:6d}  Bz={bz:6d}")
ser.close()
```
Hold a magnet near the chip; values on at least one axis should swing by thousands. **Important sanity check**: all three axes should report nonzero values that respond to a magnet. If Bx (or any axis) is stuck at exactly zero across all samples, the chip is saturating — switch to a higher `setGain` value or physically reposition the breakout further from ferromagnetic objects (servo motors, brackets).
---
## 3. Software architecture in LeRobot
We extended LeRobot's framework to treat the Hall sensor as a first-class observation modality. The design is generic — adding a future sensor type (force-torque, IMU, etc.) requires one new file plus three small edits to existing files (see §7).
### Components added or modified
```
src/lerobot/
├── configs/types.py                                 [MODIFIED]  Added FeatureType.SENSOR
├── utils/
│   ├── constants.py                                 [MODIFIED]  Added OBS_SENSORS constant
│   ├── __init__.py                                  [MODIFIED]  Re-exported OBS_SENSORS
│   └── feature_utils.py                             [MODIFIED]  Schema + frame builders handle SENSOR
├── sensors/                                          [NEW package]
│   ├── __init__.py
│   ├── configs.py                                   SensorConfig base; MLX90393SensorConfig
│   ├── sensor.py                                    Abstract Sensor class
│   ├── utils.py                                     make_sensors_from_configs factory
│   └── mlx90393.py                                  MLX90393Sensor concrete driver
├── scripts/lerobot_record.py                        [MODIFIED]  Waits for sensor calibration before episode 0
└── robots/
    ├── __init__.py                                  [MODIFIED]  Registered SOSensorFollower
    └── so_sensor_follower/                          [NEW package]
        ├── __init__.py
        ├── config_so_sensor_follower.py             SOSensorFollowerConfig
        └── so_sensor_follower.py                    SOSensorFollower robot class
```
### Key abstractions
**`FeatureType.SENSOR`** — the type tag for any non-camera streaming sensor. Distinguishes sensor data from joint state and images throughout the framework.

**`SensorConfig` base class** — a `draccus.ChoiceRegistry`-backed dataclass. Concrete sensor configs register themselves with a string key:
```python
@SensorConfig.register_subclass("mlx90393")
@dataclass
class MLX90393SensorConfig(SensorConfig):
    port: str = "/dev/cu.usbmodem197004501"
    baud_rate: int = 2_000_000
    buffer_size: int = 10
    baseline_frames: int = 100
    baseline: list[float] | None = None
```
The registration enables CLI syntax like `--robot.sensors='{gripper: {type: mlx90393, ...}}'`.

**`Sensor` abstract base class** — defines the contract every sensor driver must implement: `connect`, `disconnect`, `start_continuous_read`, `stop_continuous_read`, `get_latest_data`, `shape`, plus optional `wait_for_calibration` and `metadata`.

**`MLX90393Sensor`** — concrete implementation that reads from the Teensy. It runs a daemon background thread that continuously consumes binary frames and pushes them into a `collections.deque(maxlen=N)` ring buffer. Each `get_latest_data()` call returns the last `N` samples as an `(N, 3)` float32 array.

**`make_sensors_from_configs`** — factory function that dispatches each `SensorConfig` to its matching concrete `Sensor` class based on the `type` field.

**`SOSensorFollower`** — robot class extending `SOFollower`. Adds a `sensors: dict[str, SensorConfig]` field, constructs sensors via the factory, and includes their readings in observations under `observation.sensors.<name>`. Exposes `wait_for_sensor_calibration(timeout_s)` for the recorder to call before recording starts.

### Data flow during recording
```
[Teensy] →USB→ [MLX90393Sensor read thread] →deque→ [get_latest_data] → (10, 3) array
                                                                              │
                                                                              ▼
[Recorder] → robot.get_observation() → {"observation.state": ..., "observation.sensors.gripper": (10, 3) array} → parquet
```
The Teensy stream runs continuously at 100 Hz. The recorder samples the observation at ~30 Hz, draining the deque ~2–3 samples at a time (so each `get_latest_data()` call returns the most recent 100 ms of Hall data — adjacent dataset frames overlap by roughly 70 ms). Approximately 38% of Teensy samples are overwritten in the deque before the recorder reads them; this is acceptable for policy input (ACT consumes the 10-row buffer, not raw 100 Hz), but means the parquet data is not suitable for high-frequency spectral analysis. For full-rate captures, use a separate raw logger script bypassing `lerobot-record`.

### Dataset schema
After recording, the parquet dataset has these columns for a single Hall sensor named `gripper`:
```
observation.state                    float32  shape=(N_motors,)
observation.images.front             video    shape=(H, W, 3)        (if cameras)
observation.sensors.gripper          float32  shape=(10, 3)
action                               float32  shape=(N_motors,)
timestamp                            float32  shape=()
frame_index                          int64    shape=()
episode_index                        int64    shape=()
...
```
Adding a second Hall sensor named `wrist` would add `observation.sensors.wrist` with the same shape. Different sensor types or names live as parallel columns.

> Note: ACT does not currently consume `FeatureType.SENSOR` features. The
> column is faithfully recorded but ignored by ACT's forward pass. To use
> the sensor in ACT, either expose it as `FeatureType.ENV` at the schema
> layer or add a sensor branch to ACT's encoder. See
> [`07_sensor_noise_findings.md`](07_sensor_noise_findings.md#open-items-for-future-work).

---
## 3a. Configuring sensors at recording time

Sensors plug in over serial (USB-to-UART) and are declared via `--robot.sensors=`:

```bash
--robot.sensors='{gripper: {type: mlx90393, port: /dev/cu.usbmodem197004501, baud_rate: 2000000, buffer_size: 10}}' \
```

The dict key (`gripper` here) is the **sensor name** — it becomes the suffix on the dataset's observation key (`observation.sensors.gripper`). Keep it consistent across record, replay, and any future training/eval, since the column key won't migrate gracefully if renamed.

Required and useful fields per sensor:

- **`type`** — registry key for the concrete sensor class (`mlx90393` is the only one currently implemented).
- **`port`** — serial device path. On macOS it's `/dev/cu.usbmodem*` (the Teensy enumerates as a usbmodem device). On Linux it's typically `/dev/ttyUSB0` or `/dev/ttyACM0`. On Windows / WSL2 it's a `COM*` port that must be `usbipd attach`'d into WSL.
- **`baud_rate`** — 2 000 000 (2 Mbaud) for the Teensy-based MLX90393 bridge, matching the firmware.
- **`buffer_size`** — number of samples to expose per frame. 10 gives ~100 ms of history at 100 Hz.
- **`baseline_frames`** — number of samples averaged to form the calibration baseline at startup. Default 100 (= 1 second at 100 Hz).

Multiple sensors go in the same dict — e.g. one per fingertip:

```bash
--robot.sensors='{left_finger: {type: mlx90393, port: /dev/ttyUSB0, baud_rate: 2000000, buffer_size: 10}, right_finger: {type: mlx90393, port: /dev/ttyUSB1, baud_rate: 2000000, buffer_size: 10}}' \
```

The robot type must be `so_sensor_follower` (not the upstream `so101_follower`) for `--robot.sensors=` to be accepted; see §4 calibration-file note.

Gotchas:

- **`dialout` group** — on Linux the user running `lerobot-record` must be in `dialout` (or whatever group owns `/dev/ttyUSB*`). See
  [`01_environment_setup.md`](01_environment_setup.md#3-linux-setup-ubuntu-2204--2404).
- **Port reshuffling** — `/dev/ttyUSB0` can swap with the arm's serial port after a reboot. A `udev` rule keyed on the USB-serial chip's serial number gives you a stable symlink (e.g. `/dev/teensy_gripper`).
- **2 Mbaud needs a good bridge** — Teensy 4.1 native USB serial handles 2 Mbaud cleanly. Cheap CH340 / external USB-UART adapters often don't and silently drop frames. If you see corrupted readings, suspect the cable / adapter first.
- **Camera startup masks the calibration warm-up** — the MLX90393 driver needs ~1 second to fill its baseline buffer. In practice the camera initialization in `lerobot-record` takes longer than that, so by the time frame 0 is captured the sensor is calibrated. If you record without cameras, the calibration wait patch in §3 is what prevents zero-valued frames at episode start.

---
## 4. Calibration procedure
The MLX90393 has significant offset bias (the resting field at the chip is not zero, due to Earth's field, nearby metal, and the chip's own zero-offset). We subtract this per-axis baseline so the policy sees changes around zero rather than absolute field values.
### How calibration works
When `MLX90393Sensor.start_continuous_read()` is called, the driver enters a calibration phase:
1. Collect `baseline_frames` samples (default 100, ~1 second at 100 Hz).
2. Compute the per-axis mean: `baseline = mean([Bx_1, ..., Bx_100], axis=0)`.
3. From this point forward, every emitted sample is `raw - baseline`.

During the calibration phase, `get_latest_data()` returns `None`. The robot's `get_observation()` substitutes zeros if it gets `None`, so frames captured during calibration would contain zero-valued sensor data. The recorder works around this by calling `robot.wait_for_sensor_calibration()` before episode 0 begins.
### Calibration timing relative to motor torque

The current implementation calibrates **as soon as the sensor's background thread starts**, which is during `SOSensorFollower.__init__`. This happens *before* the motors are torque-enabled. We initially flagged this as a likely source of baseline error, on the hypothesis that motor magnetic fields would contribute differently in torque-on vs torque-off states.

Empirically, this concern did not materialize: across the noise-characterization datasets, the baseline shift between torque-off (calibration) and torque-on (recording) is < 1 μT — within the measurement noise floor. Single calibration at session start is sufficient for recording sessions of at least 10 minutes. See [`07_sensor_noise_findings.md`](07_sensor_noise_findings.md#thermal-drift) for the measured drift data.

### Calibration data is recorded in `info.json`
Each sensor's `metadata()` method returns a JSON-serializable snapshot:
```json
{
  "type": "MLX90393Sensor",
  "shape": [10, 3],
  "port": "/dev/cu.usbmodem197004501",
  "baud_rate": 2000000,
  "buffer_size": 10,
  "is_calibrated": true,
  "baseline": [-5370.15, 876.04, 976.29]
}
```
This is intended to be embedded into the dataset's `info.json` so the calibration regime that produced any recorded frames is reproducible. (Currently not yet wired into the recorder; lower priority now that single calibration has been shown to be stable across sessions, but still useful for full traceability.)
### What to do if readings look wrong
If your readings are saturated, far from zero at rest, or one axis is stuck at exactly zero, work through these in order:

1. **Check for saturation.** Read raw int16 values directly (via `Hall_sensor_check.py` from `lerobotac/codes/Hall_sensor_check/`). If any axis is at the rail (±32768), the chip is saturating — increase `setGain` (paradoxically, "5X" is wider range than "2.5X") or `setResolution` (RES_18 is wider range than RES_16). The Bx-always-zero bug we hit in early datasets was caused by this exact failure mode.
2. **Reset and recalibrate.** Power-cycle the Teensy, restart the recorder while the gripper is at the position it will be in during recording. The driver auto-calibrates fresh on every start.
3. **Provide a fixed baseline.** Pass `baseline: [bx, by, bz]` in the CLI config to skip auto-calibration. Useful if you have a known good baseline from a previous session.
4. **Mount the sensor differently.** Physical relocation reduces interference from servo motors. We have not needed to do this; servo motors contribute < 1 μT during stationary holds at our mount geometry. Worth revisiting only if a higher-sensitivity gain setting becomes necessary.
---
## 5. Recording a dataset
### Find your serial ports
Plug in everything (follower arm, leader arm, Teensy) and check:
```bash
ls /dev/cu.usbmodem*
```
To identify which port is which, unplug one device at a time and re-run. The disappearing port is that device.

Current lab mapping (subject to change with USB topology):
| Device | Port |
|---|---|
| SO-101 follower | `/dev/tty.usbmodem5B420737901` |
| SO-101 leader | `/dev/tty.usbmodem5B421385081` |
| Teensy + MLX | `/dev/cu.usbmodem197004501` |
### Calibration files (one-time setup)
`SOSensorFollower` is a distinct robot type from `SOFollower`, so it has its own calibration directory. If you've already calibrated as `so101_follower`, copy the file:
```bash
cp ~/.cache/huggingface/lerobot/calibration/robots/so_follower/so101_follower_seeed.json \
   ~/.cache/huggingface/lerobot/calibration/robots/so_sensor_follower/so101_follower_seeed.json
```
(The motor calibration values are identical between the two robot types — only the folder differs.)
### Recording command
```bash
lerobot-record \
  --robot.type=so_sensor_follower \
  --robot.port=/dev/tty.usbmodem5B420737901 \
  --robot.id=so101_follower_seeed \
  --robot.cameras="{ front: {type: opencv, index_or_path: 1, width: 1920, height: 1080, fps: 30} }" \
  --robot.sensors="{ gripper: {type: mlx90393, port: /dev/cu.usbmodem197004501, baud_rate: 2000000, buffer_size: 10} }" \
  --teleop.type=so101_leader \
  --teleop.port=/dev/tty.usbmodem5B421385081 \
  --teleop.id=so101_leader_seeed \
  --display_data=true \
  --dataset.repo_id=${HF_USER}/<dataset_name> \
  --dataset.num_episodes=N \
  --dataset.single_task="<description>" \
  --dataset.episode_time_s=<seconds> \
  --dataset.reset_time_s=<seconds> \
  --dataset.streaming_encoding=true \
  --dataset.encoder_threads=2 \
  --dataset.push_to_hub=False
```
Key flags:
- `--robot.type=so_sensor_follower` — uses our extended robot class.
- `--robot.sensors='{name: {type: mlx90393, port: ..., buffer_size: N}}'` — declares one or more sensors. Each gets a column `observation.sensors.<name>` in the dataset.
- `--dataset.push_to_hub=False` — keeps the dataset local. Drop this flag when ready to upload.
### Verifying the dataset
After recording, the dataset lives at `~/.cache/huggingface/lerobot/<HF_USER>/<dataset_name>_<timestamp>/`. The timestamped folder name means each recording attempt produces its own directory. To load it:
```python
from lerobot.datasets.lerobot_dataset import LeRobotDataset
ROOT = "/Users/<you>/.cache/huggingface/lerobot/<HF_USER>/<dataset_name>_<timestamp>"
ds = LeRobotDataset("<HF_USER>/<dataset_name>", root=ROOT)
# Check features
for key, feat in ds.features.items():
    print(f"  {key}: dtype={feat['dtype']}, shape={feat['shape']}")
# Inspect a frame
sample = ds[100]
print(sample["observation.sensors.gripper"])
```
Confirm:
- `observation.sensors.gripper` appears with the expected shape `(buffer_size, 3)` and dtype `float32`.
- **None of the three axes are identically zero** across the dataset (a sign of chip saturation; see §4 troubleshooting).
- Values change over time as the robot moves and the gripper actuates.
- No leading zero frames at the start of episode 0 (the `wait_for_sensor_calibration` patch in §3 prevents these; if you see them, your `lerobot-record` is from before that fix).
---
## 6. Known issues and status
| Issue | Status | Notes |
|---|---|---|
| First ~1 s of each recording run contains zeros (calibration warm-up at robot `__init__`) | **Fixed** | `lerobot-record` calls `robot.wait_for_sensor_calibration(timeout_s=10.0)` before episode 0. Verified clean start-of-episode on post-fix datasets. |
| Bx (or any axis) identically zero across a dataset | **Fixed in firmware** | Was caused by chip saturation against the int16 rail at `GAIN_2_5X` (Bx resting at ~-1100 μT, ~83% of full-scale). Resolved by switching to `GAIN_5X` for wider range. The `Hall_sensor_check.py` saturation check in §2 catches recurrences. |
| `build_dataset_frame` silently drops 2-D sensor features | **Fixed** | Patched in commit `0459520` on the `hall-sensor` branch of `lerobotac`. Without the fix, `observation.sensors.gripper` is missing from recorded frames. |
| Calibration runs before motors are torque-enabled | **Deprioritized** | Empirically the torque-on vs torque-off baseline differs by < 1 μT — see [`07_sensor_noise_findings.md`](07_sensor_noise_findings.md#thermal-drift). Worth eventual cleanup for design hygiene, but not blocking. |
| Sensor metadata not embedded in dataset `info.json` | Open | Cosmetic. Baselines can be recovered from data; lower priority now that single calibration is stable. |
| Camera at index 0 fails on this MacBook | Workaround | Use `index_or_path: 1` or `index_or_path: 2`. |
| Magnetic interference from servo motors | **Investigated** | Servo current contributes < 1 μT during stationary holds. Motion-correlated field changes are dominated by Earth's-field rotation (deterministic from joint state), not servo interference. See [`07_sensor_noise_findings.md`](07_sensor_noise_findings.md#where-motion-noise-actually-comes-from). No shielding needed. |
| ACT doesn't consume `FeatureType.SENSOR` | Open | The sensor column is recorded in the dataset but ignored by ACT's forward pass. Either expose the sensor as `FeatureType.ENV` (cheap) or add a sensor branch to ACT (clean). Decide after running vanilla ACT (vision + state) and seeing whether tactile input is needed. |
---
## 7. Adding a new sensor type
To add a different sensor (e.g., a force-torque sensor):
1. Create `src/lerobot/sensors/<sensor_name>.py` with a class inheriting from `Sensor`.
2. Add a `<SensorName>Config` class to `src/lerobot/sensors/configs.py` decorated with `@SensorConfig.register_subclass("<name>")`.
3. Add one `elif cfg.type == "<name>": ...` clause to `src/lerobot/sensors/utils.py:make_sensors_from_configs`.
4. Re-export the new class from `src/lerobot/sensors/__init__.py`.

Nothing else changes. The framework's schema builder, frame builder, and `SOSensorFollower` robot will handle the new sensor automatically — they don't know or care what kind of sensor it is, only that it follows the `Sensor` interface and declares its `shape`.
---
## 8. References
- Upstream LeRobot: <https://github.com/huggingface/lerobot>
- Inspiration for sensor extension pattern: <https://github.com/TNA001-AI/lerobot_tactile>
- MLX90393 datasheet: Melexis website
- Adafruit MLX90393 library: <https://github.com/adafruit/Adafruit_MLX90393_Library>
- This fork: <https://github.com/Jingyi-Z/lerobotac>
- Sensor noise findings: [`07_sensor_noise_findings.md`](07_sensor_noise_findings.md)
---
*Last updated: 2026-05-14*