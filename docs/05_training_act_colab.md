# Training ACT on SO-101 in Google Colab

This is the cloud-side counterpart to the local record/replay/eval workflow.
Training runs on a Colab GPU (ideally an **A100**); the resulting policy is
pushed to the Hugging Face Hub and pulled back to the laptop for on-robot
evaluation.

The doc has two layers:

- **The basics** mirror the official LeRobot ACT page and the
  "Train a policy" / "Train using Google Colab" sections of the IL tutorial.
- **The walkthrough** mirrors my own notebook `ref/Training_ACT_so101.ipynb`,
  which is itself adapted from the official LeRobot training notebook.

> Authoritative sources:
> - ACT policy: <https://huggingface.co/docs/lerobot/act>
> - Train a policy (incl. Colab): <https://huggingface.co/docs/lerobot/il_robots#train-a-policy>
> - Official Colab notebook: <https://github.com/huggingface/notebooks/blob/main/lerobot/training-act.ipynb>
> - ACT paper: <https://tonyzhaozh.github.io/aloha/>

---

## 1. About ACT

From the official ACT page:

- **Architecture**: transformer encoder/decoder. ResNet-18 vision backbone,
  transformer encoder synthesizes image features + joint state + latent z,
  transformer decoder emits action chunks via cross-attention.
- **Outputs**: a chunk of `k` future actions (joint positions). LeRobot
  streams them at the dataset's FPS during inference.
- **Parameters**: ~80M. Trains in a few hours on a single GPU.
- **Data efficiency**: often works with just ~50 demos.

It's the policy the docs recommend trying first, which is why I'm using it
here.

The Colab notebook trains ACT on
`Jingyi-Z/so101-wrist-pick-place-ball-bowl-v1` (60 episodes, 1 front camera,
6-DoF action + 6-DoF state).

---

## 2. Colab runtime

- **Runtime → Change runtime type → GPU → A100** (or any A100/A6000).
- Confirm you have enough compute units for ~2.5h on A100 (more on weaker
  GPUs).
- Python 3.12 is what current Colab runtimes provide — matches the LeRobot
  install guide's recommendation.

---

## 3. Step-by-step

### Step 1 — Conda (skipped on Colab)

Older versions of my notebook used `condacolab` to bootstrap a conda env, but
that pinned Python to 3.11 while LeRobot wants 3.12. I dropped it and rely
on the Colab system Python.

### Step 2 — Install LeRobot + ffmpeg

```bash
!git clone https://github.com/huggingface/lerobot.git /content/lerobot_repo
%cd /content/lerobot_repo
!pip install -e .
!pip install -e ".[feetech]"           # not strictly needed in Colab, harmless
!pip install \
  "av>=15.0.0,<16.0.0" \
  "datasets>=4.0.0,<5.0.0" \
  "torchcodec>=0.2.1,<0.11.0" \
  "jsonlines>=4.0.0,<5.0.0" \
  "imageio[ffmpeg]>=2.34.0,<3.0.0"

!apt-get update -qq
!apt-get install -y ffmpeg
```

Then make sure the editable repo is on `sys.path`:

```python
!python -V                                # expect 3.12
import sys; print(sys.executable)
sys.path.insert(0, "/content/lerobot_repo/src")
```

> Why these pins? They match the official notebook's working set and the
> versions you can see in my notebook's install log (e.g. `lerobot==0.5.2`,
> `av==15.1.0`, `torchcodec==0.10.0+cu128`, `torch==2.10.0+cu128`).

### Step 3 — Configure Hugging Face token

In Colab → key icon (left sidebar) → add a secret named **`HF_TOKEN`** (or
`HF_write`) with a write-scope token from
<https://huggingface.co/settings/tokens>.

```python
from google.colab import userdata
import os
os.environ["HF_TOKEN"] = userdata.get("HF_TOKEN")    # match your secret name
assert os.getenv("HF_TOKEN"), "Add HF_TOKEN as a Colab secret"
```

