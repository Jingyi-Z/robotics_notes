# 11. Training ACT on a Slurm GPU cluster

Doc 05 trains ACT on Colab. This doc covers the same training on a Slurm cluster
(worked out on NCSA Delta, an A40 partition), where three problems will eat your
first day if you do not know about them: a tactile column that silently contaminates
a vision-only baseline, missing FFmpeg shared libraries that crash torchcodec, and
buffered output that makes a healthy job look deadlocked.

Companion docs: `05_training_act_colab.md` (ACT on Colab),
`08_paxini_tactile_sensor.md` (the tactile dataset schema),
`10_pi05_training.md` (pi0.5 on the same corpus).

---

## 1. Environment build

Use a conda env on scratch storage, not home. Home quotas are small and Python
imports off the parallel filesystem are slow either way.

```bash
export SCR=/scratch/<project>/<user>       # your scratch root
mkdir -p $SCR/act/logs $SCR/hf_cache $SCR/envs $SCR/pipcache
module load miniforge3-python              # or your site's conda module
mamba create -y -p $SCR/envs/lerobot python=3.11
export PIP_CACHE_DIR=$SCR/pipcache
$SCR/envs/lerobot/bin/pip install lerobot
```

Point the Hugging Face caches at scratch too:

```bash
export HF_HOME=$SCR/hf_cache
export HF_LEROBOT_HOME=$SCR/hf_cache/lerobot
```

### FFmpeg: the crash you will hit first

`pip install lerobot` does not bring FFmpeg's shared libraries, and cluster
default library paths rarely have them. torchcodec probes FFmpeg 4 through 7,
fails all four, and raises `OSError: Could not load this library` the moment
training touches a video. Both halves of the fix are required:

```bash
mamba install -y -p $SCR/envs/lerobot -c conda-forge "ffmpeg<8"
```

The cap below 8 matters, torchcodec supports only FFmpeg 4 through 7. Then in the
job script, because calling the env's python directly does not put the env's
`lib/` on the linker path:

```bash
export LD_LIBRARY_PATH=$SCR/envs/lerobot/lib:$LD_LIBRARY_PATH
```

## 2. Keeping a vision-only baseline vision-only

If your dataset carries a tactile feature such as
`observation.sensors.paxini_fingertip` with shape `[2, 52, 3]`, LeRobot's
`dataset_to_policy_features` classifies it as `FeatureType.STATE`. Stock ACT
concatenates all STATE features, so 312 tactile dimensions silently join the
6-dim proprioception vector. Nothing crashes. The run simply stops being the
baseline it claims to be. Check before training rather than guessing:

```python
from lerobot.datasets.lerobot_dataset import LeRobotDatasetMetadata
from lerobot.datasets.utils import dataset_to_policy_features
m = LeRobotDatasetMetadata("<user>/<dataset>")
print(dataset_to_policy_features(m.features))
```

`lerobot-train` has no flag to exclude a feature, so the fix lives in the data:
build a derived view of the dataset with the tactile column removed. Videos are
symlinked unchanged, the feature is dropped from `meta/info.json`, tactile stats
columns are stripped from the episode-metadata parquets, and the data parquets
are rewritten without the column. Training then points at the view with
`--dataset.repo_id=<user>/<dataset>_vp --dataset.root=$SCR/<dataset>_vp` and
stays entirely stock. If you write such a rewrite loop, assert the number of
rewritten files is greater than zero. A wrong assumed layout produces a clean
looking no-op.

## 3. Training configuration

One configuration per job, differing only in the episode range:

```bash
lerobot-train --policy.type=act --policy.device=cuda --policy.push_to_hub=false \
  --dataset.repo_id=<user>/<dataset>_vp --dataset.root=$SCR/<dataset>_vp \
  --dataset.episodes="[0,...,70]" --batch_size=8 --steps=100000 \
  --save_freq=20000 --log_freq=200 --eval_freq=0 --wandb.enable=false --seed=1000
```

The model is about 52M learnable parameters. On one A40 with 16 CPUs, 100,000
steps at batch 8 take about 4 hours, so a 6-hour walltime request is comfortable.
Checkpoints land under `<output>/checkpoints/<step>/pretrained_model/`, about
207 MB each.

When comparing runs trained on different episode counts, remember that the same
step budget means more epochs over a smaller set. A lower final loss on the
smaller set partly reflects memorisation. Only a real-robot rollout settles which
policy is better.

## 4. Buffer discipline, or how a healthy job looks dead

The first submission showed 11 minutes of wall time, 11 seconds of CPU, and zero
output. That reads as a deadlock and the jobs were cancelled. It was neither:
stdout was fully buffered and cold Python imports off the parallel filesystem are
genuinely slow. `import torchvision` measured 3.6 minutes once, and the same
import varied by a factor of 73 between login-node runs.

Rules that follow:

- `export PYTHONUNBUFFERED=1` in every job script, plus timestamped stage
  markers before the training command.
- Expect 8 to 15 minutes of silence before the first step line. That is startup,
  not a hang.
- Never diagnose from silence when output is buffered, and never benchmark
  anything on a login node.
- Low CPU with high wall time on a shared filesystem usually means I/O wait.

## 5. Uploading checkpoints

The env's own `hf` CLI works even when the system python is too old for the
standalone installer:

```bash
$SCR/envs/lerobot/bin/hf auth login    # type the token yourself, interactively
$SCR/envs/lerobot/bin/hf upload <user>/act-<run-name> \
  $SCR/act/<run>/checkpoints/100000/pretrained_model . --private
```

## 6. Web-shell survival kit

Many clusters disable SSH keys and the browser-based shell (Open OnDemand) is
the only route. Its websocket drops every few minutes, silently.

- Run anything long under `nohup` with output to a log file. Foreground work is
  lost on the next drop.
- Shell variables do not survive a drop. Use absolute paths in every command.
- Long pastes get truncated mid-transfer. Build files by appending chunks of
  about 15 lines with `cat >>` heredocs, then verify with `wc -l` and `md5sum`.
- Reloading the shell URL reconnects without a fresh 2FA login for a while.
