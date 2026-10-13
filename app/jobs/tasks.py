import logging
import os
import time
from datetime import timedelta
from pathlib import Path

from celery import shared_task
from django.conf import settings
from django.db.models import Count
from django.utils import timezone

from .models import Job

logger = logging.getLogger(__name__)

# На одном хосте одновременно выполняется только одна задача (эмуляция
# «одна ВМ - один прогон тестов»)
LOCK_FILE = "/tmp/run_job.lock"


def artifact_path(job_id):
    return Path(settings.ARTIFACTS_DIR) / f"job_{job_id}.log"


@shared_task
def run_job(job_id):
    """Эмуляция прогона тестов на виртуальной машине."""
    while os.path.exists(LOCK_FILE):
        time.sleep(1)
    with open(LOCK_FILE, "w") as lock:
        lock.write(str(os.getpid()))

    job = None
    try:
        job = Job.objects.get(pk=job_id)
        job.status = Job.RUNNING
        job.started_at = timezone.now()
        job.save()
        logger.info("job %s started", job_id)

        Path(settings.ARTIFACTS_DIR).mkdir(parents=True, exist_ok=True)
        with open(artifact_path(job_id), "a") as out:
            for step in range(1, 6):
                time.sleep(settings.JOB_STEP_SECONDS)
                out.write(f"{timezone.now().isoformat()} step {step}/5 ok\n")
                out.flush()
                logger.info("job %s step %s/5", job_id, step)

        job.status = Job.DONE
    except Exception:
        logger.exception("job %s failed", job_id)
        if job is not None:
            job.status = Job.FAILED
        raise
    finally:
        if job is not None:
            job.finished_at = timezone.now()
            job.save()
        os.remove(LOCK_FILE)


@shared_task
def cleanup_old_artifacts():
    """Удаляет логи прогонов старше ARTIFACT_TTL_DAYS."""
    root = Path(settings.ARTIFACTS_DIR)
    if not root.exists():
        return 0
    border = time.time() - settings.ARTIFACT_TTL_DAYS * 86400
    removed = 0
    for f in root.glob("job_*.log"):
        if f.stat().st_mtime < border:
            f.unlink()
            removed += 1
    logger.info("cleanup: removed %s files", removed)
    return removed


@shared_task
def mark_stale_jobs():
    """Помечает зависшие (running > 30 минут) задачи как failed."""
    border = timezone.now() - timedelta(minutes=30)
    updated = Job.objects.filter(status=Job.RUNNING, started_at__lt=border).update(
        status=Job.FAILED, finished_at=timezone.now()
    )
    if updated:
        logger.warning("stale jobs marked failed: %s", updated)
    return updated


@shared_task
def daily_report():
    """Ежедневный отчёт по статусам задач (в логи)."""
    stats = dict(Job.objects.values_list("status").annotate(c=Count("id")))
    logger.info("daily report: %s", stats)
    return stats
