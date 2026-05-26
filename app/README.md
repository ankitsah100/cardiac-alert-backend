# ❤️ Cardiac Alert System — Cloud Setup Guide

## Architecture
```
Glory Fit Watch
     ↓ (Bluetooth)
Glory Fit App
     ↓ (sync)
Health Connect (Android)
     ↓ (HTTP Shortcuts app, every 30s)
Railway Cloud Backend  ←── This repo, auto-deployed from GitHub
     ↓
SMS Alert (Twilio) + Live Dashboard
```

---

## Step 1 — Deploy to Railway (free)

1. Go to railway.app → Login with GitHub
2. Click "New Project" → "Deploy from GitHub repo"
3. Select this repo → Railway auto-detects Python and deploys
4. After deploy, click your project → copy the public URL
   - Looks like: `https://cardiac-alert-xxxx.up.railway.app`

---

## Step 2 — Register yourself as a patient

Open this URL in your browser (replace with your Railway URL):

```
POST https://YOUR-RAILWAY-URL/patient/register
```

Or use this curl command:
```bash
curl -X POST https://YOUR-RAILWAY-URL/patient/register \
  -H "Content-Type: application/json" \
  -d '{
    "patient_id": "ankit_001",
    "name": "Ankit",
    "age": 26,
    "emergency_contact": "+9779800000000",
    "baseline_hr": 72,
    "baseline_hrv": 45
  }'
```

---

## Step 3 — Connect Glory Fit via HTTP Shortcuts (Android)

### Install HTTP Shortcuts
Play Store → search "HTTP Shortcuts" by Waboodoo → Install

### Create a shortcut
1. Open HTTP Shortcuts → + button → Regular Shortcut
2. Name: "Send Heart Rate"
3. Method: POST
4. URL: `https://YOUR-RAILWAY-URL/reading`
5. Request body (JSON):
```json
{
  "patient_id": "ankit_001",
  "timestamp": {timestamp},
  "heart_rate": {heart_rate},
  "spo2": {spo2}
}
```
6. Save

### Automate with Tasker (optional, runs every 30s automatically)
- Install Tasker from Play Store
- Create task → HTTP Request → point to your shortcut
- Set trigger: Time → repeat every 30 seconds

---

## Step 4 — SMS Alerts (optional, needs Twilio)

1. Sign up free at twilio.com (trial gives you $15 credit)
2. Get your Account SID, Auth Token, and phone number
3. In Railway → your project → Variables → add:
   - `TWILIO_SID` = your account SID
   - `TWILIO_TOKEN` = your auth token  
   - `TWILIO_FROM` = your Twilio number e.g. +1xxxxxxxxxx

---

## API Endpoints

| Method | Endpoint | What it does |
|--------|----------|--------------|
| GET  | / | Status page (open in browser) |
| POST | /patient/register | Register a patient |
| POST | /reading | Send a heart rate reading |
| GET  | /patient/{id}/status | Latest reading + risk |
| GET  | /patient/{id}/history | Last 50 readings |

---

## Risk Levels

| Level | Score | What happens |
|-------|-------|--------------|
| normal | 0.0–0.39 | Logged silently |
| warning | 0.40–0.74 | Logged + dashboard alert |
| critical | 0.75–1.0 | SMS to emergency contact |
