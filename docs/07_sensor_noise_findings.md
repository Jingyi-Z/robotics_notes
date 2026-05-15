# MLX90393 Sensor Noise — Characterization Findings

This doc records what we learned about the gripper-mounted MLX90393's noise
behavior on our SO-101 setup, as a reference for downstream policy training
and future hardware iteration. The work is summarized here; the underlying
analyses lived in conversation traces and `lerobotac` parquet datasets.

## TL;DR

The sensor is **good enough for tactile-aware ACT training as-is**.
Contact signals (±5000 μT) are 500–1000× larger than any noise floor
measured. No physical shielding, repositioning, or per-episode
recalibration is required. The only code patch needed for clean recordings
is `wait_for_sensor_calibration` in `lerobot-record`.

## Sensor configuration in effect

- Chip: MLX90393 (Adafruit breakout)
- Gain: `GAIN_5X` (the wide-range setting — counterintuitively, "5X" means
  lower internal amplification)
- Resolution: `RES_16` on all axes
- Oversampling: `OSR_2`
- Filter: `FILTER_2`
- Teensy → host frame rate: 100 Hz
- Effective recorder rate: ~62 Hz (~38% of Teensy samples are overwritten
  in the buffer before the 30 Hz recorder drains it; not a problem for
  policy use)
- Units: 1 LSB in the parquet ≈ 0.1 μT (firmware scales μT by 10 before
  packing as int16)

## Noise floors

All values in μT, computed on locally-detrended residuals.

| Condition | Bx σ | By σ | Bz σ |
|---|---|---|---|
| Idle, robot stationary, torque-on | **2.32** | **2.38** | **3.66** |
| Stationary within a motion episode | 2.34 | 2.37 | 3.67 |
| Robot moving (gentle joint sweep) | 4.17 | 2.71 | 4.80 |
| Robot moving (pick-place arc, gripper still) | 8.60 | 2.84 | 4.68 |
| Robot moving (pick-place arc + gripper actuation) | 10.22 | 3.16 | 6.57 |

The idle floor (2.4 / 2.4 / 3.7 μT) matches the MLX90393 datasheet's
typical RMS noise at the configured gain / resolution / OSR / filter
settings. The Z axis is consistently ~1.5× noisier than X/Y, which is
expected from the chip's Hall-element geometry. Noise is white,
Gaussian, and zero-cross-axis-correlated at idle.

## Where motion "noise" actually comes from

Motion increases apparent σ by 1.1× to 4.4×, but most of that is **not
random noise** — it's the deterministic rotation of Earth's ~50 μT field
through the sensor frame as the arm reorients.

Evidence: a linear regression `B = f(sin/cos of joint angles)` explains
**81–94% of the field variance** during motion. The smooth low-frequency
swings on Bx (up to ±90 μT during a pick-place arc) are essentially
fully predictable from joint state.

The gripper-pad magnet contributes a secondary, smaller effect: closing
the gripper increases By's apparent σ by ~2× when the arm is otherwise
stationary, and adding the gripper angle to the regression boosts R² on
Bz by +12% in episodes with gripper actuation. This is the magnet on
the gripper pad shifting position relative to the chip when the pad
deforms.

**Implication for training**: feed both joint state AND raw sensor
reading to ACT. Don't pre-subtract the joint-angle component — the
policy can learn it. The same input also gives ACT access to the
gripper-magnet contribution, which is a real proprioception signal
about pad deformation (i.e. an early contact cue).

## Thermal drift

Over 10 minutes of torque-on stationary recording:

| Axis | Total drift | Range (max−min) |
|---|---|---|
| Bx | +0.42 μT | 1.70 μT |
| By | +0.57 μT | 2.21 μT |
| Bz | +0.26 μT | 1.47 μT |

Drift is **5× smaller than the sample-level σ**. Single-calibration-per-
session is sufficient for any recording up to at least 10 minutes. No
per-episode recalibration is needed.

This applies to *time-based* drift only. Contact-induced drift (the magnet
shifting after a grasp) is a separate question and was *not* measured
cleanly. The earlier `pick_and_place_test_0513_*` dataset showed
per-episode baseline drifts of ±100 μT across 10 contact-involving
episodes, which is plausibly contact-induced and would be worth
re-measuring if it becomes a problem during training.

## Historical issues, now resolved

1. **Bx-always-zero bug** (pre-fix datasets): the chip's X-axis was
   saturating against the int16 rail because of a strong nearby
   ferromagnetic source pushing the resting Bx to ~−1073 μT (~83% of the
   ±1300 μT range at the previous `GAIN_2_5X` setting). Once saturated,
   calibration captured the rail value as the baseline, and every
   subsequent saturated sample produced `raw − baseline = 0` exactly.
   Fix: switched to `GAIN_5X` (wider range, ~±2600 μT). Bx now reads
   real values around zero with the expected noise.

2. **`build_dataset_frame` dropping 2-D sensor features**: the original
   implementation only handled 1-D and image features, silently
   dropping 2-D `FeatureType.SENSOR` arrays. Fixed in commit `0459520`
   on the `hall-sensor` branch of `lerobotac`.

3. **First-frame zeros from incomplete calibration**: the
   `MLX90393Sensor` needs ~1 second to fill its 100-sample baseline
   buffer; if recording starts before then, the first ~30 frames
   contain zeros. Fixed by patching `lerobot-record` to call
   `robot.wait_for_sensor_calibration()` before episode 0.

## What this means in practice

For contact detection during typical motion:

| Use case | Threshold (3σ_motion) |
|---|---|
| Bx-based contact (worst-case motion) | ~30 μT |
| By-based contact (best axis) | ~10 μT |
| Bz-based contact | ~20 μT |

Typical observed contact signals during pick-and-place grasps: ±500 to
±5000 μT. Detection margin is comfortable on every axis.

## Datasets used in this analysis

- `Jingyi-Z/noise_analysis_0514_20260514_170959` — idle floor (30 s)
- `Jingyi-Z/thermal_drift_test_20260514_181952` — 10-minute stationary
- `Jingyi-Z/motion_noise_test_20260514_200145` — three motion episodes

(`Jingyi-Z/pick_and_place_test_0513_20260513_175247` is the pre-fix
dataset and is **not safe for training** — Bx is identically zero across
all samples.)

## Open items for future work

- **Contact-induced drift**: characterize how much the baseline shifts
  after repeated grasps. Only matters if it correlates with task
  performance.
- **Tactile head in ACT**: `FeatureType.SENSOR` is not consumed by
  ACT's forward pass yet. Either expose the sensor as
  `FeatureType.ENV` (cheap) or add a proper sensor branch to ACT
  (clean). Decide after seeing whether vanilla ACT (vision + state)
  succeeds on the task.
- **Multi-sensor support**: the current sensor framework supports
  multiple sensors in the dataset schema, but ACT only consumes one
  `env_state` key. Multi-sensor training requires the proper-branch
  approach above.