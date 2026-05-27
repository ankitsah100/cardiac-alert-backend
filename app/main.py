"""
Cardiac Alert Backend — Cloud Version
Deployed on Railway via GitHub
"""

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import Optional
import asyncio, json, time
from datetime import datetime

from .analyzer import CardiacAnalyzer
from .alerts import AlertManager
from .store import DataStore

app = FastAPI(title="Cardiac Alert System", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

analyzer = CardiacAnalyzer()
alert_mgr = AlertManager()
store = DataStore()
dashboard_clients: list[WebSocket] = []

# Auto-register default patient on startup
store.register_patient({"patient_id": "ankit_001", "name": "Ankit", "age": 26, "emergency_contact": "+9779800000000", "baseline_hr": 72.0, "baseline_hrv": 45.0})

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
    """
    Accepts data from Life Dashboard Companion app.
    Extracts heart rate, SpO2, HRV and processes them.
    """
    try:
        # Extract heart rate — take latest reading
        hr = None
        hr_list = payload.get("heart_rate", [])
        if hr_list:
            hr = hr_list[-1].get("bpm") or hr_list[-1].get("beatsPerMinute")

        # Extract SpO2
        spo2 = None
        spo2_list = payload.get("oxygen_saturation", [])
        if spo2_list:
            spo2 = spo2_list[-1].get("percentage") or spo2_list[-1].get("value")
            if spo2 and spo2 < 2:  # stored as 0.98 not 98
                spo2 = spo2 * 100

        # Extract HRV
        hrv = None
        hrv_list = payload.get("heart_rate_variability", [])
        if hrv_list:
            hrv = hrv_list[-1].get("heartRateVariabilityMillis") or hrv_list[-1].get("value")

        # Fallback if no HR found
        if not hr:
            return {"message": "No heart rate data found in payload", "received_keys": list(payload.keys())}

        # Build a WatchReading and process it
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

@app.get("/patient/{patient_id}/summary")
def get_summary(patient_id: str):
    latest = store.get_latest(patient_id)
    if not latest:
        return "No data yet. Sync your watch first."
    hr = latest.get("heart_rate", "?")
    spo2 = latest.get("spo2")
    hrv = latest.get("hrv_rmssd")
    risk = latest.get("risk_level", "unknown").upper()
    score = latest.get("risk_score", 0)
    flags = latest.get("flags", [])
    if risk == "CRITICAL":
        emoji = "🚨"
    elif risk == "WARNING":
        emoji = "⚠️"
    else:
        emoji = "✅"
    msg = f"{emoji} HR: {hr} bpm | Risk: {risk}"
    if spo2:
        msg += f" | SpO2: {spo2}%"
    if hrv:
        msg += f" | HRV: {hrv}ms"
    if flags:
        flag_text = ", ".join(flags).replace("_", " ")
        msg += f"\nFlags: {flag_text}"
    msg += f"\nScore: {score}"
    return msg
