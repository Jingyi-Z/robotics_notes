# Recording and Replaying Demonstrations

Once teleop works ([`02_hardware_setup.md`](02_hardware_setup.md)) you can
start recording episodes for imitation learning. The official walkthrough I
follow lives at <https://huggingface.co/docs/lerobot/il_robots>; this doc
mirrors that flow with my SO-101 commands plugged in.

The three CLIs covered here:

- `lerobot-record` — leader→follower demonstrations into a LeRobotDataset
- `lerobot-replay` — play a recorded episode back on the follower
  (no leader required)
- The Hub `visualize_dataset` Space — browse a dataset in your browser

> Authoritative source: <https://huggingface.co/docs/lerobot/il_robots>
> Dataset format: <https://huggingface.co/docs/lerobot/lerobot-dataset-v3>

---

## 1. Conventions

- **`repo_id`** uses `HF_USER/DATASET_NAME` form even before uploading. The
  dataset is materialized locally at
  `~/.cache/huggingface/lerobot/<repo_id>/`.
- **Task instruction** — `--dataset.single_task="..."` is stored on every
  episode as the language description. Keep it specific; this is the prompt a
  VLA model will eventually see.
- **Episode length** — `--dataset.episode_time_s` is the cap (seconds) per
  episode; `--dataset.reset_time_s` is the pause between episodes for you to
  reset the scene. Both default to 60s.
- **Number of episodes** — `--dataset.num_episodes` (default 50).

### Hugging Face login (one-time)

```bash
huggingface-cli login --token "${HUGGINGFACE_TOKEN}" --add-to-git-credential
```

Then grab your HF username into a shell variable so the commands below stay
copy-pasteable:

```bash
HF_USER=$(hf auth whoami | awk -F': *' 'NR==1 {print $2}')
echo $HF_USER
```

---

## 2. Record a dataset (SEEED arms, front camera, pick-and-place)

```bash
lerobot-record \
  --robot.type=so101_follower \
  --robot.port=/dev/tty.usbmodem5B420737901 \
  --robot.id=so101_follower_seeed \
  --robot.cameras="{ front: {type: opencv, index_or_path: 0, width: 1920, height: 1080, fps: 30} }" \
  --teleop.type=so101_leader \
  --teleop.port=/dev/tty.usbmodem5B421385081 \
  --teleop.id=so101_leader_seeed \
  --display_data=true \
  --dataset.repo_id=${HF_USER}/so101-pickplacetest \
  --dataset.num_episodes=20 \
  --dataset.single_task="Pick up the red ball and place it in the plastic bowl" \
  --dataset.episode_time_s=15 \
  --dataset.reset_time_s=2 \
  --dataset.streaming_encoding=true \
  --dataset.encoder_threads=2
```

Notes (most of these from the official `Record function` section):

- The dataset is stored at `~/.cache/huggingface/lerobot/${HF_USER}/so101-pickplacetest`.
- By default, `lerobot-record` **pushes to the Hub** when the run finishes.
  Pass `--dataset.push_to_hub=false` to keep it local until you've cleaned bad
  episodes.
- `--dataset.streaming_encoding=true --dataset.encoder_threads=2` are the
  current recommended encoder flags — they reduce peak disk usage by encoding
  videos as recording progresses.
- `--display_data=true` opens a `rerun` window with live camera frames and
  joint state. I leave it on while recording.

### Keyboard shortcuts during recording

From the official tutorial (these replaced the older space/q/r bindings):

- **Right Arrow (`→`)** — early-stop the current episode (or skip the reset
  window) and move on.
- **Left Arrow (`←`)** — cancel the current episode and re-record it.
- **Escape (`ESC`)** — stop the session, encode videos, and upload the
  dataset.

