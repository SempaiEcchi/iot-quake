# Plan 06: Public Release

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> Task 1 is a blocking security gate. Task 6 pushes to the public internet and **must not run without explicit human confirmation** — an agent should stop and ask.

**Goal:** A public GitHub repository that another student could rebuild from, with no leaked credentials.

**Architecture:** Audit for secrets first, then write the things a stranger needs (license, results, credits), then publish once.

**Tech Stack:** git, `gh` CLI

## Before you start

Two things to settle that have nothing to do with code:

- **Check your course's policy on publishing coursework.** Some programmes treat a public
  repo before grading as an academic integrity problem, because it lets others copy your
  submission. If in doubt, ask your instructor, or publish after grades are returned.
- **Publishing is effectively permanent.** GitHub repos get cloned, forked, and indexed within
  minutes. Deleting the repo later does not retract what was copied. Treat this as one-way.

---

### Task 1: Secret audit — blocking gate

Do this before anything else. If a WiFi password reached git history, the fix is rewriting
history *and* changing the password. After pushing, rewriting history does not help — assume
anything pushed is permanently public.

- [ ] **Step 1: Confirm config.h was never committed**

```bash
git log --all --full-history --oneline -- firmware/node/config.h
```

Expected: **no output.** Any output means the file is in history — go to Step 4.

- [ ] **Step 2: Search all history for your actual password**

Substitute your real hotspot password.

```bash
git grep -I --all-match -n 'your-real-password' $(git rev-list --all) 2>/dev/null | head
```

Expected: no output. Also check the SSID:

```bash
git grep -I -n 'your-real-ssid' $(git rev-list --all) 2>/dev/null | head
```

- [ ] **Step 3: Confirm nothing sensitive is staged or untracked-but-about-to-be-added**

```bash
git status --short
git ls-files | grep -i config
```

Expected from the second command: only `firmware/node/config.h.example`. If plain `config.h`
appears, it is tracked — stop and go to Step 4.

- [ ] **Step 4: If a secret is in history, remove it before continuing**

Nothing has been pushed yet, so this is still cheap.

```bash
git rm --cached firmware/node/config.h
git commit -m "chore: untrack config.h"
```

That stops future commits but leaves the old ones. To purge history, easiest option with only
local commits:

```bash
# Verify the ignore rule is right first
git check-ignore -v firmware/node/config.h    # expect a .gitignore match

# Then squash history into one clean commit
git checkout --orphan clean-main
git add -A
git commit -m "init: two-node networked earthquake detector"
git branch -D main
git branch -m main
```

Re-run Steps 1–3. Both must come back empty. **Change your hotspot password anyway** — it is
free and removes all doubt.

- [ ] **Step 5: Confirm the gate passed**

Write down that Steps 1–3 returned nothing. Do not proceed otherwise.

---

### Task 2: License

**Files:**
- Create: `LICENSE`

- [ ] **Step 1: Write an MIT license**

```
MIT License

Copyright (c) 2026 <YOUR NAME>

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

Replace `<YOUR NAME>`.

- [ ] **Step 2: Commit**

```bash
git add LICENSE
git commit -m "chore: MIT license"
```

---

### Task 3: Media

**Files:**
- Create: `docs/media/nodes.jpg`
- Create: `docs/media/demo.gif` (optional)

- [ ] **Step 1: Add the wiring photo from plan 01**

Both nodes, wiring visible. Resize to about 1600 px wide so the repo stays small.

```bash
mkdir -p docs/media
# then copy your photo in as docs/media/nodes.jpg
```

- [ ] **Step 2: Record the demo, if you can**

A short clip of the two-node contrast — tap one node, nothing; shake the table, buzzer. This
one clip communicates the project better than any paragraph.

- [ ] **Step 3: Commit**

```bash
git add docs/media
git commit -m "docs: hardware photo and demo clip"
```

---

### Task 4: Finish the README

**Files:**
- Modify: `README.md`

The README already covers parts, wiring, running, and topics. It needs the measured results,
the media, and credits.

- [ ] **Step 1: Add the photo near the top**

Right after the opening description:

```markdown
![Two nodes on breadboards](docs/media/nodes.jpg)
```

- [ ] **Step 2: Add a Results section with your real numbers**

Copy the actual figures from `docs/RESULTS.md` — a reader should not have to open another
file to learn whether this worked.

```markdown
## Results

| Measurement | Value |
|---|---|
| Noise floor, node-01 | 0.00 gal RMS |
| Noise floor, node-02 | 0.00 gal RMS |
| Threshold | 0.00 gal |
| Lowest detectable shindo | 0 |
| Single-node events rejected in 1 h of normal activity | 0 |
| Real earthquakes captured | 0 |

Full detail: [docs/RESULTS.md](docs/RESULTS.md) · [docs/TESTLOG.md](docs/TESTLOG.md)
```

The rejection count is the headline. It is the measured value of using two nodes instead of
one.

- [ ] **Step 3: Add a Credits section**

Attribution matters here twice over: it is normal open-source courtesy, and for coursework
undocumented borrowing is an academic integrity problem. Be explicit about what you took.

```markdown
## Credits

