# 13. Evaluating policies on a custom sensor robot (LeRobot 0.6.1 rollout)

Running a trained policy on real hardware whose robot type is a plugin, not a
stock LeRobot robot, and whose observation carries extra sensor channels beyond
the joints. Covers the four things that silently break such an evaluation, the
extra flag a relative-action policy needs, and the calibration rule that costs a
whole rollout block when you get it wrong.

Companion docs: `04_evaluation.md` (running a trained policy locally),
`11_act_slurm_cluster_training.md` and `12_pi05_lerobot061_slurm.md` (producing
the checkpoints), `08_paxini_tactile_sensor.md` (the sensor side).

---

## 1. Setup shape

One environment, python 3.12, `lerobot==0.6.1` plus the robot plugin installed
editable. `lerobot-rollout` ships with 0.6.1, so no fork is needed:

```bash
conda activate <env>
pip install "lerobot[feetech]==0.6.1"
pip install -e <path to the robot plugin package>
```

The plugin registers its robot type by entry point, so `--robot.type=<name>`
works as soon as it is importable. A processor step shipped inside the plugin
package is registered the same way, as long as the package `__init__.py` imports
it:

```python
from .my_processor_step import MyProcessorStep  # noqa: F401
```

That import matters: the rollout loads the checkpoint's processor pipeline by
registry name, and the plugin import is what puts the name in the registry.

## 2. Four silent breakages

**2.1 A training-only config field blocks loading.** If the training environment
carried a patch that added a config field (say an observation-dropout
probability), the saved `config.json` carries it and a clean evaluation
environment refuses the checkpoint:

```
error: The fields `<field>` are not valid for <Policy>Config
```

The field is inert at inference, so strip it from the downloaded copy:

```bash
python -c "
import json, sys
p = sys.argv[1]
d = json.load(open(p)); print('removed', d.pop('<field>', None))
json.dump(d, open(p, 'w'), indent=2)" <ckpt>/config.json
```

**2.2 Extra sensor channels are filtered out of `observation.state`.** This is
the expensive one. When the rollout context assembles the observation features
it keeps camera features plus scalar features whose names end in `.pos` or
`.vel`. A plugin that exposes extra scalar channels (tactile, force, IMU) under
any other naming loses them: the policy sees a joints-only state, and the
recorded evaluation dataset does not contain the sensor stream either.

Symptom, if a processor step asserts on the state width:

```
AssertionError: observation.state has 6 values, expected 6+312
```

Without such an assert there is no symptom at all, which is worse. Check
directly before the first run:

```bash
python -c "
from lerobot.rollout.context import *  # noqa
import inspect, lerobot.rollout.context as c
print('.pos' in inspect.getsource(c))"
```

Fix in the evaluation environment, keeping the action side untouched:

```python
from pathlib import Path
import lerobot

p = Path(lerobot.__file__).parent / "rollout/context.py"
s = p.read_text()
marker = "keep sensor scalars"
if marker not in s:
    old = 'if isinstance(v, tuple) or (v is float and k.endswith((".pos", ".vel")))\n    }'
    assert s.count(old) == 1
    p.write_text(s.replace(old, 'if isinstance(v, tuple) or v is float  # ' + marker + '\n    }'))
    print("patched")
```

Only the observation filter changes. The action-side filter still selects
`.pos`/`.vel`, which is what keeps arm and base commands correct.

**2.3 Channel order differs from the training rig.** Multi-sensor observations
are flattened in the order the sensors are listed in the robot config, so a
dataset recorded with sensor modules `[10, 18]` and an evaluation rig configured
as `[2, 10]` can present the two halves in opposite order. Nothing errors and
every downstream shape matches, so a policy that depends on channel identity
silently degrades.

Pin the mapping empirically before trusting a run: drive the sensor backend
directly, press one physical sensor, and print per-half magnitudes.

```python
import time
import numpy as np
from <plugin>.<backend> import <Backend>, <BackendConfig>

b = <Backend>(<BackendConfig>(port="/dev/ttyACM1", transport="board", slots=[2, 10], obs_hz=30.0))
b.set_sensor_name("my_sensor")
b.connect(); b.start_continuous_read(); time.sleep(1)
t0 = time.monotonic()
while time.monotonic() - t0 < 10:
    o = b.get_latest_data()
    if o is not None:
        h = np.abs(np.asarray(o).reshape(2, -1)).max(axis=1)
        print(f"half0={h[0]:7.3f}  half1={h[1]:7.3f}", end="\r")
    time.sleep(0.1)
b.disconnect()
```

