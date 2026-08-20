# Wiring

Node: FREENOVE FNK0090 (ESP32-WROOM-32) + GY-521 (MPU6050), on one breadboard.

## FNK0090 pinout (verified from the board)

Front view, USB-C at the bottom. **40 pins, not 38** — 20 per side, so it occupies
20 breadboard columns.

| # | LEFT header | | # | RIGHT header |
|---|---|---|---|---|
| 1 | `3V3` | | 1 | `GND` |
| 2 | `RST` | | 2 | `GPIO23` |
| 3 | `GPIO36` | | 3 | **`GPIO22`** I2C_SCL |
| 4 | `GPIO39` | | 4 | `GPIO1` U0TXD |
| 5 | `GPIO34` | | 5 | `GPIO3` U0RXD |
| 6 | `GPIO35` | | 6 | **`GPIO21`** I2C_SDA |
| 7 | `GPIO32` | | 7 | `GND` |
| 8 | `GPIO33` | | 8 | `GPIO19` |
| 9 | **`GPIO25`** buzzer | | 9 | `GPIO18` |
| 10 | `GPIO26` | | 10 | `GPIO5` |
| 11 | `GPIO27` | | 11 | `GPIO17` |
| 12 | `GPIO14` | | 12 | `GPIO16` |
| 13 | `GPIO12` | | 13 | `GPIO4` |
| 14 | **`GND`** | | 14 | `GPIO0` |
| 15 | `GPIO13` | | 15 | **`GPIO2`** LED_IO2, onboard LED |
| 16 | `3V3` | | 16 | `GPIO15` |
| 17 | `3V3` | | 17 | `GND` |
| 18 | `3V3` | | 18 | `GND` |
| 19 | `5V` | | 19 | `GND` |
| 20 | `5V` | | 20 | `GND` |

Three spare `3V3` pins on the left and four spare `GND` on the right mean this build
needs **no power rails** — every load gets its own pin.

## Breadboard placement (two half-size boards, side by side)

Two 400-point boards joined along the long edge, facing rails removed. Letters read
`A`-`J` on board 1 then `A'`-`J'` on board 2; numbers 1-30 run down both.

- ESP32 left header in board 1 **`J`**, numbers 1-20
- ESP32 right header in board 2 **`F'`**, numbers 1-20

Free holes after seating:

| Area | Use |
|---|---|
| board 1 `F` `G` `H` `I` | reach any left-side ESP32 pin |
| board 2 `G'` `H'` `I'` `J'` | reach any right-side ESP32 pin |
| board 1 `A`-`E`, numbers 21-30 | GY-521 sits here |
| board 2 `G'`-`J'`, numbers 21-30 | buzzer sits here |
| board 2 `A'`-`E'` | under the ESP32 body, unusable |

Wire into the **same number, a different letter on the same side of the channel**.
`9J` is reached from `9I`; `9H` and `10J` reach nothing.

### Wire list

GY-521 pins in board 1 `A`, numbers 22-29 (`VCC GND SCL SDA XDA XCL AD0 INT`).
Buzzer in board 2 `J'`, numbers 22-24.

| # | From (ESP32 pin) | Hole | To | Hole |
|---|---|---|---|---|
| 1 | `3V3` left 1 | `1I` b1 | GY-521 `VCC` | `22B` b1 |
| 2 | `GND` left 14 | `14I` b1 | GY-521 `GND` | `23B` b1 |
| 3 | `GPIO22` right 3 | `3G'` b2 | GY-521 `SCL` | `24B` b1 |
| 4 | `GPIO21` right 6 | `6G'` b2 | GY-521 `SDA` | `25B` b1 |
| 5 | `GPIO25` left 9 | `9I` b1 | buzzer `IO` | b2 `J'` |
| 6 | `3V3` left 16 | `16I` b1 | buzzer `VCC` | b2 `J'` |
| 7 | `GND` right 17 | `17G'` b2 | buzzer `GND` | b2 `J'` |

Two dovetailed boards flex at the seam. For the long unattended run tape **both**
boards down - a rocking seam is movement in the 0.2-5 Hz band, exactly what the
detector looks for.

## Connections

Six jumpers. No LED and no resistor — the FNK0090 has an onboard LED on **GPIO2**,
which the firmware uses instead of a discrete one.

| # | From | To | Why |
|---|---|---|---|
| 1 | ESP32 `3V3` | red (+) rail | Power the rail |
| 2 | ESP32 `GND` | blue (−) rail | Common ground |
| 3 | red (+) rail | GY-521 `VCC` | 3.3 V, **not 5 V** |
| 4 | blue (−) rail | GY-521 `GND` | |
| 5 | ESP32 `GPIO21` | GY-521 `SDA` | I2C data |
| 6 | ESP32 `GPIO22` | GY-521 `SCL` | I2C clock |

Buzzer (3-pin active module), three more:

| # | From | To |
|---|---|---|
| 7 | ESP32 `GPIO25` | buzzer `I/O` (or `S`) |
| 8 | red (+) rail | buzzer `VCC` |
| 9 | blue (−) rail | buzzer `GND` |

### If your buzzer is a bare 2-wire piezo

