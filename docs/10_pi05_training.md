# 10. Training pi0.5 on sotac (A0 vision-only baseline)

First VLA training run on the curated tactile corpus. Doc 09 covers ACT on
tactile data; this doc covers the pi0.5 backbone, the A0 vision-only baseline
that every later tactile condition is measured against, and the four bugs that
had to be fixed to get a valid run.

Companion docs: `08_paxini_tactile_sensor.md` (sensor + dataset),
`09_tactile_act_experiments.md` (ACT ablation design).

---

## 1. Why A0 comes first

A0 is pi0.5 with vision and proprioception only, no tactile. It is the control
condition for the whole study. Before building any tactile encoder, A0 answers
one question:

> Does vision-only leave headroom for tactile to help?

Gate: per-task success between 40 and 70 percent. Above 80 percent means the
tasks are already solved and no tactile gain is measurable, so the task set
must change before anything else is built. Below 20 percent means the problem
is data or training, not modality.

**Recorded prediction (before results):** overall success modest, uncertain
because the dataset is small; cup expected hardest.

---

## 2. Environment

LeRobot 0.4.x ships pi05 natively. The `hall-sensor` fork is NOT needed for A0,
because A0 uses no tactile code. Stock upstream in a clean venv is sufficient
and avoids blocking on the fork port.

```bash
python -m venv venv && source venv/bin/activate
pip install 'lerobot[dataset,pi,training]'
export HF_HOME=/workspace/hf
hf auth login
```

The base `lerobot` install is not enough. Three extras are required:
`dataset` (HF datasets backend), `pi` (PaliGemma / pi0 stack),
`training` (accelerate).

**Gated repo.** pi05 pulls its tokenizer from `google/paligemma-3b-pt-224`,
which is gated. Two things are needed, and having one without the other still
gives a 401:

1. License accepted on the account at
   <https://huggingface.co/google/paligemma-3b-pt-224>
2. An authenticated token present on the training machine. A fine-grained
   read token must have **Read access to public gated repos** enabled.

---

## 3. Bug 1: tactile is silently classified as STATE

`lerobot/utils/feature_utils.py::dataset_to_policy_features` maps dataset keys
to policy features with this chain:

```python
elif key == OBS_ENV_STATE:      type = FeatureType.ENV
elif key.startswith(OBS_STR):   type = FeatureType.STATE
elif key.startswith(ACTION):    type = FeatureType.ACTION
else:                           continue
```

`observation.sensors.paxini_fingertip` matches the `startswith` branch and is
labeled `FeatureType.STATE` with shape (2, 52, 3). Nothing downstream excludes
it. Verified directly:

```
action                              FeatureType.ACTION (6,)
observation.state                   FeatureType.STATE  (6,)
observation.images.wrist            FeatureType.VISUAL (3, 480, 640)
observation.images.top              FeatureType.VISUAL (3, 480, 640)
observation.sensors.paxini_fingertip FeatureType.STATE (2, 52, 3)   <-- wrong
```

**Consequence if unnoticed:** the "vision-only" baseline would concatenate 312
tactile values onto the 6 joint positions. Every A0 vs A1 comparison would be
meaningless, and nothing would error.

**Fix.** A wrapper script that monkeypatches the function. Two patches are
required, not one: `policies/factory.py` does
`from lerobot.utils.feature_utils import dataset_to_policy_features`, which
binds its own module-level name at import time, so patching only the
`feature_utils` attribute misses it.

**Standing rule.** Every condition A0 through A4 needs explicit feature
routing. Never rely on default key classification for a custom modality.

---

## 4. Bug 2: fork bomb from an unguarded entry point

Calling `main()` at module top level in the wrapper meant every dataloader
worker re-imported the module and re-ran `main()`, each spawning its own
workers. Symptom: `Creating policy` printed dozens of times at an identical
timestamp, and the machine locked up.

**Fix.** `main()` goes inside `if __name__ == "__main__":`. The monkeypatches
stay OUTSIDE the guard, so workers still inherit them when they re-import.

