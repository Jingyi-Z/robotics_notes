# robotics_notes

Jingyi's notebook for working with the **SO-ARM 101** under
[Hugging Face LeRobot](https://github.com/huggingface/lerobot). The end-to-end
loop documented here is:

1. Install LeRobot on a laptop (Mac primary; Linux + Windows also covered).
2. Identify ports, calibrate, and teleoperate the SO-ARM 101.
3. Record + replay demonstrations into a LeRobotDataset.
4. Train an **ACT** policy on Google Colab from that dataset.
5. Pull the trained policy back to the laptop and roll it out on the real robot.

## Documentation

| # | Topic | Doc |
|---|---|---|
| 01 | Environment setup (Mac / Linux / Windows) | [`docs/01_environment_setup.md`](docs/01_environment_setup.md) |
| 02 | SO-ARM 101 hardware setup, calibration, teleop | [`docs/02_hardware_setup.md`](docs/02_hardware_setup.md) |
| 03 | Recording + replaying demonstrations | [`docs/03_record_replay.md`](docs/03_record_replay.md) |
| 04 | Running a trained policy locally (evaluation) | [`docs/04_evaluation.md`](docs/04_evaluation.md) |
| 05 | Training ACT on Google Colab | [`docs/05_training_act_colab.md`](docs/05_training_act_colab.md) |
| 06 | MLX90393 Hall tactile sensor integration | [`docs/06_tactile_sensor.md`](docs/06_tactile_sensor.md) |

## Hardware

- SO-ARM 101 — leader + follower pair, in two vendor variants (WOWROBO, SEEED).
- USB webcam (1080p @ 30 FPS) for the `front` observation.
- MLX90393 Hall-effect magnetometer + Teensy 4.1 bridge for tactile sensing on
  the gripper pad — see doc 06.

## Software

- LeRobot (editable clone of https://github.com/huggingface/lerobot).
- Python 3.12, ffmpeg 4.4+, PyTorch with MPS (Mac) or CUDA (training box).
- Hugging Face Hub for dataset + policy storage.
- (Optional) Weights & Biases for training run dashboards.

## Conventions

- Datasets live at `~/.cache/huggingface/lerobot/<HF_USER>/<DATASET>/` and are
  referenced everywhere by their `repo_id` of the form `<HF_USER>/<DATASET>`.
- Policy checkpoints are pushed to the Hub under `<HF_USER>/<MODEL>`.
- Evaluation rollouts use the `eval_*` prefix in the dataset name so they're
  easy to filter out from training data.
- Per-arm `--robot.id` / `--teleop.id` strings are stable across runs and tie a
  calibration to a specific physical arm.

## Sources

These docs lean on the official LeRobot documentation first, with my own
hands-on notes layered on top:

- LeRobot docs index: <https://huggingface.co/docs/lerobot/index>
- Installation guide: <https://huggingface.co/docs/lerobot/installation>
- SO-101 setup: <https://huggingface.co/docs/lerobot/so101>
- Imitation learning tutorial (teleop / record / replay / train / eval):
  <https://huggingface.co/docs/lerobot/il_robots>
- ACT policy: <https://huggingface.co/docs/lerobot/act>
- Cameras: <https://huggingface.co/docs/lerobot/cameras>
- Official LeRobot Colab notebook (basis for mine):
  <https://github.com/huggingface/notebooks/blob/main/lerobot/training-act.ipynb>

Local references in my Box `ref/` folder:

- `Training_ACT_so101.ipynb` — my Colab training notebook
- `SO-ARM 101 Calibration on Mac.md` — exact commands I used on Mac

## License

See [`LICENSE`](LICENSE).
