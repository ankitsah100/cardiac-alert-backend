"""
Cardiac Alert Backend — Cloud Version
Deployed on Railway via GitHub
"""

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
import asyncio, json, time, math

from .analyzer import CardiacAnalyzer
from .alerts import AlertManager
from .store import DataStore

app = FastAPI(title="Cardiac Alert System", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

analyzer = CardiacAnalyzer()
alert_mgr = AlertManager()
store = DataStore()
dashboard_clients: list[WebSocket] = []

store.register_patient({
    "patient_id": "ankit_001", "name": "Ankit", "age": 26,
    "emergency_contact": "+9779800000000",
    "baseline_hr": 72.0, "baseline_hrv": 45.0
})


# ─────────────────────────────────────────────────────────────────────────────
# MODELS
# ─────────────────────────────────────────────────────────────────────────────

class WatchReading(BaseModel):
    patient_id: str
    timestamp: float
    heart_rate: float
    hrv_rmssd: Optional[float] = None
    spo2: Optional[float] = None
    ppg_signal: Optional[list[float]] = None
    rr_intervals: Optional[list[float]] = None

class RegisterPatient(BaseModel):
    patient_id: str
    name: str
    age: int
    emergency_contact: str
    baseline_hr: Optional[float] = 72.0
    baseline_hrv: Optional[float] = 45.0

class Symptoms(BaseModel):
    chest_pain: bool = False
    shortness_of_breath: bool = False
    palpitations: bool = False
    dizziness: bool = False
    fatigue: bool = False
    sweating: bool = False
    nausea: bool = False
    leg_swelling: bool = False

class MedicalHistory(BaseModel):
    diabetes: bool = False
    hypertension: bool = False
    previous_heart_attack: bool = False
    family_history: bool = False
    high_cholesterol: bool = False
    stroke: bool = False
    systolic_bp: Optional[float] = None
    diastolic_bp: Optional[float] = None
    cholesterol_level: Optional[float] = None
    fasting_blood_sugar: Optional[float] = None

class Lifestyle(BaseModel):
    smoking: bool = False
    alcohol: bool = False
    exercise_frequency: str = "none"
    stress_level: str = "low"
    diet_quality: str = "average"

class SymptomAssessmentRequest(BaseModel):
    patient_id: Optional[str] = None
    name: Optional[str] = None
    age: int
    gender: str = "male"
    weight_kg: Optional[float] = None
    height_cm: Optional[float] = None
    symptoms: Symptoms = Symptoms()
    medical_history: MedicalHistory = MedicalHistory()
    lifestyle: Lifestyle = Lifestyle()


# ─────────────────────────────────────────────────────────────────────────────
# SYMPTOM SCORING ENGINE
# ─────────────────────────────────────────────────────────────────────────────

def _calc_bmi(w, h):
    if w and h and h > 0:
        return round(w / (h / 100) ** 2, 1)
    return None

def _symptom_score(req: SymptomAssessmentRequest):
    s = 0.0
    factors = []

    def add(label, pts, sev):
        nonlocal s
        s += pts
        factors.append({"factor": label, "contribution": round(pts, 1), "severity": sev})

    age = req.age
    if age >= 75:        add("Age 75+", 18, "high")
    elif age >= 65:      add("Age 65-74", 13, "high")
    elif age >= 55:      add("Age 55-64", 8, "medium")
    elif age >= 45:      add("Age 45-54", 4, "medium")

    bmi = _calc_bmi(req.weight_kg, req.height_cm)
    if bmi:
        if bmi >= 35:    add(f"Severe obesity (BMI {bmi})", 7, "high")
        elif bmi >= 30:  add(f"Obesity (BMI {bmi})", 4, "medium")
        elif bmi >= 25:  add(f"Overweight (BMI {bmi})", 2, "low")

    sy = req.symptoms
    if sy.chest_pain:             add("Chest pain", 14, "high")
    if sy.shortness_of_breath:    add("Shortness of breath", 9, "high")
    if sy.palpitations:           add("Palpitations", 7, "medium")
    if sy.dizziness:              add("Dizziness", 6, "medium")
    if sy.fatigue:                add("Unusual fatigue", 5, "medium")
    if sy.sweating:               add("Excessive sweating", 5, "medium")
    if sy.nausea:                 add("Nausea", 3, "low")
    if sy.leg_swelling:           add("Leg edema", 6, "medium")
    if sy.chest_pain and sy.shortness_of_breath:
        add("ACS cluster (chest pain + dyspnea)", 8, "high")

    h = req.medical_history
    if h.previous_heart_attack:   add("Prior heart attack", 18, "high")
    if h.stroke:                  add("Prior stroke", 12, "high")
    if h.diabetes:                add("Diabetes", 10, "high")
    if h.hypertension:            add("Hypertension", 9, "high")
    if h.high_cholesterol:        add("High cholesterol", 7, "medium")
    if h.family_history:          add("Family history CVD", 7, "medium")

    if h.systolic_bp:
        if h.systolic_bp >= 180:    add(f"Hypertensive crisis (SBP {h.systolic_bp})", 10, "high")
        elif h.systolic_bp >= 160:  add(f"Stage 2 HTN (SBP {h.systolic_bp})", 6, "high")
        elif h.systolic_bp >= 140:  add(f"Stage 1 HTN (SBP {h.systolic_bp})", 3, "medium")
    if h.cholesterol_level:
        if h.cholesterol_level >= 240:    add(f"High cholesterol ({h.cholesterol_level})", 5, "high")
        elif h.cholesterol_level >= 200:  add(f"Borderline cholesterol ({h.cholesterol_level})", 2, "medium")
    if h.fasting_blood_sugar:
        if h.fasting_blood_sugar >= 126:  add(f"Diabetic glucose ({h.fasting_blood_sugar})", 6, "high")
        elif h.fasting_blood_sugar >= 100: add(f"Pre-diabetic glucose ({h.fasting_blood_sugar})", 3, "medium")

    lf = req.lifestyle
    if lf.smoking:                         add("Active smoking", 10, "high")
    if lf.alcohol:                         add("Alcohol use", 4, "medium")
    if lf.exercise_frequency == "none":    add("Sedentary lifestyle", 6, "medium")
    elif lf.exercise_frequency == "light": add("Low activity level", 3, "low")
    if lf.stress_level == "high":          add("High chronic stress", 5, "medium")
    elif lf.stress_level == "medium":      add("Moderate stress", 2, "low")
    if lf.diet_quality == "poor":          add("Poor diet", 4, "medium")

    score = min(round(s, 1), 100.0)
    factors.sort(key=lambda x: x["contribution"], reverse=True)
    return score, factors, bmi


def _level(score: float) -> str:
    if score < 20:  return "low"
    if score < 45:  return "medium"
    if score < 70:  return "high"
    return "critical"


# ─────────────────────────────────────────────────────────────────────────────
# WATCH SCORE NORMALIZER
# Converts watch risk_level string → 0-100 numeric score
# so we can mathematically combine it with symptom score
# ─────────────────────────────────────────────────────────────────────────────

WATCH_LEVEL_TO_SCORE = {
    "normal":   15.0,
    "low":      15.0,
    "moderate": 35.0,
    "medium":   35.0,
    "warning":  65.0,
    "high":     65.0,
    "critical": 90.0,
}

def _watch_score_from_latest(patient_id: str) -> Optional[dict]:
    """
    Fetches latest watch reading from store.
    Returns dict with numeric score, level, age_minutes, hr, spo2, hrv.
    Returns None if no recent data (older than 2 hours).
    """
    latest = store.get_latest(patient_id)
    if not latest:
        return None

    processed_at = latest.get("processed_at", 0)
    age_minutes = (time.time() - processed_at) / 60

    # Only use watch data if it's recent (within 2 hours)
    if age_minutes > 120:
        return None

    risk_level = latest.get("risk_level", "normal").lower()
    ml_confidence = latest.get("ml_confidence")

    # Use ML risk_score directly if available (0-1 scale → convert to 0-100)
    raw_score = latest.get("risk_score")
    if raw_score is not None:
        # risk_score from analyzer is already 0-1 or 0-100, normalize to 0-100
        watch_numeric = float(raw_score) * 100 if float(raw_score) <= 1 else float(raw_score)
    else:
        watch_numeric = WATCH_LEVEL_TO_SCORE.get(risk_level, 15.0)

    return {
        "score": round(watch_numeric, 1),
        "level": risk_level,
        "heart_rate": latest.get("heart_rate"),
        "spo2": latest.get("spo2"),
        "hrv_rmssd": latest.get("hrv_rmssd"),
        "ml_confidence": ml_confidence,
        "flags": latest.get("flags", []),
        "age_minutes": round(age_minutes, 1),
    }


# ─────────────────────────────────────────────────────────────────────────────
# COMBINED SCORING
# Watch (ML) = 60% weight   |   Symptom (rules) = 40% weight
# If no watch data → 100% symptom score
# ─────────────────────────────────────────────────────────────────────────────

def _combine_scores(symptom_score: float, watch_data: Optional[dict]) -> tuple:
    """
    Returns (combined_score, method, watch_contribution, symptom_contribution)
    """
    if watch_data is None:
        return symptom_score, "symptom_only", None, 100

    watch_score = watch_data["score"]

    # Weighted average: 60% watch, 40% symptom
    combined = round((watch_score * 0.60) + (symptom_score * 0.40), 1)
    combined = min(combined, 100.0)

    return combined, "combined_ml_symptom", 60, 40


RECS = {
    "low": (
        "Cardiac risk is low. Maintain a healthy lifestyle and get a check-up every 1-2 years.",
        "मुटु जोखिम कम छ। स्वस्थ जीवनशैली कायम राख्नुहोस् र हरेक १-२ वर्षमा स्वास्थ्य जाँच गर्नुहोस्।"
    ),
    "medium": (
        "Moderate cardiac risk detected. See a doctor within 2-4 weeks. Monitor blood pressure and cholesterol.",
        "मध्यम मुटु जोखिम पाइयो। २-४ हप्ताभित्र डाक्टरसँग सल्लाह लिनुहोस्। रक्तचाप र कोलेस्ट्रोल जाँच गर्नुहोस्।"
    ),
    "high": (
        "High cardiac risk detected. Consult a cardiologist within 48-72 hours. Avoid strenuous activity until evaluated.",
        "उच्च मुटु जोखिम पाइयो। ४८-७२ घण्टाभित्र हृदयरोग विशेषज्ञसँग परामर्श लिनुहोस्। मूल्यांकन नभएसम्म कठिन व्यायामबाट बच्नुहोस्।"
    ),
    "critical": (
        "CRITICAL RISK. Call 102 (Nepal Ambulance) or go to the nearest hospital emergency immediately. Do not drive yourself.",
        "अत्यन्त उच्च जोखिम। तुरुन्त १०२ (नेपाल एम्बुलेन्स) मा फोन गर्नुहोस् वा नजिकको अस्पतालको इमर्जेन्सीमा जानुहोस्। आफैं गाडी नचलाउनुहोस्।"
    ),
}


# ─────────────────────────────────────────────────────────────────────────────
# EXISTING ROUTES
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def root():
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    return f"""<html><head><title>Cardiac Alert</title>
    <style>body{{font-family:Arial,sans-serif;background:#0f172a;color:#e2e8f0;
    display:flex;justify-content:center;align-items:center;height:100vh;margin:0}}
    .card{{background:#1e293b;border-radius:16px;padding:40px;text-align:center;border:1px solid #334155}}
    .dot{{width:14px;height:14px;background:#22c55e;border-radius:50%;display:inline-block;
    margin-right:8px;animation:pulse 1.5s infinite}}
    @keyframes pulse{{0%,100%{{opacity:1}}50%{{opacity:0.3}}}}</style></head>
    <body><div class="card"><div><span class="dot"></span>
    <span style="color:#22c55e;font-weight:bold">ONLINE</span></div>
    <h1>❤️ Cardiac Alert System</h1>
    <p>Backend running — {now}</p>
    <p style="background:#166534;color:#86efac;padding:4px 12px;border-radius:20px;
    font-size:13px;display:inline-block;margin-top:12px">Ready to receive watch data</p>
    </div></body></html>"""

@app.post("/patient/register")
def register_patient(data: RegisterPatient):
    store.register_patient(data.dict())
    return {"message": f"Patient {data.patient_id} registered"}

@app.post("/reading")
async def post_reading(reading: WatchReading):
    return await process_reading(reading)

@app.post("/healthconnect")
async def health_connect_webhook(payload: dict):
    try:
        from datetime import datetime, timezone

        def latest_by_time(records, value_keys):
            if not records:
                return None
            def parse_time(r):
                t = r.get("end_time") or r.get("start_time") or ""
                try:
                    return datetime.fromisoformat(t.replace("Z", "+00:00"))
                except:
                    return datetime.min.replace(tzinfo=timezone.utc)
            records_sorted = sorted(records, key=parse_time, reverse=True)
            for r in records_sorted:
                for k in value_keys:
                    if r.get(k) is not None:
                        return r[k]
            return None

        hr = latest_by_time(payload.get("heart_rate", []), ["bpm", "beatsPerMinute", "value"])
        spo2 = latest_by_time(payload.get("oxygen_saturation", []), ["percentage", "value"])
        if spo2 and spo2 < 2:
            spo2 = spo2 * 100
        hrv = latest_by_time(payload.get("heart_rate_variability", []), ["heartRateVariabilityMillis", "value"])

        if not hr:
            return {"message": "No heart rate data found in payload", "received_keys": list(payload.keys())}

        reading = WatchReading(
            patient_id="ankit_001",
            timestamp=time.time(),
            heart_rate=float(hr),
            spo2=float(spo2) if spo2 else None,
            hrv_rmssd=float(hrv) if hrv else None,
        )
        result = await process_reading(reading)
        return result

    except Exception as e:
        return {"error": str(e), "received_keys": list(payload.keys())}

@app.get("/patient/{patient_id}/status")
def get_status(patient_id: str):
    latest = store.get_latest(patient_id)
    if not latest:
        raise HTTPException(status_code=404, detail="No data yet")
    return latest

@app.get("/patient/{patient_id}/history")
def get_history(patient_id: str, limit: int = 50):
    history = store.get_history(patient_id, limit)
    if not history:
        raise HTTPException(status_code=404, detail="Patient not found")
    return {"patient_id": patient_id, "readings": history}

@app.get("/patient/{patient_id}/summary")
def get_summary(patient_id: str):
    import time as t
    latest = store.get_latest(patient_id)
    if not latest:
        return "No data yet. Sync Life Dashboard first."
    processed_at = latest.get("processed_at", 0)
    age_minutes = (t.time() - processed_at) / 60
    if age_minutes > 120:
        h = int(age_minutes // 60)
        m = int(age_minutes % 60)
        return f"Last reading: {h}h {m}m ago. Open Life Dashboard and tap Sync Now."
    hr = latest.get("heart_rate", "?")
    spo2 = latest.get("spo2")
    risk = latest.get("risk_level", "unknown").upper()
    flags = latest.get("flags", [])
    age_str = f"{int(age_minutes)}min ago"
    if risk == "CRITICAL":   emoji = "CRITICAL ALERT"
    elif risk == "WARNING":  emoji = "WARNING"
    else:                    emoji = "NORMAL"
    msg = f"HR: {hr} bpm | {emoji} | {age_str}"
    if spo2:   msg += f" | SpO2: {spo2}%"
    if flags:  msg += " | " + ", ".join(flags).replace("_", " ")
    return msg

@app.websocket("/ws/watch/{patient_id}")
async def watch_ws(websocket: WebSocket, patient_id: str):
    await websocket.accept()
    try:
        while True:
            data = json.loads(await websocket.receive_text())
            data["patient_id"] = patient_id
            result = await process_reading(WatchReading(**data))
            await websocket.send_text(json.dumps(result))
    except WebSocketDisconnect:
        pass

@app.websocket("/ws/dashboard")
async def dashboard_ws(websocket: WebSocket):
    await websocket.accept()
    dashboard_clients.append(websocket)
    try:
        while True:
            await asyncio.sleep(30)
            await websocket.send_text(json.dumps({"type": "ping"}))
    except WebSocketDisconnect:
        if websocket in dashboard_clients:
            dashboard_clients.remove(websocket)


# ─────────────────────────────────────────────────────────────────────────────
# SYMPTOM ASSESSMENT — now with combined scoring
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/symptom-assessment")
async def symptom_assessment(req: SymptomAssessmentRequest):
    # Step 1: Calculate symptom score
    sym_score, factors, bmi = _symptom_score(req)

    # Step 2: Fetch latest watch data (if patient_id provided and data is recent)
    watch_data = None
    if req.patient_id:
        watch_data = _watch_score_from_latest(req.patient_id)

    # Step 3: Combine scores
    final_score, method, watch_weight, symptom_weight = _combine_scores(sym_score, watch_data)

    # Step 4: Determine level and recommendation
    level = _level(final_score)
    rec_en, rec_ne = RECS[level]

    # Step 5: Build response
    response = {
        "patient_id": req.patient_id,
        "assessed_at": datetime.utcnow().isoformat() + "Z",
        "risk_score": final_score,
        "risk_level": level,
        "risk_factors": factors,
        "recommendation_en": rec_en,
        "recommendation_ne": rec_ne,
        "bmi": bmi,
        "method": method,
        # Breakdown so app can show both scores
        "symptom_score": sym_score,
        "symptom_weight_pct": symptom_weight,
        "watch_data": {
            "score": watch_data["score"],
            "heart_rate": watch_data["heart_rate"],
            "spo2": watch_data["spo2"],
            "hrv_rmssd": watch_data["hrv_rmssd"],
            "flags": watch_data["flags"],
            "data_age_minutes": watch_data["age_minutes"],
            "weight_pct": watch_weight,
        } if watch_data else None,
    }
    return response


# ─────────────────────────────────────────────────────────────────────────────
# INTERNAL HELPER
# ─────────────────────────────────────────────────────────────────────────────

async def process_reading(reading: WatchReading) -> dict:
    patient = store.get_patient(reading.patient_id)
    risk = analyzer.score(reading, patient)
    result = {
        "patient_id": reading.patient_id,
        "timestamp": reading.timestamp,
        "heart_rate": reading.heart_rate,
        "hrv_rmssd": reading.hrv_rmssd,
        "spo2": reading.spo2,
        "risk_score": round(risk["score"], 3),
        "risk_level": risk["level"],
        "flags": risk["flags"],
        "method": risk.get("method", "rules"),
        "ml_prediction": risk.get("ml_prediction"),
        "ml_confidence": risk.get("ml_confidence"),
        "processed_at": time.time(),
    }
    store.save_reading(reading.patient_id, result)
    if risk["level"] in ("warning", "critical"):
        contact = patient.get("emergency_contact") if patient else None
        await alert_mgr.send(
            level=risk["level"],
            patient_id=reading.patient_id,
            patient_name=patient.get("name", "Unknown") if patient else "Unknown",
            flags=risk["flags"], hr=reading.heart_rate, contact=contact,
        )
        for ws in list(dashboard_clients):
            try: await ws.send_text(json.dumps({"type": "alert", "data": result}))
            except: dashboard_clients.remove(ws)
    return result
