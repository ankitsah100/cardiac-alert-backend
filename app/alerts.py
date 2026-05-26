"""
AlertManager
Sends alerts when cardiac risk is detected.
- WARNING level  → push notification / log
- CRITICAL level → SMS via Twilio + push notification

Configure Twilio credentials via environment variables:
    TWILIO_SID, TWILIO_TOKEN, TWILIO_FROM
"""

import os
import asyncio
from datetime import datetime


class AlertManager:

    def __init__(self):
        self.twilio_sid   = os.getenv("TWILIO_SID")
        self.twilio_token = os.getenv("TWILIO_TOKEN")
        self.twilio_from  = os.getenv("TWILIO_FROM")   # your Twilio number
        self._twilio = None
        self._last_alert: dict[str, float] = {}  # patient_id -> last alert timestamp
        self.COOLDOWN_SEC = 120  # don't re-alert same patient within 2 minutes

    def _get_twilio(self):
        if self._twilio is None and self.twilio_sid:
            try:
                from twilio.rest import Client
                self._twilio = Client(self.twilio_sid, self.twilio_token)
            except ImportError:
                print("[Alert] Twilio not installed. Run: pip install twilio")
        return self._twilio

    async def send(self, level: str, patient_id: str, patient_name: str,
                   flags: list, hr: float, contact: str = None):
        import time
        now = time.time()
        last = self._last_alert.get(patient_id, 0)
        if now - last < self.COOLDOWN_SEC:
            return  # already alerted recently
        self._last_alert[patient_id] = now

        msg = self._compose_message(level, patient_name, flags, hr)

        # Always log to console
        print(f"\n{'='*50}")
        print(f"[ALERT] {level.upper()} — {datetime.utcnow().isoformat()}")
        print(f"Patient : {patient_name} ({patient_id})")
        print(f"HR      : {hr} bpm")
        print(f"Flags   : {', '.join(flags)}")
        print(f"Message : {msg}")
        print(f"{'='*50}\n")

        # Send SMS for critical alerts if Twilio configured
        if level == "critical" and contact:
            await asyncio.to_thread(self._send_sms, contact, msg)

    def _send_sms(self, to: str, body: str):
        client = self._get_twilio()
        if client is None:
            print(f"[Alert] SMS skipped — Twilio not configured. Would send to {to}:")
            print(f"        {body}")
            return
        try:
            message = client.messages.create(
                body=body,
                from_=self.twilio_from,
                to=to,
            )
            print(f"[Alert] SMS sent. SID={message.sid}")
        except Exception as e:
            print(f"[Alert] SMS failed: {e}")

    def _compose_message(self, level: str, name: str, flags: list, hr: float) -> str:
        flag_text = ", ".join(flags).replace("_", " ")
        if level == "critical":
            return (
                f"URGENT: {name} cardiac alert. "
                f"HR={hr:.0f}bpm. Issues: {flag_text}. "
                f"Check immediately or call emergency services."
            )
        return (
            f"Warning: {name} showing abnormal heart activity. "
            f"HR={hr:.0f}bpm. Flags: {flag_text}. Please check."
        )
