import serial
import struct

<<<<<<< HEAD
PORT = "/dev/cu.usbmodem197004501"  
=======
PORT = "/dev/cu.usbmodem197004501"  # change to match your `ls` output
>>>>>>> origin/main

ser = serial.Serial(PORT, 2000000, timeout=1)

for _ in range(200):
    # Scan byte-by-byte for the 0xAA 0x55 sync header.
    while True:
        b = ser.read(1)
        if len(b) == 0:
            print("timeout waiting for data")
            ser.close()
            exit()
        if b[0] == 0xAA:
            b2 = ser.read(1)
            if len(b2) == 1 and b2[0] == 0x55:
                break

    payload = ser.read(6)
    if len(payload) != 6:
        continue
    bx, by, bz = struct.unpack("<hhh", payload)
    print(f"Bx={bx:7d}  By={by:7d}  Bz={bz:7d}")

ser.close()