Final `train_a0.py`:

```python
import lerobot.utils.feature_utils as fu
_orig = fu.dataset_to_policy_features

def filtered(features):
    return _orig({k: v for k, v in features.items()
                  if k != "observation.sensors.paxini_fingertip"})

fu.dataset_to_policy_features = filtered
import lerobot.policies.factory as pf
pf.dataset_to_policy_features = filtered

if __name__ == "__main__":
    from lerobot.scripts.lerobot_train import main
    main()
```

---

## 5. Bug 3: stale episode metadata in the HF snapshot cache

Training died with:

```
IndexError: Invalid key: 28564 is out of bounds for size 25401
```

The hub's `meta/episodes/` holds one file with 63 rows. The local snapshot
cache held three (`file-000`, `file-001`, `file-002`), because files deleted
upstream persist in the local cache. LeRobot concatenates every parquet it
finds there.

| Source | Episodes | Frames |
|---|---|---|
| `meta/info.json` | 63 | 25,401 |
| data parquet | 63 | 25,401 |
| cached `meta/episodes` (3 files) | **78** | **32,673** |

**Fix.** `rm -rf $HF_HOME/lerobot/hub/datasets--<user>--<dataset>`, or download
to a local dir and pass `--dataset.root`.

**Standing rule** (reinforces the freeze-numbering lesson from the 2026-08-26
curation sprint): assert metadata consistency before every training run.

```python
from lerobot.datasets.lerobot_dataset import LeRobotDatasetMetadata
m = LeRobotDatasetMetadata('Jingyi-Z/sotac')
assert len(m.episodes) == m.info.total_episodes
assert sum(m.episodes["length"]) == m.info.total_frames
```

TODO: add this to `preflight.py`.

Separately, the hub repo itself still needs cleaning with
`HfApi.upload_folder(delete_patterns=...)`; other users pulling sotac fresh
will not hit this, but any stale orphans on the hub should go.

---

## 6. Bug 4: disk, not memory, is the binding constraint

A pi0.5 checkpoint is **41 GB**, not the ~16 GB the weight count suggests:

| Component | Size |
|---|---|
| `pretrained_model` (weights) | 16 GB |
| `training_state` (optimizer) | 25 GB |
| **total per checkpoint** | **41 GB** |

At `save_freq=2500` over 30,000 steps that is 12 checkpoints, 492 GB. The run
died at `No space left on device` on a 150 GB disk, twice, at different
`save_freq` values.

**Mitigations, in order of preference:**

1. `save_freq=6000` (5 checkpoints, ~205 GB) still overflows 150 GB. Budget
   `steps / save_freq * 41 GB` explicitly.
2. Delete `training_state` from old checkpoints once they are uploaded. Only
   the checkpoint being resumed from needs it. This frees 25 GB each while
   keeping every weight file.
3. Upload `pretrained_model` to the Hub and delete locally.

**For ACCESS:** request scratch accordingly, or save weights only. Disk, not
GPU-hours, is the limiting resource for this workload.

---

## 7. Episode exclusions (APPLIES IDENTICALLY TO A0 THROUGH A4)

| Episodes | Reason |
|---|---|
| 24, 25, 33, 35 | Flagged |
| 39, 45, 48 | Failure |

63 minus 7 = **56 episodes, 22,506 frames**.

- [ ] TODO: record whether these indices are curated (0 to 62) or raw
      numbering. Standing rule: always state the numbering system.
- [ ] TODO: move these labels into `annotations/episode_annotations.json` so
      they travel with the dataset.

A baseline trained on 56 episodes compared against a tactile condition trained
on 63 is not a comparison. Lock this set.

---

## 8. Measured performance (RTX PRO 6000 Blackwell, 96 GB)

| Metric | Value |
|---|---|
| torch | 2.11.0+cu128, driver 590.48.01 |
| Trainable params | 4,143,404,816 (full fine-tune) |
| Batch 8 | 1.09 to 1.14 step/s, ~84 GB peak |
| Batch 16 | **OOM** at 96 GB |
| 30,000 steps at batch 8 | ~7.5 hours |
| Cost on rented GPU | ~$10 per seed at $1.31/hr |

