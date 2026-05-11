# LeRobot Environment Setup

This doc tracks how I install LeRobot for local SO-ARM 101 control,
recording, replay, and on-device evaluation. The workflow follows the
[official LeRobot install guide](https://huggingface.co/docs/lerobot/installation),
plus a few platform-specific notes I hit on Mac / Linux / Windows.

> Authoritative source: <https://huggingface.co/docs/lerobot/installation>
> SO-101 motor extras: <https://huggingface.co/docs/lerobot/so101>

Cloud (Google Colab) training has its own install steps; see
[`05_training_act_colab.md`](05_training_act_colab.md).

---

## 1. Prerequisites (all platforms)

- Python **3.12** (LeRobot is targeted at 3.12; 3.13 is not officially supported)
- `conda` (via [miniforge](https://github.com/conda-forge/miniforge)) — the
  official guide uses this. `uv` / `venv` also work, but then you have to
  manage `ffmpeg` system-wide yourself.
- `git`
- A Hugging Face account + access token from <https://huggingface.co/settings/tokens>
  (write scope for uploading datasets/models)
- (Optional) Weights & Biases account for training run dashboards

LeRobot wants **`ffmpeg` 7.x with the `libsvtav1` encoder**. The conda-forge
build provides this on every platform. `ffmpeg 8.X is not yet supported`.

---

## 2. macOS setup (primary)

### 2.1 Install miniforge

```bash
brew install miniforge
conda init "$(basename "${SHELL}")"
```

Restart the terminal.

### 2.2 Create the environment

```bash
conda create -y -n lerobot python=3.12
conda activate lerobot
```

### 2.3 Install ffmpeg via conda-forge

```bash
conda install ffmpeg -c conda-forge
ffmpeg -version           # check; should be 7.x
ffmpeg -encoders | grep libsvtav1   # confirm libsvtav1 is present
```

If `libsvtav1` is missing, pin the version explicitly:

```bash
conda install ffmpeg=7.1.1 -c conda-forge
```

### 2.4 Install LeRobot from source (editable)

This is what the official guide recommends if you might want to patch the
code. Same flow the Colab notebook uses too.

```bash
git clone https://github.com/huggingface/lerobot.git ~/code/lerobot
cd ~/code/lerobot
pip install -e .

# SO-101 motor support
pip install -e ".[feetech]"
```

If you don't want an editable clone:

```bash
pip install lerobot
pip install 'lerobot[feetech]'
# or pip install 'lerobot[all]' to get everything
```

### 2.5 PyTorch / MPS

`pip install -e .` pulls a torch wheel with MPS support on Apple Silicon. For
policy inference, use `--policy.device=mps`. CPU works but is slow.

### 2.6 Hugging Face login

```bash
huggingface-cli login --token "${HUGGINGFACE_TOKEN}" --add-to-git-credential
# or interactively:
hf auth login
```

For uploading datasets/models, your token needs **write** scope. The
`--add-to-git-credential` flag is what the official tutorial uses so that
subsequent `huggingface-cli upload` and `git push` calls don't re-prompt.

### 2.7 (Optional) wandb

```bash
wandb login
```

### 2.8 Sanity check

```bash
lerobot-find-port --help
lerobot-find-cameras --help
lerobot-setup-motors --help
lerobot-calibrate --help
lerobot-teleoperate --help
lerobot-record --help
lerobot-replay --help
lerobot-train --help
```

---

## 3. Linux setup (Ubuntu 22.04 / 24.04)

### 3.1 System build deps

From the official troubleshooting section — needed if `pip install -e .` errors
out trying to compile `pyav` or related video deps:

```bash
sudo apt-get update
sudo apt-get install -y cmake build-essential python3-dev pkg-config \
  libavformat-dev libavcodec-dev libavdevice-dev libavutil-dev \
  libswscale-dev libswresample-dev libavfilter-dev
```

USB tty access for the SO-ARM 101 motor buses:

```bash
sudo usermod -aG dialout $USER
# log out / back in so the new group takes effect
```

### 3.2 Conda env + ffmpeg

```bash
conda create -y -n lerobot python=3.12
conda activate lerobot
conda install ffmpeg -c conda-forge
```

### 3.3 LeRobot

```bash
git clone https://github.com/huggingface/lerobot.git ~/code/lerobot
cd ~/code/lerobot
pip install -e .
pip install -e ".[feetech]"
```

### 3.4 PyTorch / CUDA

If your machine has an NVIDIA GPU, install a CUDA-matched torch wheel after
the LeRobot install (or before, then re-run `pip install -e .` to make sure
the CUDA wheel sticks). Use `--policy.device=cuda` for training/inference.

### 3.5 Hugging Face login

```bash
huggingface-cli login --token "${HUGGINGFACE_TOKEN}" --add-to-git-credential
```

---

## 4. Windows setup

The cleanest path is **WSL2 + Ubuntu**, which then becomes the Linux flow
above. Native Windows works for some pieces (training, dataset processing) but
not all serial/USB stories.

### 4.1 Recommended: WSL2

```powershell
wsl --install -d Ubuntu-22.04
```

Inside the Ubuntu shell, follow section 3. **Two WSL-specific notes from the
official docs:**

```bash
# evdev needs to come from conda-forge in WSL
conda install evdev -c conda-forge
```

USB pass-through to WSL uses [`usbipd-win`](https://github.com/dorssel/usbipd-win):

```powershell
winget install --interactive --exact dorssel.usbipd-win
usbipd list                       # find your STM32 / CH340 bus id
usbipd bind  --busid <BUSID>
usbipd attach --wsl --busid <BUSID>
```

Inside WSL the arm then shows as `/dev/ttyACM0` (or `/dev/ttyUSB0`).

### 4.2 Native Windows (if you must)

```powershell
# Install miniforge from https://github.com/conda-forge/miniforge
conda create -y -n lerobot python=3.12
conda activate lerobot
conda install ffmpeg -c conda-forge

git clone https://github.com/huggingface/lerobot.git $env:USERPROFILE\code\lerobot
cd $env:USERPROFILE\code\lerobot
pip install -e .
pip install -e ".[feetech]"
```

Notes:

- Use **COM ports** (`COM3`, `COM4`, ...) in `--robot.port=` and
  `--teleop.port=`, not `/dev/tty*`.
- Camera indices behave the same as Linux/macOS: `index_or_path: 0` is the
  first webcam.
- `torchcodec` can be picky on native Windows; falling back to WSL2 is the
  easy fix.

---

## 5. Common troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `lerobot-*` command not found | Conda env not active | `conda activate lerobot` |
| `ffmpeg: command not found` | System / env ffmpeg missing | `conda install ffmpeg -c conda-forge` |
| `libsvtav1` missing on `ffmpeg -encoders` | ffmpeg 8.x installed | Pin: `conda install ffmpeg=7.1.1 -c conda-forge` |
| `pip install -e .` fails compiling pyav | Missing libav* dev headers | Run the apt install in §3.1 |
| `Permission denied: /dev/ttyACM0` | Not in `dialout` group | `sudo usermod -aG dialout $USER`, re-login |
| Port disappears after replug | OS reassigns name | Use a fixed `--robot.id` so calibration survives |
| MPS errors during inference | Old torch | `pip install --upgrade torch torchvision` |
| WSL: arrow keys no effect during record | `$DISPLAY` unset | `export DISPLAY=:0` (see pynput limitations) |

---

## 6. References

- LeRobot install guide: <https://huggingface.co/docs/lerobot/installation>
- LeRobot main docs index: <https://huggingface.co/docs/lerobot/index>
- LeRobot repo: <https://github.com/huggingface/lerobot>

Next: hook up the arm — [`02_hardware_setup.md`](02_hardware_setup.md).
