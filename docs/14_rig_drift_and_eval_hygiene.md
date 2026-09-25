# 14. Rig drift: why a real-robot score expires, and the checks that catch it

A policy checkpoint does not change. The robot under it does. Cameras get
replugged, mounts get bumped, arms get recalibrated, and two weeks later the
same checkpoint on the same task scores nothing like it did before. This doc
covers the cheap health check that detects that in eight minutes, the rules
that keep a comparison valid, and four bench habits that cost a session each
when they are missing.

Companion docs: `04_evaluation.md` (running a trained policy),
`13_policy_rollout_custom_sensor_robot.md` (rollout on a plugin robot),
`02_hardware_setup.md` (arm and camera setup).

---

## 1. The failure this prevents

A multi-policy evaluation campaign was planned: six checkpoints, one scene
block each, roughly an hour apiece. The first policy scored zero on the opening
scene, with a visible and consistent spatial offset on every reach.

The natural reading is that the policy is bad. The correct next move is to
check the rig instead. An older baseline checkpoint, one that had been measured
on the same scene two weeks earlier, was rolled out for five episodes. It
scored far below its earlier number, on the identical weights.

That result says the measuring instrument moved, not the thing being measured.
Every score the campaign would have produced that day would have been a
measurement of accumulated bench drift. The remaining five hours were cancelled.

Drift accumulates from ordinary work: USB replugs that change camera indices,
a camera arm nudged while reaching past it, a gripper remounted, a motor
recalibrated, the table itself shifted. No single event is worth logging. The
sum of sixteen days of them is.

## 2. The A-probe: a rig health check before every eval session

Keep one checkpoint as the permanent reference. It should be an early baseline
whose score you have written down, on a scene you can set up identically.

Open every eval session with it:

```bash
lerobot-rollout \
  --policy.path=/abs/path/to/baseline_checkpoint \
  --robot.type=<your robot> \
  --dataset.repo_id=<user>/rollout_probe_baseline \
  --dataset.num_episodes=5 \
  --strategy.type=episodic \
  --display_data=false
```

Five episodes, one scene, about eight minutes. Then compare against the number
you recorded for that same checkpoint and scene.

- Score within the expected band: the rig is healthy, run the campaign.
- Score far below: stop. Anything measured today is a drift measurement.

The asymmetry is what makes this worth doing. Eight minutes spent every session
against five hours of worthless data collected once.

Record the probe as a real dataset rather than watching it. It becomes the
evidence that the rig was healthy on the day the campaign ran, which is what a
reviewer asking about your protocol actually wants.

## 3. Rules that keep a comparison valid

**Same day, same rig.** Two numbers from different weeks are two different
robots. If you need to compare policy A against policy B, roll them out in the
same session, ideally interleaved, and never quote a number from a previous
session as the comparison arm. Rerun the anchor.

**Re-baseline after any hardware change.** Moving the arm, remounting a camera,
recalibrating a motor, or re-gluing a sensor all invalidate earlier numbers.
Group hardware changes into one maintenance block, then re-measure the anchor
once afterwards rather than drifting through a campaign.

**Hold the hardware still for the length of a campaign.** If a sensor is known
to be biased and a fix is planned, run the whole campaign with the bias in
place and fix it after. A constant known bias across all policies is a fair
comparison. A bias fixed halfway through is two incomparable halves.

**Write down the geometry.** The score belongs to a rig state. Keep the marked
object positions, the camera pose, the calibration file, and the date together,
so that a future run can tell whether it is comparing policies or comparing
rigs.

## 4. Four bench habits, each learned by losing a session

### Address serial devices by stable path, never by ACM number

`/dev/ttyACM0` and `/dev/ttyACM1` swap on reboot, on replug, and sometimes for
no visible reason. Three reshuffles in two days is normal. Use the by-id path
in every command and every config:

```bash
ls -l /dev/serial/by-id/
# usb-1a86_USB_Single_Serial_<serial>-if00 -> ../../ttyACM0
```

```bash
--robot.port=/dev/serial/by-id/usb-1a86_USB_Single_Serial_<serial>-if00
```

The by-id name is derived from the vendor, product, and device serial, so it
follows the device rather than the enumeration order.

### Nothing load-bearing lives in /tmp

A machine that reboots overnight wipes `/tmp` on most distributions. An
editable package install whose source tree lived there comes back as a broken
import with no obvious cause. Install plugins and working copies under `$HOME`:

```bash
mkdir -p ~/plugins && cd ~/plugins
tar xzf ~/backups/<plugin>.tgz
pip install -e ~/plugins/<plugin>
python -c "import <plugin>; print('ok')"
```

Keep a dated tarball of anything installed editable. When the tarball is older
than the code, the gap has to be rebuilt from spec and then verified, which is
the next habit.

### Verify a rebuilt preprocessing step numerically, not by eye

If an online processing step has to be reconstructed, do not trust that it
matches the offline version used to build the training data. Run both on the
same recorded episode and compare arrays:

```python
import numpy as np
offline = build_features_offline(episode)   # the dataset-building path
online  = [step(frame) for frame in episode]
print(np.abs(np.asarray(online) - offline).max())   # want 0.0, accept ~1e-6
```

Any window, padding, or state-reset difference shows up here and nowhere else.
A silently wrong feature at rollout time looks exactly like a bad policy.

### Task strings must match training byte for byte

Language-conditioned policies key on the exact instruction text. A rephrased
task string is an unseen task. Read the strings out of the training dataset
rather than retyping them:

```python
import pandas as pd
print(pd.read_parquet("<dataset>/meta/tasks.parquet")["task"].unique())
```

A preposition is enough to matter. "place it on top of the container" and
"place it into the container" describe different motions, and the policy
learned one of them.

## 5. Reading a score once you know the rig is off

A drifted rig is not useless, it is just a different experiment. Two things
still read cleanly from it.

**Relative robustness on the same day.** Rolling several policies on the same
drifted rig compares how much each one degrades. That is a real robustness
result, and arguably a more informative one than a clean-rig score, provided
you say plainly that the rig was off.

**Failure mode, not failure rate.** Watching *how* a policy fails under a known
geometric offset tells you whether it has spatial slack. A policy that still
completes the task with a visible offset has absorbed the error. A policy that
misses entirely has not. The rates from that session stay unpublished; the
qualitative split is sound.

What cannot be read is an absolute success rate, or any comparison against a
number from another week.

## 6. Session checklist

```
[ ] serial devices addressed by /dev/serial/by-id path
[ ] plugin imports from ~/ and not /tmp
[ ] task strings read from the training dataset's meta/tasks.parquet
[ ] A-probe: 5 episodes, reference checkpoint, reference scene
[ ] probe score compared against the recorded number, go / no-go decided
[ ] all policies for this comparison rolled out today, on this rig
[ ] hardware untouched until the campaign ends
[ ] rig state noted with the results: date, calibration file, camera pose
```
