"""
SchedulerService — in-process APScheduler wrapper (Phase 7).

Runs the reminder cycle every hour in the FastAPI process.
Disable with env REMINDER_SCHEDULER_ENABLED=0 (e.g. during tests).
"""

import os

from apscheduler.schedulers.background import BackgroundScheduler

from app.database.database import SessionLocal
from app.services.reminder_service import ReminderService

_scheduler = None


def run_reminder_cycle():
    """One full reminder pass with its own DB session."""
    db = SessionLocal()
    try:
        summary = ReminderService.run_all(db)
        print(f"[REMINDERS] cycle done: {summary}")
    except Exception as e:
        print(f"[REMINDERS] cycle failed: {e}")
    finally:
        db.close()


def start_scheduler():
    """Start the background scheduler once (idempotent)."""
    global _scheduler

    enabled = os.getenv("REMINDER_SCHEDULER_ENABLED", "1") != "0"
    if not enabled:
        print("[REMINDERS] scheduler disabled via REMINDER_SCHEDULER_ENABLED=0")
        return None

    if _scheduler is not None:
        return _scheduler

    _scheduler = BackgroundScheduler(timezone="Asia/Kolkata")
    _scheduler.add_job(
        run_reminder_cycle,
        trigger="interval",
        hours=1,
        id="reminder_cycle",
        coalesce=True,
        max_instances=1
    )
    _scheduler.start()
    print("[REMINDERS] scheduler started (hourly cycle)")
    return _scheduler


def stop_scheduler():
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        print("[REMINDERS] scheduler stopped")


def scheduler_running() -> bool:
    return _scheduler is not None and _scheduler.running
