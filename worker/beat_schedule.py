"""
worker/beat_schedule.py

Celery Beat periodic task schedule.
Run the beat scheduler with:
    celery -A worker.celery_app beat --schedule=/tmp/celerybeat-schedule -l info
"""
from worker.celery_app import celery_app
from celery.schedules import crontab

celery_app.conf.beat_schedule = {
    # Scrape all dispute sources nightly at 2:00 AM UTC
    "nightly-dispute-scrape": {
        "task": "worker.tasks.scrape_task.scrape_disputes",
        "schedule": crontab(hour=2, minute=0),
        "options": {"queue": "scrapers"},
    },
    # Re-index contracts without embeddings every 6 hours
    "reindex-embeddings": {
        "task": "worker.tasks.scrape_task.scrape_disputes",
        "schedule": crontab(minute=0, hour="*/6"),
        "options": {"queue": "scrapers"},
    },
}

celery_app.conf.timezone = "UTC"