Set the HF user (used to name output repos):

```python
HF_USER = "Jingyi-Z"        # ← change to your username
os.environ["HF_USER"] = HF_USER
```

Mount Drive so checkpoints survive a runtime disconnect:

```python
from google.colab import drive
drive.mount('/content/drive')
```

### Step 4 — (Optional) Weights & Biases login

The official guide enables `--wandb.enable=true` in its sample command. If
you want live loss/grad curves:

```python
!pip install wandb
import wandb
wandb.login(key=userdata.get("WANDB_API_KEY"))
```

Or just `wandb login` and paste your key. If you skip this, pass
`--wandb.enable=False` to `lerobot-train` later.

### Step 5 — Preview the dataset

```python
import sys; sys.path.insert(0, "/content/lerobot_repo/src")
import lerobot.utils.import_utils as iu
iu._require_package_cache.clear()

from lerobot.datasets.lerobot_dataset import LeRobotDataset
dataset = LeRobotDataset(f"{HF_USER}/so101-wrist-pick-place-ball-bowl-v1")

print(f"Episodes: {dataset.num_episodes}")
print(f"Frames:   {dataset.num_frames}")
print(f"FPS:      {dataset.fps}")
print(f"Features: {list(dataset.features.keys())}")
```

For my dataset:

- 60 episodes, 26,825 frames, 30 FPS
- Features: `action`, `observation.state`, `observation.images.front`,
  `timestamp`, `frame_index`, `episode_index`, `index`, `task_index`
- Action shape `[6]`, state shape `[6]`, image `[3, 1080, 1920]`

### Step 6 — Train ACT

The headline command. This is the official ACT example, expanded with my
preferred flags. Trains from scratch on episodes 0–49, 100k steps, batch size
8, on a Colab A100:

```bash
!lerobot-train \
  --dataset.repo_id=${HF_USER}/so101-wrist-pick-place-ball-bowl-v1 \
  --dataset.episodes=[0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30,31,32,33,34,35,36,37,38,39,40,41,42,43,44,45,46,47,48,49] \
  --output_dir=/content/drive/MyDrive/lerobot_outputs/act-so101-wrist-pick-place-ball-bowl-v1.4 \
  --job_name=act_v1.4 \
  --policy.type=act \
  --policy.repo_id=${HF_USER}/act-so101-wrist-pick-place-ball-bowl-v1.4 \
  --policy.device=cuda \
  --batch_size=8 \
  --steps=100000 \
  --save_freq=10000 \
  --log_freq=200 \
  --wandb.enable=true \
  --wandb.project=act_v1.4
```

Important flags (mostly per the official tutorial):

| Flag | What it does |
|---|---|
| `--dataset.repo_id` | Hub dataset id (or local `--dataset.root`) |
| `--dataset.episodes=[...]` | Restrict to a subset of episodes (omit for all) |
| `--policy.type=act` | ACT policy — input/output dims auto-inferred from dataset |
| `--policy.repo_id` | Where the final model gets pushed on the Hub |
| `--output_dir` | Local (Drive) output — checkpoints + wandb logs |
| `--policy.device=cuda` | Required on Colab GPU runtimes |
| `--batch_size=8` | Default ACT recommendation; fits on A100 at 1080×1920 |
| `--steps=100000` | Full run (~2.5h on A100) |
| `--save_freq=10000` | Drop a checkpoint every 10k steps |

Output layout per checkpoint (same as the official tutorial):

```text
outputs/train/<job_name>/checkpoints/
  010000/
    pretrained_model/   ← model.safetensors + config.json + processors
    training_state/     ← optimizer + RNG + step number
  020000/
  ...
  last/                 ← copy of the most recent checkpoint
```

### Step 6.5 — Resume training from a checkpoint

The official tutorial shows the clean resume pattern using `--config_path`:

```bash
!lerobot-train \
  --config_path=outputs/train/act_v1.4/checkpoints/last/pretrained_model/train_config.json \
  --resume=true
```