Prior art this project drew on:

- [coniferconifer/ESP32-seismometer](https://github.com/coniferconifer/ESP32-seismometer) —
  JMA-based intensity approach and the gravity-offset filtering idea
- [GeoShake: DIY seismology and PGA](https://geoshake.org/blog/diy-seismology-pga-geoshake) —
  multi-sensor noise rejection, which this project reduces to two nodes
- [Qiita: 地震観測を目的とした加速度センサ5種の性能比較](https://qiita.com/compo031/items/e62d0a0e1425c5e1efe8) —
  accelerometer noise-floor comparison that informed the sensor choice
- [OCW Bucharest earthquake detection project](https://ocw.cs.pub.ro/courses/iothings/proiecte/2021/earthquakedetection) —
  ESP32 + MPU6050 baseline

This project's own contribution is the two-node correlation rule and the measured
false-positive rejection rate.
```

- [ ] **Step 4: Add a Build-it-yourself pointer**

```markdown
## Building this yourself

Step-by-step plans, from buying parts to publishing:
[docs/superpowers/plans/2026-07-30-quake-net/](docs/superpowers/plans/2026-07-30-quake-net/00-index.md)

Copy `firmware/node/config.h.example` to `config.h` and fill in your WiFi and broker IP.
`config.h` is gitignored — do not commit yours.
```

- [ ] **Step 5: Verify every link resolves**

```bash
grep -o '(\(docs\|firmware\|correlator\)[^)]*)' README.md | tr -d '()' | while read -r f; do
  [ -e "${f%%#*}" ] && echo "ok   $f" || echo "MISS $f"
done
```

Expected: every line `ok`. Fix any `MISS`.

- [ ] **Step 6: Commit**

```bash
git add README.md
git commit -m "docs: results, media, and credits in README"
```

---

### Task 5: Reproducibility check

Prove a stranger can build this. The most common failure is a file you have locally but never
committed.

- [ ] **Step 1: Clone into a temp directory and build from scratch**

```bash
cd /tmp && rm -rf quake-check
git clone /Users/leo/projects/iot quake-check
cd quake-check
```

- [ ] **Step 2: Confirm the host tests pass in the clone**

```bash
cd test && make run
```

Expected: `all detector tests passed`

- [ ] **Step 3: Confirm the correlator tests pass in the clone**

```bash
cd ../correlator && python -m pytest test_core.py -v
```

Expected: `8 passed`

- [ ] **Step 4: Confirm the sketch compiles after copying the template config**

```bash
cp firmware/node/config.h.example firmware/node/config.h
arduino-cli compile --fqbn esp32:esp32:esp32 firmware/node
```

Expected: compiles. This proves `config.h.example` has every macro the sketch needs — the
single most likely thing to be broken for a stranger.

- [ ] **Step 5: Confirm no secret is in the clone**

```bash
grep -rIn 'your-real-password' . 2>/dev/null | head
```

Expected: no output. This is a second, independent check on Task 1.

- [ ] **Step 6: Clean up**

```bash
cd /tmp && rm -rf quake-check
```

- [ ] **Step 7: Fix and commit anything the clone revealed**

---

### Task 6: Publish — requires human confirmation

**STOP.** This step is public and effectively irreversible. Confirm before running it:

- Task 1's secret audit came back empty
- Task 5's clone built cleanly
- Your course permits publishing coursework now
- Your name in `LICENSE` is correct

- [ ] **Step 1: Authenticate gh**

```bash
gh auth status || gh auth login
```

- [ ] **Step 2: Final pre-flight check on what will be published**

```bash
git ls-files | grep -i -E 'config\.h$|\.env|secret|password' || echo "clean"
```

Expected: `clean`.

- [ ] **Step 3: Create the repository and push**

```bash
gh repo create quake-net --public --source=. --remote=origin \
  --description "Two ESP32 nodes detect an earthquake only when both agree - correlation rejects local noise" \
  --push
```

- [ ] **Step 4: Add topics so it is findable**

```bash
gh repo edit --add-topic esp32,mpu6050,earthquake,seismometer,mqtt,iot,sensor-network
```

- [ ] **Step 5: Verify what actually landed**

```bash
gh repo view --web
```

Check on the live page: README renders, the photo displays, `config.h` is **absent**, and
`config.h.example` is present.

- [ ] **Step 6: If a secret did leak, act immediately**

Do not try to quietly rewrite history — assume it is already cloned and indexed.

1. Change your WiFi password now. That is the only step that actually protects you.
2. `gh repo delete quake-net` to limit further spread.
3. Fix the history locally, re-run Task 1, then republish.

---

## Done when

- Public repo exists, README renders with the photo and real result numbers
- `config.h` is absent from the repo; `config.h.example` is present
- A fresh clone passes both test suites and compiles the sketch
- Credits attribute all four reference projects

## Project complete

Working system, measured results, tests, and a public repo. For the report, the strongest
material is in `docs/RESULTS.md`: the measured noise floor, the lowest detectable shindo, and
the count of single-node events that correlation rejected. That last number is the
quantitative case for the whole architecture.
