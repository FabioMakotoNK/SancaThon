#pragma once

#include <algorithm>
#include <cmath>

namespace ciclorota {

class Kalman1D {
 public:
  explicit Kalman1D(float process_noise = 0.08f, float measurement_noise = 4.0f)
      : process_noise_(process_noise), measurement_noise_(measurement_noise) {}

  float reset(float measurement) {
    estimate_ = measurement;
    error_estimate_ = 1.0f;
    initialized_ = true;
    return estimate_;
  }

  float update(float measurement) {
    if (!initialized_) return reset(measurement);
    const float predicted_error = error_estimate_ + process_noise_;
    const float gain = predicted_error / (predicted_error + measurement_noise_);
    estimate_ += gain * (measurement - estimate_);
    error_estimate_ = (1.0f - gain) * predicted_error;
    return estimate_;
  }

  bool initialized() const { return initialized_; }
  float value() const { return estimate_; }

 private:
  float process_noise_;
  float measurement_noise_;
  float estimate_ = 0.0f;
  float error_estimate_ = 1.0f;
  bool initialized_ = false;
};

class MeasurementPipeline {
 public:
  bool update(float raw_cm, float& filtered_cm, bool& discontinuity_reset) {
    discontinuity_reset = false;
    if (!std::isfinite(raw_cm) || raw_cm < kMinDistanceCm || raw_cm > kMaxDistanceCm) return false;
    samples_[sample_cursor_] = raw_cm;
    sample_cursor_ = (sample_cursor_ + 1) % kMedianWindow;
    if (sample_count_ < kMedianWindow) ++sample_count_;
    const float measured = median();
    if (filter_.initialized() && std::fabs(measured - filter_.value()) > kDiscontinuityCm) {
      if (candidate_count_ == 0 ||
          std::fabs(measured - candidate_mean_) > kConfirmationToleranceCm) {
        candidate_count_ = 1;
        candidate_mean_ = measured;
        candidate_sum_ = measured;
        return false;
      }
      ++candidate_count_;
      candidate_sum_ += measured;
      candidate_mean_ = candidate_sum_ / candidate_count_;
      if (candidate_count_ < kConfirmationSamples) return false;
      filtered_cm = filter_.reset(median());
      clearCandidate();
      discontinuity_reset = true;
      return true;
    }
    clearCandidate();
    filtered_cm = filter_.update(measured);
    return true;
  }

  static float fillPercent(float distance_cm, float empty_cm, float full_cm) {
    if (!std::isfinite(distance_cm) || empty_cm <= full_cm || full_cm <= 0.0f) return -1.0f;
    float fill = 100.0f * (empty_cm - distance_cm) / (empty_cm - full_cm);
    return std::max(0.0f, std::min(100.0f, fill));
  }

  static constexpr float kMinDistanceCm = 2.0f;
  static constexpr float kMaxDistanceCm = 400.0f;

 private:
  static constexpr int kMedianWindow = 3;
  static constexpr int kConfirmationSamples = 3;
  static constexpr float kDiscontinuityCm = 30.0f;
  static constexpr float kConfirmationToleranceCm = 10.0f;

  float median() const {
    float values[kMedianWindow];
    for (int i = 0; i < sample_count_; ++i) values[i] = samples_[i];
    std::sort(values, values + sample_count_);
    if (sample_count_ % 2 == 1) return values[sample_count_ / 2];
    return (values[sample_count_ / 2 - 1] + values[sample_count_ / 2]) / 2.0f;
  }

  void clearCandidate() {
    candidate_count_ = 0;
    candidate_sum_ = 0.0f;
    candidate_mean_ = 0.0f;
  }

  float samples_[kMedianWindow] = {0.0f, 0.0f, 0.0f};
  int sample_cursor_ = 0;
  int sample_count_ = 0;
  Kalman1D filter_;
  int candidate_count_ = 0;
  float candidate_sum_ = 0.0f;
  float candidate_mean_ = 0.0f;
};

}  // namespace ciclorota
