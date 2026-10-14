import os

from celery import Celery
from celery.app.defaults import NAMESPACES

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "syncapp.settings")

app = Celery("syncapp")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

# Настройки, которые CLI Celery читает напрямую.
# Без них на Celery 5.6.x падает с AttributeError.
# app.conf.update(
#     worker_pool="prefork",
#     worker_prefetch_multiplier=4,
#     worker_disable_prefetch=False,
#     worker_concurrency=os.cpu_count() or 1,
#     worker_state_db=None,
#     worker_send_task_events=False,
#     worker_enable_remote_control=True,
#     worker_hijack_root_logger=False,
#     task_serializer="json",
#     result_serializer="json",
#     accept_content=["json"],
#     timezone="UTC",
#     enable_utc=True,
# )
