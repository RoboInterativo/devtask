from django.db import models


class Job(models.Model):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    STATUSES = [(PENDING, PENDING), (RUNNING, RUNNING), (DONE, DONE), (FAILED, FAILED)]

    name = models.CharField(max_length=100)
    status = models.CharField(max_length=20, choices=STATUSES, default=PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-id"]

    def __str__(self):
        return f"{self.pk}:{self.name}:{self.status}"