If the order is reversed relative to training, swap it at evaluation time in the
processor step rather than retraining. A boolean config field is enough:

```python
if self.swap_halves:
    h = self.sensor_dim // 2
    sensor = np.concatenate([sensor[h:], sensor[:h]])
```

Set it in each checkpoint's `policy_preprocessor.json` so the change travels
with the checkpoint instead of living in the environment.

**2.4 Relative-action policies need the RTC engine.** The default synchronous
inference engine rejects a policy whose processor pipeline contains a
relative-actions step, because per-tick re-anchoring makes cached chunk actions
drift:

```
SyncInferenceEngine does not support policies with relative actions for now.
```

Add `--inference.type=rtc`. RTC post-processes a whole action chunk, which is
the correct semantics for those policies. A periodic

```
Indexes diff is not equal to real delay. indexes_diff=3, real_delay=5
```

is the latency tracker noting that inference took more control ticks than the
queue predicted. Occasional lines during warmup are benign; continuous spam with
visibly stuttering motion means raising the execution horizon.

## 3. Small rules that stop a run

- Rollout dataset names must start with `rollout_`. Anything else is rejected
  at context build time.
- A crashed run leaves its dataset directory behind and the next attempt fails
  with `FileExistsError` on `mkdir`. Remove the directory before retrying.
- Camera indices move whenever USB devices are replugged. Check with
  `v4l2-ctl --list-devices`, and confirm which index is which view by grabbing
  one frame each (ffmpeg 6 needs `-update 1` for a single image):
  ```bash
  ffmpeg -loglevel error -f v4l2 -input_format mjpeg -video_size 640x480 \
      -i /dev/videoN -frames:v 1 -update 1 -y /tmp/camN.jpg
  ```
  A camera that only offers MJPEG at the requested size appears to hang when
  asked for raw YUYV; pass `-input_format mjpeg`.
- If the policy expects different camera keys than the robot provides, map them
  at rollout time with `--rename_map`, the same flag used at training time.

## 4. Calibration belongs to the hardware as it is mounted today

A tempting failure mode is to reuse the calibration file from the era the
training data was recorded, on the theory that the policy expects those joint
values. That is backwards. Calibration maps encoder counts to joint angles for
the hardware as currently assembled; if a joint has been remounted since, the
old file is simply wrong, and the policy sees an observation that does not match
the arm's real posture.

Observed on one arm: the recording-era file differed from the current one by
about 95 degrees of homing offset on the wrist roll (the servo horn had been
remounted), and a second, more recent file differed by about 7.6 degrees on the
shoulder pan, which alone produced a consistent several-centimetre overshoot
past the target. The correct choice was the current calibration in every case.

Compare candidates before choosing:

```bash
python -c "
import json, sys
a = json.load(open(sys.argv[1])); b = json.load(open(sys.argv[2]))
for k in a:
    print(f'{k:15s} A={a[k][\"homing_offset\"]:6d} B={b[k][\"homing_offset\"]:6d} diff={a[k][\"homing_offset\"]-b[k][\"homing_offset\"]}')
" <file_a>.json <file_b>.json
```

Roughly 11 encoder counts per degree on these servos, so a 90 count difference
is about 8 degrees. Any joint differing by more than a couple of degrees is
worth explaining before a rollout block is recorded against it.

## 5. Order of operations that works

1. Patch the environment (2.1, 2.2), install the plugin, verify the processor
   step is in the registry from a fresh interpreter.
2. Check cameras and identify views; check the sensor channel order (2.3).
3. Run ONE short dry episode into a throwaway `rollout_*` dataset. It costs two
   minutes and catches every item above.
4. Record scene by scene, five episodes per invocation, `--resume=true` after
   the first, noting the episode index range per scene as you go.
5. Write the dataset card on the robot machine with a heredoc, including the
   episode-to-scene map and any discard ranges, then upload.

Blocks recorded before a configuration fix stay on disk and are excluded by
index in the card rather than deleted, because deletion renumbers episodes.