Linux WSL gotcha: if the arrow keys don't work, set `$DISPLAY` —
[pynput limitations](https://pynput.readthedocs.io/en/latest/limitations.html#linux).

---

## 3. Resume a run

If a run was cut short, re-run the same command with `--resume=true`.
**Important:** when resuming, `--dataset.num_episodes` is the **number of
additional episodes**, not the total.

```bash
lerobot-record \
  --robot.type=so101_follower \
  --robot.port=/dev/tty.usbmodem5B420737901 \
  --robot.id=so101_follower_seeed \
  --robot.cameras="{ front: {type: opencv, index_or_path: 0, width: 1920, height: 1080, fps: 30} }" \
  --teleop.type=so101_leader \
  --teleop.port=/dev/tty.usbmodem5B421385081 \
  --teleop.id=so101_leader_seeed \
  --display_data=true \
  --dataset.repo_id=${HF_USER}/so101-wrist-pick-place-ball-bowl-v1 \
  --dataset.num_episodes=10 \
  --dataset.single_task="Pick up the red ball and place it in the plastic bowl" \
  --dataset.episode_time_s=30 \
  --dataset.reset_time_s=5 \
  --dataset.streaming_encoding=true \
  --dataset.encoder_threads=2 \
  --resume=true
```

To start a dataset over from scratch, **manually delete** the dataset
directory first (`rm -rf ~/.cache/huggingface/lerobot/...`).

---

## 4. Visualize the dataset

### On the Hub

If the dataset has been pushed (`--dataset.push_to_hub=true`, the default),
paste the repo id into the
[`lerobot/visualize_dataset` Space](https://huggingface.co/spaces/lerobot/visualize_dataset):

```text
echo ${HF_USER}/so101-pickplacetest
```

Or jump straight to:

```text
https://huggingface.co/spaces/lerobot/visualize_dataset?path=%2F<HF_USER>%2F<DATASET>%2Fepisode_0
```

### Local

The legacy CLI helper is still around:

```bash
lerobot-dataset-viz \
  --repo-id ${HF_USER}/so101-wrist-pick-place-ball-bowl-v1 \
  --episode-index=0
```

---

## 5. Upload to the Hub (manual)

If you recorded with `--dataset.push_to_hub=false`, push the dataset later
with `huggingface-cli upload`:

```bash
huggingface-cli upload \
  ${HF_USER}/so101-wrist-pick-place-ball-bowl-v1 \
  ~/.cache/huggingface/lerobot/${HF_USER}/so101-wrist-pick-place-ball-bowl-v1 \
  --repo-type dataset
```

(Match the local cache path under `~/.cache/huggingface/lerobot/` to your
actual dataset.)

---

## 6. Replay an episode on the follower (no leader needed)

This is the cleanest sanity check that the dataset is sane and that the
follower is calibrated against the same frame as when it was recorded.

```bash
lerobot-replay \
  --robot.type=so101_follower \
  --robot.port=/dev/tty.usbmodem5B420737901 \
  --robot.id=so101_follower_seeed \
  --dataset.repo_id=${HF_USER}/so101-wrist-pick-place-ball-bowl-v1 \
  --dataset.episode=0
```

What it does: streams the recorded `action` (joint targets) at the dataset's
FPS. If the arm tracks well, your calibration matches what was captured. If
not, recalibrate the follower (see
[`02_hardware_setup.md`](02_hardware_setup.md#24-calibrate)).

---

## 7. Cleaning up

```bash
rm -rf ~/.cache/huggingface/lerobot/${HF_USER}/so101-pickplacetest
```

(`sudo` is only needed if some files were created as root, which only happens
if you ran lerobot under sudo by mistake.)

To remove the Hub copy, use the website's "Settings → Delete repository"
button.

---

## 8. Tips from the official docs (and from getting it wrong)

From the `Tips for gathering data` section of the official tutorial:

- For a new task, start with **~50 episodes, ~10 per location**.
- Keep cameras fixed; keep grasping consistent.
- A good rule of thumb: **you should be able to do the task by only looking
  at the camera frames** — if you can't, the policy can't either.
- Once a fixed task works, start introducing variation slowly (more grasp
  positions, different camera angles).

My own lessons:

- **Pick the task description carefully on day one.** It's stored on every
  episode and survives uploads. Changing it later means re-uploading or
  hand-patching the dataset JSON.
- **`reset_time_s` should be long enough to actually reset the scene.** 2s is
  fine for a fixed object; 5+ s for varied starting positions.
- **Don't change camera resolution between runs of the same dataset.** ACT
  and every other policy key on feature shape; the dataset will refuse to
  merge.
- **Match camera *keys* to what the policy expects** —
  `observation.images.front` vs. `observation.images.wrist`, etc.

---

## 9. References

- Imitation Learning tutorial: <https://huggingface.co/docs/lerobot/il_robots>
- What makes a good dataset: <https://huggingface.co/blog/lerobot-datasets#what-makes-a-good-dataset>
- LeRobotDataset format: <https://huggingface.co/docs/lerobot/lerobot-dataset-v3>

---

Next: train a policy on the dataset — [`05_training_act_colab.md`](05_training_act_colab.md).
Or skip ahead to running a trained policy on the arm —
[`04_evaluation.md`](04_evaluation.md).
