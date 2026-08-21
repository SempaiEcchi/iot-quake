"""Read dev_gal values on stdin, print RMS and a suggested threshold."""
import math
import sys

vals = []
for line in sys.stdin:
    line = line.strip()
    try:
        vals.append(float(line))
    except ValueError:
        continue        # header, boot noise, serial garbage

if len(vals) < 100:
    sys.exit(f"only {len(vals)} samples parsed - capture longer")

# Discard the first 3 s: the EMA is still settling and would inflate the RMS.
vals = vals[300:]

rms = math.sqrt(sum(v * v for v in vals) / len(vals))
print(f"samples      {len(vals)}")
print(f"seconds      {len(vals) / 100:.1f}")
print(f"RMS          {rms:.3f} gal")
print(f"peak         {max(vals):.3f} gal")
print()
print("multiplier   threshold      lowest shindo   false triggers")
for mult, reach, rate in ((10, "3, high end", "rare"),
                          (5,  "3",           "~1 per two days"),
                          (3,  "3, low end",  "several per hour")):
    mark = "  <- recommended" if mult == 5 else ""
    print(f"  {mult:>2}x        {rms * mult:>6.2f} gal    {reach:<14} {rate}{mark}")
print()
print("5x is the spec's recommendation when the goal is shindo 3. Use 10x if")
print("this floor turns out to be building-dominated rather than sensor-dominated,")
print("which shows up as an RMS far above the ~0.9 gal the MPU6050 predicts.")
