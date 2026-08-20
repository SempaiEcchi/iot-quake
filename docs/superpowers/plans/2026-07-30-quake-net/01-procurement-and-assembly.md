# Plan 01: Procurement & Assembly

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> Tasks 1–2 are physical actions only a human can do. An agent should start at Task 3.

**Goal:** An assembled node whose accelerometer is confirmed responding at I2C address `0x68`.

**Architecture:** Buy parts, wire the node, install the toolchain, and prove the sensor talks before writing any real firmware.

**Tech Stack:** arduino-cli, ESP32 Arduino core, `Wire`

## Global Constraints

See [00-index.md](00-index.md#global-constraints). Relevant here:

- Board ESP32-DevKitC-32E, FQBN `esp32:esp32:esp32`
- MPU6050 at I2C `0x68`, SDA `GPIO21`, SCL `GPIO22`
- LED `GPIO26`, buzzer `GPIO25`

---

### Task 1: Buy the parts

**~¥3,100**, plus ~¥500 Akizuki shipping, plus ~¥300 if you need a USB cable.

| Buy | Qty | ~Price | Where |
|---|---|---|---|
| ESP32-DevKitC-32E (WROOM-32E, 4 MB) | 1 | ¥1,800 | [Akizuki M-15673](https://akizukidenshi.com/catalog/g/g115673/) |
| GY-521 module (MPU6050) | 1 | ~¥300 | Amazon.co.jp, any seller |
| Breadboard | 1 | ~¥300 | Silicon House / Akizuki |
| Jumper wires, male-male | 1 set | ~¥400 | Silicon House / Akizuki |
| Active buzzer module, 3-pin | 1 | ~¥100 | Silicon House / Akizuki |
| 5 mm LED | pack | ~¥100 | Silicon House / Akizuki |
| 330 Ω resistor | pack | ~¥100 | Silicon House / Akizuki |
| micro-USB cable | 1 | ~¥300 | skip if you own one |

Osaka, in person — 日本橋 / でんでんタウン:

- **シリコンハウス共立**, 浪速区日本橋5-8-26, 月–土 10:30–19:30 / 日祝 10:00–19:00, 06-6644-4446.
  Everything except possibly the dev board. **デジット** is in the same building.
- **マルツ 大阪日本橋店** or **千石電商 大阪日本橋店** — backup for the ESP32 board.
- Nearest station 恵美須町.

秋月電子 has **no Osaka store**. Its ¥1,800 is the online price; in Osaka expect ¥2,500–3,000.
Cheapest split: order the ESP32 and the GY-521 online, buy the cheap consumables in person.

- [ ] **Step 1: Check ESP32 stock before travelling**

The dev board is the one item likely to be out. Check [eleshop.jp](https://eleshop.jp/shop/default.aspx)
(Kyoritsu) and marutsu.co.jp, or just order from Akizuki online.

- [ ] **Step 2: Buy a spare GY-521 if the shop has them**

They are ~¥300 and they die from static and rough handling. A spare turns a dead sensor from a
week's delay into a two-minute swap. It also leaves the door open to the two-sensor upgrade
(AD0 → `0x69`) noted in the design's non-goals.

- [ ] **Step 3: Buy the parts**

---

### Task 2: Wire the node

**Files:**
- Create: `docs/wiring.md`

```
MPU6050 (GY-521)     ESP32-DevKitC-32E
  VCC   ───────────── 3V3        <-- 3.3 V, NOT 5V
  GND   ───────────── GND
  SCL   ───────────── GPIO22
  SDA   ───────────── GPIO21

LED anode  ────────── GPIO26  ── 330 Ω ── LED ── GND
Buzzer signal ─────── GPIO25   (VCC to 3V3, GND to GND)
```

- [ ] **Step 1: Wire with power off**

USB unplugged while wiring. The GY-521 has an onboard regulator and tolerates 5 V on VIN, but
its I2C lines are 3.3 V — powering from 3V3 keeps everything at one level and removes any
question of level shifting.

- [ ] **Step 2: Check the LED orientation**

Long leg (anode) toward GPIO26 through the resistor; short leg (cathode) to GND. Backwards
means it silently never lights, which is confusing to debug later.

- [ ] **Step 3: Photograph the node**

You need this for the report and for plan 06. Take it now while the wiring is tidy.

- [ ] **Step 4: Write the wiring doc**

Create `docs/wiring.md` with the ASCII diagram above, the photo, and one line noting the 3.3 V
choice and its reason.

- [ ] **Step 5: Commit**

```bash
git add docs/wiring.md
git commit -m "docs: node wiring"
```

---

### Task 3: Install the toolchain

**Tech:** arduino-cli. If you prefer the Arduino IDE 2.x GUI, install the same ESP32 core
through Boards Manager and the same library through Library Manager; the plans give
`arduino-cli` commands because they are exact and copy-pasteable.

- [x] **Step 1: Install arduino-cli**

```bash
brew install arduino-cli
arduino-cli version
```

- [x] **Step 2: Install the ESP32 core**

```bash
arduino-cli config init
arduino-cli config add board_manager.additional_urls \
  https://espressif.github.io/arduino-esp32/package_esp32_index.json
arduino-cli core update-index
arduino-cli core install esp32:esp32
```

- [x] **Step 3: Install PubSubClient**

```bash
arduino-cli lib install PubSubClient
```

- [x] **Step 4: Confirm the board is detected**

```bash
arduino-cli board list
```

Expected: a line with a `/dev/cu.usbserial-*` or `/dev/cu.wchusbserial*` port.

If no port appears, the board's USB-serial chip needs a driver. ESP32-DevKitC-32E uses a
Silicon Labs CP2102 — install the CP210x VCP driver from Silicon Labs, then re-check. Some
clone boards use a WCH CH340 instead and need the CH34x driver.

- [x] **Step 5: Write down the port**

You need it throughout. macOS port names can change across reboots — re-check if uploads start
failing.

**Measured on this board (2026-08-20):**

| | |
|---|---|
| Board | FREENOVE FNK0090, ESP32-WROOM-32, USB-C |
| Port | `/dev/cu.usbserial-10` |
| Chip | ESP32-D0WD-V3 rev 3.1 |
| MAC | `28:05:a5:fc:12:80` -> node ID `node-fc1280` |
| USB-serial | CP2102, no driver needed on macOS 15+ |

**Upload speed:** the default 921600 baud fails on this board with
`Unable to verify flash chip connection`. Every upload command in these plans therefore
carries `--board-options UploadSpeed=115200`. Do not drop it.

---

### Task 4: Prove the sensor responds

**Files:**
- Create: `firmware/i2c_scan/i2c_scan.ino`

A throwaway sketch with one job: confirm the wiring before any real firmware exists. If this
fails, no amount of correct algorithm will help.

- [x] **Step 1: Write the scanner**

```cpp
// firmware/i2c_scan/i2c_scan.ino
// Throwaway wiring check. Prints every I2C address that responds.
#include <Wire.h>

void setup() {
  Serial.begin(115200);
  delay(500);
  Wire.begin(21, 22);   // SDA, SCL
  Serial.println("scanning...");

  int found = 0;
  for (uint8_t addr = 1; addr < 127; addr++) {
    Wire.beginTransmission(addr);
    if (Wire.endTransmission() == 0) {
      Serial.printf("found device at 0x%02X\n", addr);
      found++;
    }
  }
  Serial.printf("done, %d device(s)\n", found);
}

void loop() {}
```

- [x] **Step 2: Compile it**

```bash
arduino-cli compile --fqbn esp32:esp32:esp32 firmware/i2c_scan
```

Expected: `Sketch uses NNNNNN bytes`, no errors.

- [ ] **Step 3: Upload and read the output**

Substitute your port from Task 3 Step 5.

```bash
arduino-cli upload -p /dev/cu.usbserial-10 --fqbn esp32:esp32:esp32 --board-options UploadSpeed=115200 firmware/i2c_scan
arduino-cli monitor -p /dev/cu.usbserial-10 -c baudrate=115200
```

Expected:

```
scanning...
found device at 0x68
done, 1 device(s)
```

`0x68` is the MPU6050. Exit the monitor with Ctrl-C.

- [ ] **Step 4: Troubleshoot if nothing is found**

`done, 0 device(s)` means wiring, not code. In order of likelihood:

| Symptom | Cause |
|---|---|
| 0 devices | SDA and SCL swapped. Most common error by far — try swapping them. |
| 0 devices | VCC not connected, or connected to a dead breadboard rail |
| 0 devices | Jumper wire broken. They fail silently; swap in a different wire. |
| Found `0x69` instead | AD0 pin pulled high. Fine — note it, and change `MPU_ADDR` in plan 02. |
| Garbage on serial | Wrong baud rate. Must be 115200. |

- [ ] **Step 5: Commit**

```bash
git add firmware/i2c_scan/i2c_scan.ino
git commit -m "test: I2C scanner to verify sensor wiring"
```

Keep this sketch. When the node misbehaves in plan 04, re-running it is the fastest way to rule
out wiring.

---

## Done when

- Node wired, photographed, `docs/wiring.md` committed
- `arduino-cli board list` shows the port, and you have written it down
- The node prints `found device at 0x68`

Next: [02-node-firmware.md](02-node-firmware.md)
