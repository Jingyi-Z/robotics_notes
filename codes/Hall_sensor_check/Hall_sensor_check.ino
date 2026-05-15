// MLX90393 → Teensy 4.1 → Mac serial bridge at 100 Hz
// Wire format per frame (8 bytes):
//   [0xAA] [0x55] [Bx_lo Bx_hi] [By_lo By_hi] [Bz_lo Bz_hi]
// Each axis is a signed 16-bit integer, little-endian.

#include <Wire.h>
#include <Adafruit_MLX90393.h>

Adafruit_MLX90393 sensor = Adafruit_MLX90393();

// We want one reading every 10 ms (100 Hz).
const unsigned long SAMPLE_INTERVAL_US = 10000;  // microseconds
unsigned long next_sample_us = 0; //Alarm clock for the next sample

void setup() {
  // Open the USB serial link. The baud rate here is largely cosmetic for
  // Teensy native USB — it always runs at full USB speed regardless — but the
  // Mac side needs the same number, so we pick 2,000,000 to match the
  // existing FlexiTac convention in the lerobot_tactile repo.
  Serial.begin(2000000);

  // Start the I2C bus and the MLX driver.
  if (!sensor.begin_I2C()) {
    // If the chip isn't responding, blink the onboard LED forever so we know.
    pinMode(LED_BUILTIN, OUTPUT);
    while (1) {
      digitalWrite(LED_BUILTIN, HIGH); delay(200);
      digitalWrite(LED_BUILTIN, LOW);  delay(200);
    }
  }

  // Configure the chip. Lower oversampling → faster readings.
  sensor.setGain(MLX90393_GAIN_5X); // Amplifier gain (1x to 5x). Higher gain, higher sensitivity.
  sensor.setResolution(MLX90393_X, MLX90393_RES_16); //resolution (RES_16 most precise to RES_19 widest range)
  sensor.setResolution(MLX90393_Y, MLX90393_RES_16);
  sensor.setResolution(MLX90393_Z, MLX90393_RES_16);
  sensor.setOversampling(MLX90393_OSR_2); //Average internal samples to produce one reading, to reduce random noise. OSR_0 (1 sample) to OSR_3 (8 samples).
  sensor.setFilter(MLX90393_FILTER_2); // Digital low-pass filter, to reduce high-freq noise. FILTER_0 to FILTER_7. More aggressive filter can cause longer latency and read time.

  next_sample_us = micros();
}

void loop() {
  // Wait until it's time for the next sample. micros() returns the number of
  // microseconds since the Teensy booted. This loop pattern gives us a steady
  // 100 Hz cadence regardless of how long each read takes (as long as the read
  // takes < 10 ms, which it does).
  unsigned long now_us = micros();
  if ((long)(now_us - next_sample_us) < 0) return;
  next_sample_us += SAMPLE_INTERVAL_US;

  // Read the chip. readData() returns Bx/By/Bz as floats (in microtesla), but
  // we want the raw 16-bit values for compactness. The Adafruit lib doesn't
  // expose raw directly in a clean way, so we use the float reading and scale
  // back. For a 16-bit resolution at gain 2.5x, the LSB is ~0.150 uT, so
  // multiplying by ~6.67 gives the raw int16-equivalent. (We'll just pack the
  // float-derived value as int16 directly — close enough for tactile use.)
  float x_ut, y_ut, z_ut;
  if (!sensor.readData(&x_ut, &y_ut, &z_ut)) {
    return;  // Skip this sample on read failure.
  }

  // Convert microtesla → int16 counts. The conversion factor isn't critical;
  // we just need consistent units. We clip to int16 range to be safe.
  auto to_i16 = [](float v) -> int16_t {
    float scaled = v * 10.0f;  // expand so small fields show up
    if (scaled >  32767.0f) scaled =  32767.0f;
    if (scaled < -32768.0f) scaled = -32768.0f;
    return (int16_t)scaled;
  };
  int16_t bx = to_i16(x_ut);
  int16_t by = to_i16(y_ut);
  int16_t bz = to_i16(z_ut);

  // Pack the frame and send it.
  uint8_t frame[8];
  frame[0] = 0xAA;
  frame[1] = 0x55;
  frame[2] = (uint8_t)(bx & 0xFF);          // low byte
  frame[3] = (uint8_t)((bx >> 8) & 0xFF);   // high byte
  frame[4] = (uint8_t)(by & 0xFF);
  frame[5] = (uint8_t)((by >> 8) & 0xFF);
  frame[6] = (uint8_t)(bz & 0xFF);
  frame[7] = (uint8_t)((bz >> 8) & 0xFF);
  Serial.write(frame, 8);
}