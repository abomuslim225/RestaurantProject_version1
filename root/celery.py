# root/celery.py
import os
from celery import Celery, shared_task
from celery.schedules import crontab


os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'root.settings')

app = Celery('root')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()

# Beat schedule — 4 ta task
app.conf.beat_schedule = {
    'create-daily-ingredients': {
        'task': 'apps.tasks.create_daily_ingredients',
        'schedule': crontab(hour=8, minute=0),  # 08:00
    },
    'close-daily-ingredients': {
        'task': 'apps.tasks.close_daily_ingredients',
        'schedule': crontab(hour=23, minute=0),  # 23:00
    },
}