This loads the exact dataset/policy/optimizer configuration from `train_config.json`
and picks up at the saved step.

### Step 6.6 — Fine-tune from another model

To start from existing weights instead of scratch — e.g. fine-tune the v1.2
checkpoint on more episodes:

```bash
!lerobot-train \
  --dataset.repo_id=${HF_USER}/so101-wrist-pick-place-ball-bowl-v1 \
  --policy.path=${HF_USER}/act-so101-wrist-pick-place-ball-bowl-v1.2 \
  --policy.repo_id=${HF_USER}/act-so101-wrist-pick-place-ball-bowl-v1.3 \
  --output_dir=/content/drive/MyDrive/lerobot_outputs/act-so101-wrist-pick-place-ball-bowl-v1.3 \
  --job_name=act_v1.3 \
  --policy.device=cuda \
  --batch_size=8 \
  --steps=100000 \
  --save_freq=10000 \
  --log_freq=200 \
  --wandb.enable=true \
  --wandb.project=act_v1.3
```

Notes:

- `--policy.path` loads pretrained weights as the starting point. Don't also
  pass `--policy.type=act` — type is inferred from the checkpoint.
- This is a new run, so use a new `--policy.repo_id` and `--output_dir`.

### Step 7 — Inspect the saved checkpoint

```bash
!ls -la outputs/train/act-so101-wrist-pick-place-ball-bowl-v1.1/checkpoints/last/pretrained_model/
```

You should see:

```text
config.json
model.safetensors
policy_postprocessor.json
policy_postprocessor_step_0_unnormalizer_processor.safetensors
policy_preprocessor.json
policy_preprocessor_step_3_normalizer_processor.safetensors
train_config.json
```

### Step 8 — Upload to the Hub

The official tutorial uses `huggingface-cli upload` directly:

```bash
!huggingface-cli upload ${HF_USER}/act-so101-wrist-pick-place-ball-bowl-v1 \
  outputs/train/act-so101-wrist-pick-place-ball-bowl-v1/checkpoints/last/pretrained_model
```

Or, for an intermediate checkpoint:

```bash
CKPT=010000
!huggingface-cli upload ${HF_USER}/act-so101-wrist-pick-place-ball-bowl-v1-${CKPT} \
  outputs/train/act-so101-wrist-pick-place-ball-bowl-v1/checkpoints/${CKPT}/pretrained_model
```

Python equivalent (what my notebook actually uses):

```python
from huggingface_hub import HfApi
api = HfApi(token=os.environ["HF_TOKEN"])
repo_id = f"{HF_USER}/act-so101-wrist-pick-place-ball-bowl-v1"
api.create_repo(repo_id=repo_id, repo_type="model", exist_ok=True)
api.upload_folder(
    folder_path="outputs/train/act-so101-wrist-pick-place-ball-bowl-v1/checkpoints/last/pretrained_model",
    repo_id=repo_id,
    repo_type="model",
)
```

If you'd rather not push to the Hub at all, pass `--policy.push_to_hub=false`
to `lerobot-train`.

### Step 9 — (Optional) Upload training state for later fine-tuning

```python
api.upload_folder(
    folder_path="outputs/train/.../checkpoints/last/training_state",
    path_in_repo="training_state",
    repo_id=repo_id,
    repo_type="model",
)
```

### Step 10 — Zip + download (backup)

```bash
!zip -r trained.zip outputs
!cp trained.zip /content/drive/MyDrive/
```

```python
from google.colab import files
files.download('trained.zip')
```

Better: rely on Drive (`--output_dir=/content/drive/MyDrive/...`) so a runtime
disconnect doesn't wipe your checkpoints.

---

## 4. Run history (mine, for reference)

| Tag | Episodes | Steps | From |
|---|---|---|---|
| `act_v1`   | 0–19   | 5,000   | scratch |
| `act_v1.1` | 0–19   | 100,000 | scratch |
| `act_v1.2` | 0–49   | 100,000 | fine-tune of v1.1 (0–19) |
| `act_v1.3` | 0–59   | 100,000 | fine-tune of v1.2 (0–49) |
| `act_v1.4` | 0–49   | 100,000 | scratch |
| `act_v1.5` | 0–59   | 100,000 | scratch |

