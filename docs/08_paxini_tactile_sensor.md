# Paxini PX-6AX GEN3 Tactile Sensor Integration for LeRobot
This document describes how a Paxini PX-6AX GEN3 multidimensional tactile sensor is connected to the SO-101 setup in our lab, how its data is streamed into the LeRobot recording pipeline, and the blockers encountered along the way. It is the companion to Doc #06 (the MLX90393 Hall sensor); the two sensors are independent and can be recorded together.
The Paxini sensor is a Hall-effect tactile array. Each measurement point reports a 3-axis force vector; depending on the variant a sensor has 9 to 239 points, plus an aggregate "resultant" force. Unlike the MLX setup there is no custom Teensy firmware — Paxini ships its own communication boards, and we talk to them with a Python SDK (`paxini-sdk`) written for this project.
---
## 1. Hardware overview
The sensing chain has four components in series:
```
[PX-6AX GEN3 sensor]  ──FPC──>  [Paxini comm board]  ──USB serial──>  [laptop]  ──paxini-sdk──>  [LeRobot]
```
### Components
| Component | Role | Notes |
|---|---|---|
| PX-6AX GEN3 sensor | Hall-effect tactile array (fingertip / finger-pad / palm) | 12 stock variants, 9–239 measurement points |
| Paxini communication board | Bridges the sensor's FPC to USB serial | Two types — see below |
| USB cable (board → laptop) | Power + data | CH340-class UART; `COMx` on Windows, `/dev/cu.usbserial-*` on macOS |
| `paxini-sdk` | User-authored Python driver | <https://github.com/Jingyi-Z/paxini-sdk> |
### The two communication boards
Paxini ships two boards. They speak different protocols and the SDK has a separate driver class for each.
| Board | SDK class | Protocol | Rate | Sensors |
|---|---|---|---|---|
| High-Speed Communication Board (PXSR-STDOTO4B) | `HighSpeedHandBoard` | Auto-push stream | ~91 Hz | Up to 28 modules; reports each module's point count |
| Serial Converter Board | `SingleSensorBoard` | Request/response | ~176 Hz round-trip | One sensor; **cannot** report which model is attached |
The High-Speed board streams frames continuously once enabled. The Serial Converter Board answers one request at a time and has no auto-push mode. Both run at 921600 baud, 8-N-1.
### Sensor variants
All 12 stock GEN3 variants have a distinct distributed-force point count, so the count uniquely identifies the model:
| Variant | Vendor part code | Points |
|---|---|---|
| MC-M2020-Elite (palm) | PXSR-STDMC03A | 9 |
| IP-S1610-Elite (finger pad) | PXSR-STDIP03B | 25 |
| DP-S1813-Elite (13 mm fingertip) | PXSR-STDDP03F | 31 |
| DP-S1813-Core (13 mm fingertip) | PXSR-STDDP03D | 51 |
| DP-S2015-Elite (15 mm fingertip) | PXSR-STDDP03G | 52 |
| IP-M2324-Core (finger pad) | PXSR-STDIP03A | 68 |
| CP-M3025-Core (finger pad) | PXSR-STDCP03B | 77 |
| DP-S3013-Core (integrated tip+pad) | PXSR-STDDP03E | 96 |
| DP-S2716-Core (16 mm fingertip) | PXSR-STDDP03C | 116 |
| DP-M2826-Omega (26 mm fingertip) | PXSR-STDDP03B | 127 |
| DP-L3530-Omega (30 mm fingertip) | PXSR-STDDP03A | 135 |
| CP-L5325-Omega (finger pad) | PXSR-STDCP03A | 239 |
Two sensors have been verified end-to-end in our lab: the **DP-S2015-Elite** (52 points) on the High-Speed board, and the **DP-L3530-Omega** (135 points) on the Serial Converter Board.
---
## 2. The paxini-sdk wrapper
Paxini does not publish a Python SDK — only reference scripts (`Hand_UI.py`, `USB_UI.py`, `Read_Single_Sensor_*.py`) and a protocol PDF. `paxini-sdk` is a clean, packaged driver written for this project from those materials and verified byte-for-byte against the vendor scripts and against real hardware.
### What it provides
- `HighSpeedHandBoard` — opens the High-Speed board, reads the active-module bitmap and per-module point counts, calibrates, and yields decoded `AutoPushFrame` objects from the auto-push stream.
- `SingleSensorBoard` — opens the Serial Converter Board, calibrates, and reads resultant / distributed force on request.
- `sensor_registry` — maps a point count or part code to one of the 12 variants and loads its per-point `(x, y, z)` mm coordinates.
- Command-line tools: `paxini-smoke` / `paxini-smoke-serial` (hardware smoke tests), `paxini-rerun` (3D viewer), `paxini-record` (CSV capture), `paxini-characterize`.
### Force decoding
Verified against the vendor reference programs:
- High-speed module resultant: 6 wire bytes, only the low byte of each axis is meaningful; Fx/Fy are signed int8, Fz is unsigned uint8.
- Distributed-force point: 3 wire bytes `[Fx Fy Fz]`, same signed/unsigned rule.
- Scale: **0.1 N per LSB** on every axis, both boards.
### Install
```bash
git clone https://github.com/Jingyi-Z/paxini-sdk.git
cd paxini-sdk
pip install -e ".[viz]"     # viz pulls in rerun-sdk
pytest -q                   # 52 offline tests, no hardware needed
```
### First contact with hardware
```bash
# High-Speed board (auto-detects the sensor):
paxini-smoke --port COM7 --calibrate
# Serial Converter Board (you must name the sensor):
paxini-smoke-serial --port COM3 --sensor PXSR-STDDP03A --calibrate
```
---
## 3. Software architecture in LeRobot
The Paxini sensor plugs into the same sensor framework the MLX90393 uses (Doc #06 §3) — `FeatureType.SENSOR`, the `Sensor` abstract base class, the `make_sensors_from_configs` factory, and the `SOSensorFollower` robot. Adding Paxini support meant one new driver file plus the three-edit registration pattern.
### Components added
```
src/lerobot/sensors/
├── configs.py     [MODIFIED]  Added PaxiniSensorConfig
├── utils.py       [MODIFIED]  Factory dispatches type="paxini"
├── __init__.py    [MODIFIED]  Re-exports PaxiniSensor / PaxiniSensorConfig
└── paxini.py      [NEW]       PaxiniSensor driver (both comm boards)
src/lerobot/utils/
└── visualization_utils.py  [MODIFIED]  Animates sensor data + default Blueprint
```
### PaxiniSensor
`PaxiniSensor` wraps `paxini-sdk` behind the `Sensor` interface. A daemon background thread continuously acquires force data and pushes it into a ring buffer; `get_latest_data()` returns the last `N` samples.
The `board_type` config field selects the comm board:
- `board_type="high_speed"` — the thread consumes the auto-push stream.
- `board_type="serial"` — the thread polls `SingleSensorBoard` in a request/response loop.
Both paths funnel into one shared ingestion routine, so output formats, calibration, and the optional rerun 3D point cloud behave identically regardless of board.
### Output formats
The `output_format` field controls the recorded tensor shape:
| `output_format` | Shape per step | Contents |
|---|---|---|
| `resultant` | `(N, 3)` | Aggregate Fx, Fy, Fz in newtons |
| `distributed` | `(N, P, 3)` | Per-taxel grid; `P` is the variant's point count |
| `both` | `(N, 3 + P*3)` | Flat concat of resultant + distributed |
`N` is `buffer_size` (the ring depth, default 10).
### Fixed sample rate
Because the two boards have very different native rates (~91 Hz auto-push vs. request/response), the `poll_rate_hz` config field locks the recorded cadence to a fixed value on both:
- Serial board: the poll loop sleeps the remainder of each `1/rate` period.
- High-speed board: the auto-push stream is downsampled — one frame per period is recorded, the rest dropped.
`poll_rate_hz=0` (default) uses the board's native rate. Setting e.g. `poll_rate_hz=30` gives a deterministic 30 Hz, the same idea as the Teensy giving the MLX sensor a fixed rate.
### Data flow during recording
```
[Paxini board] →USB→ [PaxiniSensor read thread] →ring→ [get_latest_data] → (N, ...) array
                                                                                │
                                                                                ▼
[Recorder] → robot.get_observation() → {"observation.sensors.<name>": array} → parquet
```
The reading lands in the dataset at `observation.sensors.<name>` — the same namespace the MLX sensor uses, so a Paxini fingertip and an MLX gripper sensor record as parallel columns.
---
## 4. Calibration
Both boards do baseline subtraction in firmware. `auto_calibrate=true` (the default) sends the calibration command at connect time — place the sensor unloaded first; all subsequent readings are referenced to that zero state.
- **High-Speed board** — calibration is asynchronous. `PaxiniSensor.wait_for_calibration()` polls until it completes; `lerobot-record` waits before episode 0.
- **Serial Converter Board** — calibration is a synchronous request/response that returns `ERR_SUC` immediately, so there is no warm-up window.
An optional host-side baseline (`software_baseline_frames > 0`) averages the first N frames after connect and subtracts that from every later sample — useful for trimming sub-LSB residual offset.
---
## 5. Recording a dataset
### High-Speed Communication Board
```bash
lerobot-record \
  --robot.type=so_sensor_follower \
  --robot.port=/dev/tty.usbmodem5B420737901 \
  --robot.id=so101_follower_seeed \
  --robot.sensors='{paxini_fingertip: {type: paxini, board_type: high_speed, port: /dev/cu.usbmodemD3BB68743E521, output_format: distributed, poll_rate_hz: 30, auto_calibrate: true, display_rerun: true}}' \
  --teleop.type=so101_leader \
  --teleop.port=/dev/tty.usbmodem5B421385081 \
  --teleop.id=so101_leader_seeed \
  --dataset.repo_id=${HF_USER}/<dataset_name> \
  --dataset.single_task="<description>" \
  --display_data=true
```
### Serial Converter Board
The serial board cannot report its sensor model, so `sensor_part_code` is required:
```bash
  --robot.sensors='{paxini_fingertip: {type: paxini, board_type: serial, port: COM3, sensor_part_code: PXSR-STDDP03A, output_format: distributed, poll_rate_hz: 30, auto_calibrate: true, display_rerun: true}}'
```
### Two sensors on one High-Speed board

The High-Speed board carries up to 28 modules. To record two fingertips at
once (e.g. gripper finger in the middle-finger slot = module 10, wrist-roll
finger in the little-finger slot = module 18), declare one sensor entry per
module, all on the same `port`, each with its own `module_index`:

```bash
  --robot.sensors='{
    paxini_gripper:    {type: paxini, board_type: high_speed, port: COM10, module_index: 10, output_format: distributed, poll_rate_hz: 30, auto_calibrate: true},
    paxini_wrist_roll: {type: paxini, board_type: high_speed, port: COM10, module_index: 18, output_format: distributed, poll_rate_hz: 30, auto_calibrate: true}
  }'
```

Both entries point at the same COM port. Internally they share one
`HighSpeedHandBoard` and one auto-push stream (a serial port opens once, and
one stream is consumed once); each sensor pulls its own module out of every
frame and records to `observation.sensors.paxini_gripper` and
`observation.sensors.paxini_wrist_roll` respectively. Give each a distinct
`module_index` — two entries left at the default would both read the first
active module and record identical data (the adapter logs a warning if it
sees this).

**Verified on hardware (2026-08-07):** two DP-S2015-Elite fingertips (module
10 = Middle-Tip slot, module 18 = Little-Tip slot) recorded together with two
cameras and both SO-101 arms into a single dataset. The full working command:

```powershell
lerobot-record `
  --robot.type=so_sensor_follower --robot.port=COM8 --robot.id=so101_follower_seeed `
  --robot.cameras="{ top: {type: opencv, index_or_path: 1, width: 640, height: 480, fps: 30, fourcc: MJPG}, wrist: {type: opencv, index_or_path: 2, width: 640, height: 480, fps: 30, fourcc: MJPG} }" `
  --robot.sensors="{ paxini_gripper: {type: paxini, board_type: high_speed, port: COM10, module_index: 10, output_format: distributed, poll_rate_hz: 30, auto_calibrate: true, display_rerun: true}, paxini_wrist_roll: {type: paxini, board_type: high_speed, port: COM10, module_index: 18, output_format: distributed, poll_rate_hz: 30, auto_calibrate: true, display_rerun: true} }" `
  --teleop.type=so101_leader --teleop.port=COM9 --teleop.id=so101_leader_seeed `
  --dataset.repo_id="Jingyi-Z/two_finger_test" --dataset.num_episodes=1 `
  --dataset.single_task="..." --dataset.push_to_hub=False --display_data=true
```

The recorded dataset has `observation.sensors.paxini_gripper` and
`observation.sensors.paxini_wrist_roll`, each shape `(10, 52, 3)`, as
independent columns.

### Live rerun visualization

With `--display_data=true` and `display_rerun: true` on each sensor, the
recorder shows a rerun window with a custom SO-101 + Paxini layout (built by
`init_rerun` in `lerobot/utils/visualization_utils.py`):

- **Paxini forces (N)** — resultant Fx/Fy/Fz and per-taxel sums for every
  fingertip, each series labeled by its entity path so the two fingertips are
  distinguishable.
- **One 3D point-cloud panel per fingertip** — the first sensor goes
  top-right, the second replaces the bottom-right panel, extras become tabs.
  Each panel shows that fingertip's 52-point cloud colored by Fz (blue at
  rest, red on contact). Separate panels avoid the overlap you get from
  drawing two identical-geometry clouds in one view.
