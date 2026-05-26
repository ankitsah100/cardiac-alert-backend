"""
CardiacAnalyzer
Scores incoming watch readings for cardiac risk.
Uses rule-based thresholds + HRV analysis.
Replace score() internals with your trained ML model later.
"""

import numpy as np
from typing import Optional


class CardiacAnalyzer:

    # ── Thresholds ──────────────────────────────────────────────
    HR_TACHY       = 120    # bpm  - tachycardia
    HR_BRADY       = 45     # bpm  - bradycardia
    HR_CRITICAL_HI = 150
    HR_CRITICAL_LO = 35
    SPO2_WARNING   = 94     # %
    SPO2_CRITICAL  = 90
    HRV_LOW        = 20     # ms RMSSD - low HRV = high risk
    RR_IRREGULAR   = 0.20   # 20% coefficient of variation = irregular rhythm
    # ────────────────────────────────────────────────────────────

    def score(self, reading, patient: Optional[dict]) -> dict:
        """
        Returns:
            {
                "score": 0.0–1.0,
                "level": "normal" | "warning" | "critical",
                "flags": ["tachycardia", "low_hrv", ...]
            }
        """
        flags = []
        scores = []

        baseline_hr  = patient.get("baseline_hr", 72)  if patient else 72
        baseline_hrv = patient.get("baseline_hrv", 45) if patient else 45

        hr = reading.heart_rate

        # ── Heart rate ──────────────────────────────────────────
        if hr >= self.HR_CRITICAL_HI:
            flags.append("critical_tachycardia")
            scores.append(0.95)
        elif hr >= self.HR_TACHY:
            flags.append("tachycardia")
            scores.append(0.60)
        elif hr <= self.HR_CRITICAL_LO:
            flags.append("critical_bradycardia")
            scores.append(0.95)
        elif hr <= self.HR_BRADY:
            flags.append("bradycardia")
            scores.append(0.65)

        # Deviation from personal baseline
        hr_dev = abs(hr - baseline_hr) / baseline_hr
        if hr_dev > 0.40:
            flags.append("large_hr_deviation")
            scores.append(0.55)

        # ── SpO2 ────────────────────────────────────────────────
        if reading.spo2 is not None:
            if reading.spo2 <= self.SPO2_CRITICAL:
                flags.append("critical_spo2")
                scores.append(0.90)
            elif reading.spo2 <= self.SPO2_WARNING:
                flags.append("low_spo2")
                scores.append(0.55)

        # ── HRV ─────────────────────────────────────────────────
        if reading.hrv_rmssd is not None:
            hrv = reading.hrv_rmssd
            if hrv < self.HRV_LOW:
                flags.append("low_hrv")
                scores.append(0.65)
            # Drop relative to personal baseline
            if baseline_hrv > 0:
                hrv_drop = (baseline_hrv - hrv) / baseline_hrv
                if hrv_drop > 0.50:
                    flags.append("hrv_collapse")
                    scores.append(0.80)

        # ── RR interval irregularity ────────────────────────────
        if reading.rr_intervals and len(reading.rr_intervals) >= 5:
            rr = np.array(reading.rr_intervals)
            cv = rr.std() / rr.mean()   # coefficient of variation
            if cv > self.RR_IRREGULAR:
                flags.append("irregular_rhythm")
                scores.append(0.70 + min(cv * 0.5, 0.25))  # scale with severity

        # ── PPG signal quality check ────────────────────────────
        if reading.ppg_signal and len(reading.ppg_signal) >= 10:
            ppg = np.array(reading.ppg_signal)
            noise_ratio = self._noise_ratio(ppg)
            if noise_ratio > 0.60:
                flags.append("poor_signal_quality")
                # Don't add to risk — just a data quality warning

        # ── Final score ─────────────────────────────────────────
        if not scores:
            final_score = 0.05    # baseline resting risk
        else:
            # Max risk drives the score, blended with average
            final_score = 0.6 * max(scores) + 0.4 * np.mean(scores)
            final_score = min(final_score, 1.0)

        level = self._level(final_score, flags)

        return {"score": final_score, "level": level, "flags": flags}

    def _level(self, score: float, flags: list) -> str:
        critical_flags = {"critical_tachycardia", "critical_bradycardia",
                          "critical_spo2", "hrv_collapse"}
        if any(f in critical_flags for f in flags) or score >= 0.75:
            return "critical"
        if score >= 0.40 or flags:
            return "warning"
        return "normal"

    def _noise_ratio(self, ppg: np.ndarray) -> float:
        """Simple SNR proxy: ratio of high-freq energy to total."""
        if len(ppg) < 4:
            return 0.0
        diff2 = np.diff(np.diff(ppg))  # second derivative ~ high freq
        total_var = ppg.var()
        if total_var == 0:
            return 0.0
        return float(diff2.var() / total_var)
