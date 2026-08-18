// test/test_detector.cpp
// Host unit tests. Plain assert -- no framework, no dependencies.
#include "detector.h"
#include <assert.h>
#include <math.h>
#include <stdio.h>

static const float G = 980.665f;   // 1 g in gal

// Feed n quiet samples starting at t_ms, 10 ms apart. Returns next timestamp.
static uint32_t quiet(Detector* d, int n, uint32_t t_ms) {
  for (int i = 0; i < n; i++) { detector_update(d, G, t_ms); t_ms += 10; }
  return t_ms;
}

static void test_baseline_converges_to_gravity() {
  Detector d; detector_init(&d, 50.0f);
  quiet(&d, 1000, 0);
  DetectorOut o = detector_update(&d, G, 10000);
  assert(fabsf(o.dev_gal) < 0.01f);
  printf("ok baseline_converges_to_gravity\n");
}

static void test_no_event_during_warmup() {
  Detector d; detector_init(&d, 50.0f);
  uint32_t t = quiet(&d, 100, 0);           // t = 1000 ms, still inside warmup
  DetectorOut o = detector_update(&d, G + 1000.0f, t);
  assert(o.dev_gal > 900.0f);               // deviation is seen...
  assert(!o.started);                       // ...but must not trigger
  assert(!o.event_done);
  printf("ok no_event_during_warmup\n");
}

static void test_event_fires_after_refractory() {
  Detector d; detector_init(&d, 50.0f);
  uint32_t t = quiet(&d, 400, 0);           // t = 4000 ms, past warmup

  DetectorOut o = detector_update(&d, G + 1000.0f, t);
  assert(o.started);
  assert(!o.event_done);                    // not yet -- refractory is open
  assert(fabsf(o.dev_gal - 1000.0f) < 1.0f);
  t += 10;

  int events = 0; float peak = 0;
  for (int i = 0; i < 600; i++) {           // 6 s of quiet
    DetectorOut q = detector_update(&d, G, t); t += 10;
    if (q.event_done) { events++; peak = q.peak_gal; }
  }
  assert(events == 1);                      // exactly once
  assert(fabsf(peak - 1000.0f) < 1.0f);     // the true peak, not a later sample
  printf("ok event_fires_after_refractory\n");
}

static void test_below_threshold_never_triggers() {
  Detector d; detector_init(&d, 50.0f);
  uint32_t t = quiet(&d, 400, 0);
  for (int i = 0; i < 500; i++) {
    // +-10 gal oscillation: well under the 50 gal threshold
    float mag = G + ((i % 2) ? 10.0f : -10.0f);
    DetectorOut o = detector_update(&d, mag, t); t += 10;
    assert(!o.started);
    assert(!o.event_done);
  }
  printf("ok below_threshold_never_triggers\n");
}

static void test_one_event_per_refractory_window() {
  Detector d; detector_init(&d, 50.0f);
  uint32_t t = quiet(&d, 400, 0);   // t = 4000 ms
  // 25 s of sustained +-200 gal shaking. Alternating each sample keeps it
  // above the EMA's ~1 s time constant, so the baseline cannot chase it out.
  int events = 0;
  for (int i = 0; i < 2500; i++) {
    float mag = G + ((i % 2) ? 200.0f : -200.0f);
    DetectorOut o = detector_update(&d, mag, t); t += 10;
    if (o.event_done) events++;
  }
  // Events CLOSE at t = 9000, 14010, 19020, 24030 -- one per 5 s refractory,
  // each starting on the sample after the previous one closed. Four, not
  // hundreds. Note a 5th is open but unclosed when the loop ends: the count
  // is completed events, so it lags the shake duration by one window.
  assert(events == 4);
  printf("ok one_event_per_refractory_window\n");
}

static void test_duration_measures_time_above_threshold() {
  Detector d; detector_init(&d, 50.0f);
  uint32_t t = quiet(&d, 400, 0);
  for (int i = 0; i < 100; i++) {           // 1 s above threshold
    float mag = G + ((i % 2) ? 200.0f : -200.0f);
    detector_update(&d, mag, t); t += 10;
  }
  uint32_t dur = 0;
  for (int i = 0; i < 600; i++) {           // then quiet until it closes
    DetectorOut o = detector_update(&d, G, t); t += 10;
    if (o.event_done) dur = o.dur_ms;
  }
  assert(dur >= 900 && dur <= 1100);        // ~1 s, not the 5 s refractory
  printf("ok duration_measures_time_above_threshold\n");
}

int main() {
  test_baseline_converges_to_gravity();
  test_no_event_during_warmup();
  test_event_fires_after_refractory();
  test_below_threshold_never_triggers();
  test_one_event_per_refractory_window();
  test_duration_measures_time_above_threshold();
  printf("\nall detector tests passed\n");
  return 0;
}