A 2-wire buzzer (e.g. LIKENNY "DC 3-24 V continuous") has no transistor. Two problems:
GPIO25 must source the full current (ESP32 limit ~20 mA recommended, 40 mA absolute),
and at 3.3 V a buzzer rated 85 dB at 24 V will be quiet.

Drive it through an NPN transistor instead:

```
GPIO25 ──[1 kΩ]── base (2N2222 / S8050)
                  collector ── buzzer (−)
                  emitter   ── GND
buzzer (+) ─────────────────── 5 V (ESP32 VIN pin)
```

No firmware change: GPIO25 HIGH still sounds it. Costs ~¥50 and gives full volume
with zero risk to the pin. A 3-pin active module has this transistor built in — if
you have one, use the three-wire table above and skip this.

Leave `XDA`, `XCL`, `AD0`, `INT` on the GY-521 unconnected. `AD0` floating/low gives
I2C address `0x68`, which is what `MPU_ADDR` in `firmware/node/node.ino` expects.

## Breadboard layout

830-point board. Columns are indicative — shift to suit your board's length.

```
      +  ─────────────────────────────────────────────────  red rail (3.3 V)
      -  ─────────────────────────────────────────────────  blue rail (GND)

                                            VCC GND SCL SDA
                                             │   │   │   │
                                             v   v   v   v
          1    5    10   15   20        25   26  27  28  29  30
      A   .    .    .    .    .    │    .    o   o   o   o   .
      B   [========= ESP32 pins =========]   V   G   S   S  X X A I
      C   [                             ]    o   o   o   o   .
      D   [        ESP32 body           ]    o   o   o   o   .
      E   [                             ]    o   o   o   o   .
     ═══  ═══════════════ channel ═════════════════════════════
      F   [                             ]    .   .   .   .   .
      G   [                             ]    .   .   .   .   .
      H   [                             ]    .   .   .   .   .
      I   [========= ESP32 pins =========]   .   .   .   .   .
      J   .    .    .    .    .    │    .    .   .   .   .   .

              o = usable hole for that signal
```

**Read the column, not the row.** A breadboard column is connected A–B–C–D–E as one
node, and F–G–H–I–J as a separate node, with the channel between them. The GY-521
pins sit in row **B**, so every jumper to them goes into row **A, C, D or E of the
same column** — whichever the module body is not covering. Rows F–J of those columns
are a different node entirely: wire there and nothing connects, and the scanner
reports `0 device(s)` while the wiring looks perfect.

Same rule for the ESP32: its pins are in rows B and I, and its body physically covers
C–H, so its only reachable holes are row **A** (for the row-B pins) and row **J** (for
the row-I pins).

The GY-521 has a single 8-pin header, so its body overhangs to one side. Seat it so the
body hangs *away* from the holes you plan to use. Its pin order on most boards is
`VCC GND SCL SDA XDA XCL AD0 INT` — **read the silkscreen, clones differ.**

## The one-free-hole problem

A 38-pin ESP32 board is ~25.4 mm across its two headers. A breadboard is 27.9 mm
from row A to row J. So the pins land in rows **B and I**, and because holes
A–E share a column and F–J share a column, each ESP32 pin leaves exactly **one**
free hole: row A on one side, row J on the other.

That is enough for this build — six wires. But it means every jumper to the ESP32
goes into row A or row J, directly beside the pin you want.

If your board is the wider 27.9 mm variant, the pins land in A and J and there are
**zero** free holes. Then either straddle two breadboards pushed together, or use
female-to-male jumpers off the ESP32 headers with the ESP32 off the breadboard.
Male-to-male jumpers will not reach ESP32 header pins on their own.

## Why 3.3 V, not 5 V

The GY-521 has an onboard regulator and tolerates 5 V on VCC, but its I2C lines
are 3.3 V logic. Powering from `3V3` keeps the whole bus at one level and removes
any question of level shifting.

## Orientation does not matter

`mpu_read_mag()` in `node.ino` takes the magnitude of all three axes
(`sqrtf(gx*gx + gy*gy + gz*gz)`), so the sensor can face any direction. The EMA
high-pass removes the 980 gal of gravity wherever it happens to land.

## Mounting

For real earthquake capture, the *breadboard-to-floor* coupling is what matters,
not the sensor-to-breadboard coupling. The module on breadboard springs resonates
far above the 0.2–5 Hz band of interest, so it tracks the board faithfully.

- Tape the breadboard to a **hard floor**, ground floor if possible. Not carpet —
  carpet is a spring soft enough to land in-band.
- Tape the USB cable down a few cm from the board. Cable tug is in-band.
- Loose breadboard contacts show up as occasional huge outliers, not as a raised
  noise floor. Plan 04's calibration run will tell you which you have.

## Verify before firmware

```bash
arduino-cli upload -p /dev/cu.usbserial-10 --fqbn esp32:esp32:esp32 \
  --board-options UploadSpeed=115200 firmware/i2c_scan
arduino-cli monitor -p /dev/cu.usbserial-10 -c baudrate=115200
```

Expected:

```
scanning...
found device at 0x68
done, 1 device(s)
```

`0 device(s)` is wiring, not code — see the troubleshooting table in
[plan 01](superpowers/plans/2026-07-30-quake-net/01-procurement-and-assembly.md).