Batch 16 needs `--policy.gradient_checkpointing=true`, trading roughly 30
percent speed for memory.

**Budget correction.** Earlier planning assumed 25 to 30 GPU-hours per seed.
The real figure is 8 to 10. A 15-run sweep is roughly 120 to 150 GPU-hours, far
inside the ACCESS Delta GPU allocation.

---

## 9. Full fine-tune, not LoRA

Decision and reasoning:

1. Full fine-tune fits in 96 GB and costs about $10 per seed. LoRA's usual
   justification (full FT infeasible) does not apply here.
2. A weak baseline is the easiest way to manufacture a fake tactile gain. If
   A0 with LoRA scores 45 percent, that is ambiguous between "headroom exists"
   and "undertrained baseline".
3. TacVLA (arXiv 2603.12665) compares against a full fine-tune pi0.5 baseline.
   Ours must be comparable to the closest competing paper.

**Overfitting is the real risk, not capacity.** At batch 8, loss reached 0.004
by step 27K, roughly 9.5 epochs over 56 episodes. Mitigation is checkpoint
selection, not LoRA: save several and evaluate them all, do not assume the last
is best.

`train_expert_only` (freeze the VLM, train only the action expert) is the
standard middle path in this literature and is worth an ablation later. LoRA is
not.

---

## 10. Commands

```bash
# integrity check BEFORE training
python - <<'EOF'
from lerobot.datasets.lerobot_dataset import LeRobotDatasetMetadata
m = LeRobotDatasetMetadata('Jingyi-Z/sotac')
assert len(m.episodes) == m.info.total_episodes, (len(m.episodes), m.info.total_episodes)
assert sum(m.episodes["length"]) == m.info.total_frames
print("meta consistent")
EOF

# A0 run
EPS=$(python -c "
drop={24,25,33,35,39,45,48}
print(','.join(str(i) for i in range(63) if i not in drop))")

PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True python train_a0.py \
  --dataset.repo_id=Jingyi-Z/sotac \
  --dataset.episodes="[$EPS]" \
  --policy.type=pi05 \
  --policy.pretrained_path=lerobot/pi05_base \
  --policy.push_to_hub=false \
  --steps=30000 --batch_size=8 --num_workers=8 \
  --save_freq=6000 \
  --output_dir=outputs/a0_seed1

# resume from the last good checkpoint
python train_a0.py \
  --config_path=outputs/a0_seed1/checkpoints/018000/pretrained_model/train_config.json \
  --resume=true

# upload weights only
hf upload Jingyi-Z/pi05_sotac_a0_seed1 \
  outputs/a0_seed1/checkpoints/018000/pretrained_model 018000 \
  --repo-type model --private
```

---

## 11. Dataset notes relevant to interpretation

- **Language is a 3-way task ID.** `meta.tasks` holds exactly three fixed
  strings, one per task group (red foam ball, orange rubber ball, red cup). No
  compositional instruction-following claim can be made from this dataset.
- **Videos are AV1.** Software decode is slow. If GPU utilization drops below
  50 percent at larger batch sizes, raise `--num_workers` before blaming the
  model.

---

## 12. Checkpoints produced

`Jingyi-Z/pi05_sotac_a0_seed1`, folders `006000`, `012000`, `018000`, `024000`.

Evaluate at least 012000 and 018000; loss had flattened well before 24K, so the
later checkpoints are more likely overfit than better.

---

## 13. Open items

- [ ] Gate 0 evaluation: 20 rollouts per task, checkpoints 012000 and 018000
- [ ] Add the metadata-consistency assertion to `preflight.py`
- [ ] Confirm numbering system for the 7 excluded episodes
- [ ] Clean stale files from the sotac hub repo (`delete_patterns`)
- [ ] Port `hall-sensor` to LeRobot v0.4.x (needed for A1 onward, not for A0)
- [ ] Seeds 2 and 3 once ACCESS Delta allocation comes online
