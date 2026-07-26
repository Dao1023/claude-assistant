"""信箱读写与状态回写"""
import json

from ..config import INBOX


def load_inbox():
    try:
        return json.loads(INBOX.read_text(encoding="utf-8"))
    except Exception:
        return {"reminders": []}


def save_inbox(data):
    INBOX.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def set_status(rid, status, note=""):
    data = load_inbox()
    for r in data["reminders"]:
        if r["id"] == rid:
            r["status"] = status
            if note:
                r["note"] = note
    save_inbox(data)
