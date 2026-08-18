// firmware/node/detector.cpp
#include "detector.h"
#include <math.h>

void detector_init(Detector* d, float threshold_gal) {
  d->threshold_gal  = threshold_gal;
  d->baseline       = 0.0f;
  d->samples        = 0;
  d->t0_ms          = 0;
  d->in_event       = false;
  d->peak_gal       = 0.0f;
  d->event_start_ms = 0;
  d->last_over_ms   = 0;
}

DetectorOut detector_update(Detector* d, float mag_gal, uint32_t now_ms) {
  DetectorOut out = {0.0f, false, false, 0.0f, 0};

  if (d->samples == 0) {
    // Seed the baseline to the first sample instead of 0. Without this the
    // first deviation is ~980 gal and the filter spends a second settling.
    d->baseline = mag_gal;
    d->t0_ms    = now_ms;
    d->samples  = 1;
    return out;                        // dev is meaningless for sample one
  }

  // Deviation against the PREVIOUS baseline, then update. This order lets a
  // single spike report its full amplitude rather than one diluted by itself.
  out.dev_gal = fabsf(mag_gal - d->baseline);
  d->baseline = (1.0f - EMA_ALPHA) * d->baseline + EMA_ALPHA * mag_gal;
  d->samples++;

  if (now_ms - d->t0_ms < WARMUP_MS) return out;   // still settling

  if (d->in_event) {
    if (out.dev_gal > d->peak_gal)       d->peak_gal     = out.dev_gal;
    if (out.dev_gal > d->threshold_gal)  d->last_over_ms = now_ms;

    if (now_ms - d->event_start_ms >= REFRACTORY_MS) {
      out.event_done = true;
      out.peak_gal   = d->peak_gal;
      out.dur_ms     = d->last_over_ms - d->event_start_ms;
      d->in_event    = false;
      d->peak_gal    = 0.0f;
    }
  } else if (out.dev_gal > d->threshold_gal) {
    out.started       = true;
    d->in_event       = true;
    d->event_start_ms = now_ms;
    d->last_over_ms   = now_ms;
    d->peak_gal       = out.dev_gal;
  }

  return out;
}
