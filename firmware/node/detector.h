// firmware/node/detector.h
// Pure detection logic. No Arduino headers -- compiles and runs on the host.
#pragma once
#include <stdint.h>

// Tuning constants. See docs/superpowers/specs/2026-07-30-esp32-quake-node-design.md
#define EMA_ALPHA      0.01f   // single-pole high-pass; ~1 s time constant at 100 Hz
#define WARMUP_MS      3000    // suppress triggers while the baseline settles
#define REFRACTORY_MS  5000    // one event per shake, not hundreds

struct Detector {
  float    threshold_gal;
  float    baseline;        // tracks gravity (~980 gal)
  uint32_t samples;
  uint32_t t0_ms;           // timestamp of first sample
  bool     in_event;
  float    peak_gal;
  uint32_t event_start_ms;
  uint32_t last_over_ms;    // last sample still above threshold
};

struct DetectorOut {
  float    dev_gal;     // deviation from baseline, always valid
  bool     started;     // true on the one sample that opens an event
  bool     event_done;  // true on the one sample that closes an event
  float    peak_gal;    // valid when event_done
  uint32_t dur_ms;      // valid when event_done
};

void        detector_init(Detector* d, float threshold_gal);
DetectorOut detector_update(Detector* d, float mag_gal, uint32_t now_ms);
