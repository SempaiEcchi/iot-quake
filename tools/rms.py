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
print(f"threshold    {rms * 10:.2f} gal   (10x RMS)")
