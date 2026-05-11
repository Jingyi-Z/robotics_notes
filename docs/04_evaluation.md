# Running a Trained Policy on the Robot (Local Evaluation)

Once you have a trained checkpoint on the Hugging Face Hub (or in
`outputs/train/.../checkpoints/last/pretrained_model/`), evaluate it with
`lerobot-record` + `--policy.path`. There is no separate `lerobot-evaluate`
CLI for the SO-101; the convention is to record an **`eval_*`** dataset so
you can replay and inspect each rollout.

This is the local-side counterpart to training in
[`05_training_act_colab.md`](05_training_act_colab.md). It works the same on
Mac (MPS), Linux/Windows (CUDA), and CPU; only `--policy.device` changes.

> Authoritative source: <https://huggingface.co/docs/lerobot/il_robots#run-inference-and-evaluate-your-policy>
> ACT-specific evaluation example: <https://huggingface.co/docs/lerobot/act#evaluating-act>

---

## 1. What "evaluation" means here

When you run `lerobot-record` with `--policy.path` set:

1. The follower arm reads its joint state and configured camera(s).
2. The policy (ACT, SmolVLA, etc.) consumes the observation and outputs an
   action chunk.
3. LeRobot streams the actions to the follower at the policy's control rate.
4. Observations + executed actions are saved into a new LeRobotDataset, just
   like a teleoperated recording — except the leader arm is not in the loop.

So everything from `03_record_replay.md` (dataset layout, resume, Hub upload)
still applies; the only difference is who/what is producing actions.

From the official tutorial: the command is **almost the same as the recording
command**, with two changes:

1. Add `--policy.path=${HF_USER}/my_policy`
   (or a local `outputs/.../pretrained_model` path).
2. Prefix the dataset name with **`eval_`** so it's easy to filter out from
   training data.

---

## 2. Minimum command (Mac, MPS)

```bash
lerobot-record \
  --robot.type=so101_follower \
  --robot.port=/dev/tty.usbmodem5B420737901 \
  --robot.id=so101_follower_seeed \
  --robot.cameras="{ front: {type: opencv, index_or_path: 0, width: 1920, height: 1080, fps: 30} }" \
  --display_data=true \
  --dataset.repo_id=${HF_USER}/eval_act-so101-wrist-pick-place-ball-bowl-v1 \
  --dataset.num_episodes=10 \
  --dataset.episode_time_s=30 \
  --dataset.reset_time_s=20 \
  --dataset.single_task="pick the red ball and place it in the plastic bowl" \
  --dataset.streaming_encoding=true \
  --dataset.encoder_threads=2 \
  --policy.path=${HF_USER}/act-so101-wrist-pick-place-ball-bowl-v1 \
  --policy.device=mps
```

Key flags:

| Flag | Notes |
|---|---|
| `--policy.path` | Hub repo (`HF_USER/MODEL`) or local `outputs/.../pretrained_model` |
| `--policy.device` | `mps` on Apple Silicon, `cuda` on NVIDIA, `cpu` as a fallback |
| `--dataset.repo_id` | Use an `eval_*` prefix by convention |
| `--dataset.episode_time_s` | Make this ≥ the longest expected rollout |
| `--dataset.reset_time_s` | Long enough to reset the scene by hand |
| `--dataset.streaming_encoding=true` / `--dataset.encoder_threads=2` | Current encoder flags (same as recording) |

The camera config **must match** what the policy was trained on — same key
name (`front`) and same dimensions. ACT keys on feature shapes; if the
observation shape changes, the forward pass errors immediately.

If the policy was trained with tactile inputs, also re-pass the tactile
flags here, exactly as at train time:

```bash
--robot.tactile_sensors='{primary: {"port": "/dev/ttyUSB0", "baud_rate": 2000000}}' \
--policy.use_tactile=true \
--policy.tactile_features='["observation.tactile.primary"]' \
```