Lets me reason about whether fine-tuning beats just adding more data.

---

## 5. After training: get the policy onto the robot

The Hub repo from Step 8 is what `lerobot-record --policy.path=...` consumes
on the laptop. See [`04_evaluation.md`](04_evaluation.md).

---

## 6. Variations and extensions

### 6.1 Train a different policy

The same `lerobot-train` flow works for the other policies LeRobot ships;
just swap `--policy.type` and (for VLAs) provide more GPU memory:

- **SmolVLA** — <https://huggingface.co/docs/lerobot/smolvla> — 450M params,
  ~40 GB VRAM, ~4h / 20k steps on A100. `--policy.type` is inferred from the
  base model so you usually don't need to pass it.
- **π0** — <https://huggingface.co/docs/lerobot/pi0> — 3B params, ~80 GB VRAM,
  8+ h / 20k steps.
- **π0.5** — <https://huggingface.co/docs/lerobot/pi05>
- **NVIDIA GR00T N1.5** — <https://huggingface.co/docs/lerobot/groot>
- **X-VLA**, **WALL-OSS** — see the Policies section in the docs sidebar.

For LoRA / PEFT fine-tuning, see
<https://huggingface.co/docs/lerobot/peft_training>.

### 6.2 Multi-GPU

If you outgrow a single GPU:
<https://huggingface.co/docs/lerobot/multi_gpu_training>.

### 6.3 Extra sensor data (AnySkin example)

Store sensor readings as `observation.environment_state` (a 1D float vector)
in the dataset and ACT will pick it up automatically — it adds a transformer
token for that input with no model code changes:

```bash
lerobot-train \
  --dataset.repo_id=${HF_USER}/my_anyskin_dataset \
  --policy.type=act \
  --policy.repo_id=${HF_USER}/act_so101_anyskin \
  --output_dir=outputs/train/act_so101_anyskin \
  --policy.device=cuda
```

Things to watch:

- **Sync** — sensor readings need to be aligned to camera frames at the
  dataset FPS.
- **Normalization** — ACT normalizes inputs automatically, but make sure the
  sensor range isn't wildly different from joint positions.
- **Calibration drift** — recalibrate AnySkin after swapping skin instances.

For modalities that don't fit a flat float vector, write a custom policy
package. See "Bring Your Own Policies":
<https://huggingface.co/docs/lerobot/bring_your_own_policies>.

---

## 7. Common training issues

| Symptom | Likely cause | Fix |
|---|---|---|
| OOM at start | batch too large | Drop `--batch_size` to 4 |
| Loss spikes mid-run | bad episode in dataset | Visualize → drop episode → retrain |
| `--policy.path` errors "shape mismatch" | dataset features changed | Make sure camera dims + state shape match the pretrained ckpt |
| `torchcodec` decode error | AV1 codec missing | Reinstall `av`, `torchcodec`; confirm `ffmpeg 7.x` on path |
| Runtime disconnects mid-run | Colab idle timeout | Use Drive `--output_dir`, restart with `--config_path .../train_config.json --resume=true` |

---

## 8. References

- ACT policy page: <https://huggingface.co/docs/lerobot/act>
- Train a policy (in the IL tutorial): <https://huggingface.co/docs/lerobot/il_robots#train-a-policy>
- Train using Google Colab section: <https://huggingface.co/docs/lerobot/il_robots#train-using-google-colab>
- Official Colab notebook: <https://github.com/huggingface/notebooks/blob/main/lerobot/training-act.ipynb>
- Notebooks index: <https://huggingface.co/docs/lerobot/notebooks>
- ACT paper: <https://arxiv.org/abs/2304.13705>

---

That's the whole loop: record → train (Colab) → push → evaluate (local) →
iterate.
