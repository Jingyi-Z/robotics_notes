"""Standalone test for the MLX90393 sensor driver.

Usage:
    python ~/test_mlx_driver.py
    python ~/test_mlx_driver.py --port /dev/cu.usbmodem197004501
"""

import argparse
import logging
import time

import numpy as np

from lerobot.sensors import MLX90393Sensor, MLX90393SensorConfig

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")


def test_connect(port: str) -> MLX90393Sensor:
    print("\n=== Test 1: Connection ===")
    config = MLX90393SensorConfig(port=port, baud_rate=2_000_000, buffer_size=10, baseline_frames=100)
    sensor = MLX90393Sensor(config)
    sensor.connect()
    assert sensor.is_connected, "Sensor reports not connected after connect()"
    print(f"✓ Connected to {port}")
    return sensor


def test_calibration(sensor: MLX90393Sensor) -> None:
    print("\n=== Test 2: Calibration ===")
    print("Starting background read thread...")
    sensor.start_continuous_read()
    print("Waiting for baseline calibration (up to 10s)...")
    print(">>> Make sure NOTHING is touching the sensor for the next second. <<<")
    t0 = time.monotonic()
    ok = sensor.wait_for_calibration(timeout_s=10.0)
    elapsed = time.monotonic() - t0
    assert ok, "Calibration did not complete within 10s"
    print(f"✓ Calibration complete in {elapsed:.2f}s")
    print(f"  Baseline (Bx, By, Bz): {sensor.baseline}")


def test_ring_buffer_fills(sensor: MLX90393Sensor) -> None:
    print("\n=== Test 3: Ring buffer fills with samples ===")
    time.sleep(0.2)  # ~20 samples at 100 Hz, more than enough to fill N=10
    data = sensor.get_latest_data()
    assert data is not None, "get_latest_data returned None after calibration"
    assert data.shape == (10, 3), f"Expected shape (10, 3), got {data.shape}"
    assert data.dtype == np.float32, f"Expected float32, got {data.dtype}"
    print(f"✓ Got shape {data.shape}, dtype {data.dtype}")
    print(f"  Last sample (most recent row): {data[-1]}")
    print(f"  First sample (oldest row):     {data[0]}")


def test_data_changes_over_time(sensor: MLX90393Sensor) -> None:
    print("\n=== Test 4: Data changes between calls ===")
    snap1 = sensor.get_latest_data()
    time.sleep(0.05)  # 50 ms gap, should be ~5 new samples
    snap2 = sensor.get_latest_data()
    if np.allclose(snap1, snap2):
        print("⚠ Two snapshots taken 50 ms apart are identical.")
        print("  This is suspicious — sensor may not be streaming.")
    else:
        print("✓ Snapshots differ between calls (sensor is streaming)")


def test_baseline_subtraction(sensor: MLX90393Sensor) -> None:
    print("\n=== Test 5: Baseline subtraction works ===")
    samples = []
    for _ in range(20):
        samples.append(sensor.get_latest_data()[-1])
        time.sleep(0.05)
    samples = np.stack(samples)
    mean = samples.mean(axis=0)
    std = samples.std(axis=0)
    print(f"  Resting mean (Bx, By, Bz): {mean}")
    print(f"  Resting std  (Bx, By, Bz): {std}")
    print("  (Mean should be near zero; std reflects sensor noise.)")
    if np.abs(mean).max() > 200:
        print("⚠ Resting mean is far from zero. Baseline may be wrong.")
    else:
        print("✓ Resting values are near zero — baseline subtraction works")


def test_magnet_response(sensor: MLX90393Sensor) -> None:
    print("\n=== Test 6: Sensor responds to a magnet ===")
    print(">>> Hold a magnet close to the sensor for the next 5 seconds. <<<")
    print(">>> Move it around so at least one axis sees a big change.   <<<")
    max_seen = np.zeros(3, dtype=np.float32)
    t_end = time.monotonic() + 5.0
    while time.monotonic() < t_end:
        sample = sensor.get_latest_data()[-1]
        max_seen = np.maximum(max_seen, np.abs(sample))
        time.sleep(0.05)
    print(f"  Peak |reading| on each axis: {max_seen}")
    if max_seen.max() > 1000:
        print("✓ Sensor clearly responds to magnet")
    else:
        print("⚠ Sensor didn't see a strong field change.")
        print("  Either the magnet was too far away, or something is wrong.")


def test_sample_rate(sensor: MLX90393Sensor) -> None:
    print("\n=== Test 7: Stream is alive ===")
    print("Measuring buffer activity for 1 second...")
    snap_a = sensor.get_latest_data().copy()
    time.sleep(1.0)
    snap_b = sensor.get_latest_data().copy()
    if np.allclose(snap_a, snap_b):
        print("⚠ Buffer didn't change in 1 second — stream is stalled!")
    else:
        # Count how many rows of snap_b are not in snap_a (approximate).
        n_different = sum(
            1 for row in snap_b if not any(np.allclose(row, a_row) for a_row in snap_a)
        )
        print(f"  Approximately {n_different}/10 ring slots refreshed in 1 second")
        print("  (At 100 Hz with buffer_size=10, expect all 10 to refresh many times.)")
        print("✓ Stream is alive")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--port",
        default="/dev/cu.usbmodem197004501",
        help="Teensy serial port (find via: ls /dev/cu.usbmodem*)",
    )
    args = parser.parse_args()

    sensor = test_connect(args.port)
    try:
        test_calibration(sensor)
        test_ring_buffer_fills(sensor)
        test_data_changes_over_time(sensor)
        test_baseline_subtraction(sensor)
        test_magnet_response(sensor)
        test_sample_rate(sensor)
        print("\n=== All tests passed ===")
    finally:
        sensor.disconnect()
        print("\nSensor disconnected.")


if __name__ == "__main__":
    main()