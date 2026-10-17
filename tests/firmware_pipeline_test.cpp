#include <cassert>
#include <cmath>
#include "sensor_pipeline.h"

int main() {
  ciclorota::MeasurementPipeline pipeline;
  float filtered = 0.0f;
  bool reset = false;
  assert(!pipeline.update(0.0f, filtered, reset));
  assert(pipeline.update(100.0f, filtered, reset));
  assert(std::fabs(filtered - 100.0f) < 0.01f);

  // A single distant echo is rejected after the median window settles.
  assert(pipeline.update(101.0f, filtered, reset));
  const float stable = filtered;
  assert(pipeline.update(300.0f, filtered, reset));
  assert(std::fabs(filtered - stable) < 2.0f);

  // Sustained emptying step is confirmed and resets the estimate.
  bool accepted = false;
  bool reset_seen = false;
  for (int i = 0; i < 6; ++i) {
    accepted = pipeline.update(145.0f, filtered, reset) || accepted;
    reset_seen = reset_seen || reset;
  }
  assert(accepted);
  assert(reset_seen);
  assert(std::fabs(filtered - 145.0f) < 0.01f);

  const float half = ciclorota::MeasurementPipeline::fillPercent(87.5f, 150.0f, 25.0f);
  assert(std::fabs(half - 50.0f) < 0.01f);
  assert(ciclorota::MeasurementPipeline::fillPercent(10.0f, 150.0f, 25.0f) == 100.0f);
  return 0;
}