Same rule as cameras: the sensor's dict key (`primary`) must match what the
dataset/training used, since it drives the `observation.tactile.<name>`
feature key.

> Tip from the official tutorial: you can leave the leader connected with
> `--teleop.*` flags too, which lets you take over between episodes without
> restarting the script. For pure evaluation runs I skip it.

---

## 3. Saving to a custom location, and resuming

When iterating across policy versions, point each rollout dataset at its own
folder so it's easy to diff later:

```bash
lerobot-record \
  --robot.type=so101_follower \
  --robot.port=/dev/tty.usbmodem5B420737901 \
  --robot.id=so101_follower_seeed \
  --robot.cameras="{ front: {type: opencv, index_or_path: 0, width: 1920, height: 1080, fps: 30} }" \
  --dataset.root=/Users/jz/lerobot_data/eval_act-so101-wrist-pick-place-ball-bowl-v1.2 \
  --dataset.repo_id=${HF_USER}/eval_act-so101-wrist-pick-place-ball-bowl-v1.2 \
  --dataset.num_episodes=10 \
  --dataset.episode_time_s=30 \
  --dataset.reset_time_s=20 \
  --dataset.single_task="pick the red ball and place it in the plastic bowl" \
  --dataset.streaming_encoding=true \
  --dataset.encoder_threads=2 \
  --policy.path=${HF_USER}/act-so101-wrist-pick-place-ball-bowl-v1.2 \
  --policy.device=mps \
  --resume=true
```

`--resume=true` is safe even on the first run for that dataset path (it just
creates the dataset), so I keep it on for repeatability. Remember:
`--dataset.num_episodes` on a resume is the **additional** count, not the
total.

---

## 4. Comparing policy versions

Use parallel names for `policy.repo_id` and the matching `eval_*` dataset:

```text
${HF_USER}/act-so101-wrist-pick-place-ball-bowl-v1.1   ↔   eval_act-...-v1.1
${HF_USER}/act-so101-wrist-pick-place-ball-bowl-v1.2   ↔   eval_act-...-v1.2
${HF_USER}/act-so101-wrist-pick-place-ball-bowl-v1.3   ↔   eval_act-...-v1.3
```

For each version I:

1. Run ~10 rollouts.
2. Mark success/fail from the live `--display_data=true` view.
3. Push the informative `eval_*` datasets to the Hub.
4. Re-open each in the visualizer to compare failure modes.

---

## 5. Deleting a bad rollout dataset

```bash
rm -rf /Users/jz/lerobot_data/eval_act-so101-wrist-pick-place-ball-bowl-v1.2
# or, default cache location:
rm -rf ~/.cache/huggingface/lerobot/${HF_USER}/eval_act-so101-wrist-pick-place-ball-bowl-v1
```

(Confirm before running in a script — gone is gone.)

---

## 6. Tips

- **Match observation keys exactly.** If you trained with
  `observation.images.front`, the camera dict at eval time must produce that
  key (`front: {...}`). Same for wrist cams.
- **MPS vs CUDA.** A Mac M-series runs ACT inference comfortably in real
  time. Larger VLAs like SmolVLA / π0 / GR00T do **not** fit in MPS — run
  those on a CUDA box.
- **Compare against teleop replay.** If a policy fails, run
  `lerobot-replay` on a teleop episode that should solve the task. If replay
  also fails, the issue is calibration, not the policy.
- **Use `--display_data=true`.** Watching joint state + camera live makes it
  obvious when the policy is hallucinating actions vs. when the camera is
  framing wrong vs. when the arm is fighting calibration.

---

## 7. References

- Run inference and evaluate your policy:
  <https://huggingface.co/docs/lerobot/il_robots#run-inference-and-evaluate-your-policy>
- Evaluating ACT specifically: <https://huggingface.co/docs/lerobot/act#evaluating-act>

---

Next: how the checkpoints above were trained —
[`05_training_act_colab.md`](05_training_act_colab.md).
