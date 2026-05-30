"""
CardiacAnalyzer — ML + Rule based hybrid
Uses trained Random Forest model when ECG data available,
falls back to rule-based scoring for simple HR/SpO2 readings
from smartwatches like Glory Fit.
"""

import numpy as np
import os
import joblib
from typing import Optional


class CardiacAnalyzer:

    # ── Rule-based thresholds (fallback for watch data) ──────────
    HR_TACHY       = 120
    HR_BRADY       = 45
    HR_CRITICAL_HI = 150
    HR_CRITICAL_LO = 35
    SPO2_WARNING   = 94
    SPO2_CRITICAL  = 90
    HRV_LOW        = 20
    RR_IRREGULAR   = 0.20
    # ─────────────────────────────────────────────────────────────

    def __init__(self):
        self._ml_model = None
        self._load_model()

    def _load_model(self):
        """Try to load trained ML model if available."""
        model_path = os.path.join(os.path.dirname(__file__), '..', 'cardiac_model.pkl')
        model_path = os.path.abspath(model_path)
        if os.path.exists(model_path):
            try:
                self._ml_model = joblib.load(model_path)
                print(f"[Analyzer] ML model loaded from {model_path}")
            except Exception as e:
                print(f"[Analyzer] Could not load ML model: {e}")
        else:
            print(f"[Analyzer] No ML model found — using rule-based scoring")

    def score(self, reading, patient: Optional[dict]) -> dict:
        """
        Score a reading using ML model if ECG data available,
        otherwise use rule-based thresholds for watch HR/SpO2 data.
        """
        # Use ML model if raw ECG signal provided
        if reading.ppg_signal and len(reading.ppg_signal) >= 100 and self._ml_model:
            return self._ml_score(reading)

        # Otherwise use rule-based scoring
        return self._rule_score(reading, patient)

    def _ml_score(self, reading) -> dict:
        """ML-based scoring using trained ECG model."""
        features = np.array(reading.ppg_signal[:180]).reshape(1, -1)
        prediction = self._ml_model.predict(features)[0]
        probabilities = self._ml_model.predict_proba(features)[0]
        classes = self._ml_model.classes_

        prob_dict = dict(zip(classes, probabilities))
        
        # Map ECG labels to risk levels
        label_map = {
            'N': ('normal', 0.05),
            'A': ('warning', 0.60),
            'V': ('critical', 0.90),
        }
        level, base_score = label_map.get(prediction, ('warning', 0.50))
        
        # Confidence-weighted score
        confidence = prob_dict.get(prediction, 0.5)
        score = base_score * confidence

        flags = []
        if prediction == 'A':
            flags.append('atrial_premature_beat')
        elif prediction == 'V':
            flags.append('ventricular_premature_beat')

        return {
            "score": round(score, 3),
            "level": level,
            "flags": flags,
            "method": "ml_model",
            "ml_prediction": prediction,
            "ml_confidence": round(confidence * 100, 1)
        }

    def _rule_score(self, reading, patient: Optional[dict]) -> dict:
        """Rule-based scoring for smartwatch HR/SpO2 data."""
        flags = []
        scores = []

        baseline_hr  = patient.get("baseline_hr", 72)  if patient else 72
        baseline_hrv = patient.get("baseline_hrv", 45) if patient else 45

        hr = reading.heart_rate

        # Heart rate
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

        hr_dev = abs(hr - baseline_hr) / baseline_hr
        if hr_dev > 0.40:
            flags.append("large_hr_deviation")
            scores.append(0.55)

        # SpO2
        if reading.spo2 is not None:
            if reading.spo2 <= self.SPO2_CRITICAL:
                flags.append("critical_spo2")
                scores.append(0.90)
            elif reading.spo2 <= self.SPO2_WARNING:
                flags.append("low_spo2")
                scores.append(0.55)

        # HRV
        if reading.hrv_rmssd is not None:
            hrv = reading.hrv_rmssd
            if hrv < self.HRV_LOW:
                flags.append("low_hrv")
                scores.append(0.65)
            if baseline_hrv > 0:
                hrv_drop = (baseline_hrv - hrv) / baseline_hrv
                if hrv_drop > 0.50:
                    flags.append("hrv_collapse")
                    scores.append(0.80)

        # RR intervals
        if reading.rr_intervals and len(reading.rr_intervals) >= 5:
            rr = np.array(reading.rr_intervals)
            cv = rr.std() / rr.mean()
            if cv > self.RR_IRREGULAR:
                flags.append("irregular_rhythm")
                scores.append(0.70 + min(cv * 0.5, 0.25))

        if not scores:
            final_score = 0.05
        else:
            final_score = 0.6 * max(scores) + 0.4 * np.mean(scores)
            final_score = min(final_score, 1.0)

        level = self._level(final_score, flags)
        return {
            "score": round(final_score, 3),
            "level": level,
            "flags": flags,
            "method": "rules"
        }

    def _level(self, score: float, flags: list) -> str:
        critical_flags = {"critical_tachycardia", "critical_bradycardia",
                          "critical_spo2", "hrv_collapse"}
        if any(f in critical_flags for f in flags) or score >= 0.75:
            return "critical"
        if score >= 0.40 or flags:
            return "warning"
        return "normal"