- Wrist + top cameras and joint/action time-series fill the rest.

Two rerun-specific gotchas were solved to make this work (see the blocker
table): rerun splits entity paths on `/` only, so the tactile data is logged
under a real slash hierarchy `observation/sensors/<name>/...` (not the dotted
`observation.sensors.<name>`) so the panel wildcards match; and the record
script passes the Paxini sensor names into `init_rerun` so it can build one
panel per fingertip.

### Notes
- The Paxini stream lands at `observation.sensors.paxini_fingertip` with shape `(buffer_size, P, 3)` in `distributed` mode.
- `display_rerun: true` logs a live 3D point cloud of the fingertip taxels (colored by Fz) into the `lerobot-record --display_data=true` viewer.
- A Paxini sensor and the MLX gripper sensor can be declared together in one `--robot.sensors` dict.
---
## 6. Known issues and blockers
| Issue | Status | Notes / mitigation |
|---|---|---|
| Paxini board stuck in auto-push mode after an unclean shutdown — next run fails with `frame head aa55 not found` | Recurring | Power-cycle the board's USB cable; a clean power-on resets the auto-push state |
| High-Speed board calibration times out (`calibration timed out after 10s`) on a second run | Recurring | Stale serial port from a previous aborted run — unplug/replug the board USB before relaunching |
| Vendor host app v1.0.11 auto-fires a firmware-upgrade command on "Open" and the UI hangs while holding the COM port | Known | Force-close `pxsr-gen3` in Task Manager, replug USB; firmware is never actually modified. v1.0.7 is a fallback |
| Serial Converter Board stamps `ERR_LEN` (status 0x01) on every read response | Benign | The payload is valid; the vendor `USB_UI.py` ignores the status byte. `paxini-sdk` tolerates `ERR_LEN` on reads, stays strict on writes |
| Serial Converter Board has no point-count register | By design | `sensor_part_code` must be supplied in the config; there is no auto-detection for this board |
| `paxini-sdk` is a community wrapper, not the official SDK | Known | Every function was cross-checked against vendor scripts + hardware; see `docs/FINDINGS.md` |
| Vendor materials document 12 sensor variants; no coordinate data for any beyond those 12 | Known | A 13th/14th variant would need its coordinate xlsx added to `sensor_registry` and its point count verified unique |
| Recording two+ sensors on one High-Speed board | Solved | Declare one `--robot.sensors` entry per module, all on the same `port` with distinct `module_index`. Instances share one board + one auto-push stream under the hood (`_SharedHighSpeedBoard`); each records its own `observation.sensors.<name>` column |
| High-frequency rerun logging from the read thread can crowd the viewer | Mitigated | `poll_rate_hz` downsampling keeps the logged rate sane (e.g. 30 Hz) |
| Two USB cameras drop frames on Windows (`latest frame is too old` / `read failed`) | Solved | USB 2.0 bandwidth saturation from uncompressed streams. Add `fourcc: MJPG` to each camera to send compressed frames (~10x less bandwidth). If it persists, plug cameras into ports on different USB controllers, or drop to `fps: 15` |
| Two sensors on one board: second sensor's connect crashes the stream (`short read` / `frame head aa55 not found`) | Solved | The second sensor's `read_distribution_point_count` collided with the first sensor's running auto-push stream on the shared port. Fixed by pre-caching every active module's point count at board open (`_SharedHighSpeedBoard._open`), before any stream starts |
| Live rerun Paxini panels empty because entity paths use dots | Solved | rerun splits entity paths on `/` only, so a dotted `observation.sensors.<name>` is ONE opaque path-part that a `/observation/sensors/**` wildcard can't match. Fixed by logging tactile data under a real slash hierarchy `observation/sensors/<name>/...` (`PaxiniSensor._log_to_rerun` and the `log_rerun_data` tactile branch) |
| Two fingertips overlap in one 3D rerun panel | Solved | The record script passes the Paxini sensor names into `init_rerun`, which builds one 3D panel per fingertip (first top-right, second bottom-right replacing the Hall panel, extras as tabs) instead of a single combined cloud |
| Recorded dataset folder has a timestamp suffix (`two_finger_test_20260807_183636`) | Known | `lerobot-record` appends a timestamp to the `repo_id`. Load a local dataset by its full timestamped folder name, or read `meta/info.json` + the parquet directly (see `lerobotac/verify_dataset.py`). `LeRobotDataset("<repo_id>")` without the suffix hits the Hub and 404s for a local-only (`push_to_hub=False`) dataset |
| SO-101 follower gripper motor (id 6) "no status packet" on torque enable | Hardware | Intermittent connection on the last servo in the chain; reseat the gripper daisy-chain cable and power-cycle the arm. Not sensor-related |
---
## 7. References
- paxini-sdk (this project's driver): <https://github.com/Jingyi-Z/paxini-sdk>
- LeRobot fork with the sensor framework: <https://github.com/Jingyi-Z/lerobotac> (`hall-sensor` branch)
- Companion doc — MLX90393 Hall sensor: Doc #06
- Vendor reference package: *PaXini PX-6AX GEN3 product package_20251202* (`Hand_UI.py`, `USB_UI.py`, `Read_Single_Sensor_*.py`, *Communication Board Communication Protocol_V1.0.5* PDF)
- Upstream LeRobot: <https://github.com/huggingface/lerobot>
---
*Last updated: 2026-05-20*
