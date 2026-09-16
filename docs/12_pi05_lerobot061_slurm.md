# 12. Training pi0.5 with LeRobot 0.6.1 on a Slurm cluster

Doc 10 trained pi0.5 on LeRobot 0.4.x on a single workstation. That path has
since rotted: the current `lerobot/pi05_base` checkpoint on the Hub no longer
loads on 0.4.x. This doc covers the migration to LeRobot 0.6.1 and a working
Slurm recipe for both full fine-tune and LoRA, including notes for aarch64
(GH200) nodes where x86 wheels do not apply.

Companion docs: `10_pi05_training.md` (pi0.5 basics, dataset integrity,
gated tokenizer), `11_act_slurm_cluster_training.md` (Slurm survival:
buffering, storage, walltime).

---

## 1. Three ways 0.4.x fails with pi0.5 today

Each of these produced a dead job before the version question was settled.
Knowing them saves a day of debugging:

1. **Forked transformers requirement.** The 0.4.x `pi` extra pins a LeRobot
   fork of transformers (branch `fix/lerobot_openpi`). On stock transformers
   the checkpoint loads but computes wrong numerics, so the model hard-fails
   a marker-module check (`transformers.models.siglip.check`) on purpose.
   The error message ("An incorrect transformer version is used") does not
   mention the fork.
2. **Checkpoint drift.** `lerobot/pi05_base` main gained a
   `relative_actions_processor` step in mid-2026. 0.4.x has no such processor
   and cannot load the current revision. Pinning an old checkpoint revision
   works but freezes you out of upstream fixes.
3. **Camera name mismatch.** pi05_base expects `base_0_rgb`,
   `left_wrist_0_rgb`, `right_wrist_0_rgb`. A dataset with other camera names
   fails validation. Fix at train time with `--rename_map`; cameras that are
   missing entirely after renaming are padded and masked internally, so a
   two-camera rig is fine.

LeRobot 0.6.1 resolves 1 and 2 (stock transformers 5.x, current checkpoints
load) and 3 stays a one-flag fix. The cost: 0.6.x requires Python >= 3.12.

## 2. Environment

On a cluster, build a venv over the site pytorch module so torch comes
prebuilt for the node architecture (this is what makes GH200/aarch64 work):

```bash
module load <site python-3.12 + pytorch module>
python -m venv --system-site-packages $WRK/envs/lerobot061-venv
source $WRK/envs/lerobot061-venv/bin/activate
pip install "lerobot[pi,dataset]==0.6.1" "peft>=0.18,<1" "av>=15,<16"
```

Notes:

- `[pi]` alone is not enough, `[dataset]` is also required. `peft` is needed
  for LoRA, `av` as the video decode fallback.
- On aarch64, torchcodec cp312 wheels exist for this version range; if
  torchcodec still fails to import, LeRobot falls back to PyAV.
- The gated `google/paligemma-3b-pt-224` tokenizer rules from doc 10 section 2
  apply unchanged: accept the license on the account AND have an
  authenticated token on the cluster (`hf auth login`), with HF_HOME pointed
  at project storage, not the small home quota.
- First import from parallel filesystems can sit silent for ~10 minutes at
  near-zero CPU. That is I/O wait, not a hang (doc 11 section on buffering).

## 3. Keep tactile out of the baseline

As in doc 10 section 3, any extra float feature in the dataset is silently
classified as STATE and concatenated onto proprioception. For a vision-only
baseline, train on a derived view with the tactile column dropped, never on
the raw dataset.

## 4. Slurm script, both modes

One script, mode switched by an exported variable:

```bash
#!/bin/bash
#SBATCH --partition=<gpu partition>
#SBATCH --nodes=1
#SBATCH --gpus-per-node=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=100g
#SBATCH --time=24:00:00
#SBATCH --output=<log dir>/%x_%j.log

set -e
source $WRK/envs/lerobot061-venv/bin/activate
export HF_HOME=$WRK/hf_cache
export HF_LEROBOT_HOME=$WRK/hf_cache/lerobot
export PYTHONUNBUFFERED=1

MODE=${MODE:-ft}

COMMON=(
  --dataset.repo_id=<user>/<dataset_vp>
  --dataset.root=$WRK/<dataset_vp>
  --rename_map='{"observation.images.top":"observation.images.base_0_rgb","observation.images.wrist":"observation.images.left_wrist_0_rgb"}'
  --policy.path=lerobot/pi05_base
  --policy.push_to_hub=false
  --policy.dtype=bfloat16
  --policy.gradient_checkpointing=true
  --policy.device=cuda
  --steps=20000
  --save_freq=5000
  --log_freq=50
  --num_workers=8
  --wandb.enable=false
)

if [ "$MODE" = "ft" ]; then
  srun lerobot-train "${COMMON[@]}" --batch_size=16 \
    --output_dir=$WRK/runs/pi05_ft --job_name=pi05_ft
elif [ "$MODE" = "lora" ]; then
  srun lerobot-train "${COMMON[@]}" --batch_size=32 \
    --peft.method_type=LORA --peft.r=16 \
    --output_dir=$WRK/runs/pi05_lora --job_name=pi05_lora
fi
```

Submit as `sbatch --job-name=pi05ft --export=ALL,MODE=ft <script>`.

## 5. Measured performance (GH200 96 GB, 55k-frame dataset)

| Mode | Batch | s/step | 20k steps | Peak mem |
|---|---|---|---|---|
| Full fine-tune (bf16 + grad ckpt) | 16 | 1.37 | ~7.5 h | 37 GB |
| LoRA r=16 | 32 | 1.78 | ~10 h | 20 GB |

Convergence sanity on a ~55k-frame single-task dataset: full fine-tune loss
fell from 0.26 at step 50 to ~0.004 by step 18k with stable gradient norms.
The first minutes are dominated by data loading (`data_s` of several seconds
per step); it drops to ~0.005 s once the workers warm. Do not size walltime
from the first log lines.

## 6. Memory rule of thumb

pi0.5 is ~3.5B parameters. Full fine-tune with Adam needs on the order of
70+ GB even in bf16 with gradient checkpointing, so 40 to 48 GB GPUs (A40,
A100-40G) cannot run it at any batch size, and DDP does not pool memory.
LoRA at r=16 fits comfortably in 24 GB and up. Pick the cluster before
writing the script.
