import tempfile
from unittest import mock

from django.test import override_settings
from rest_framework.test import APITestCase

from .models import Job
from .tasks import run_job


@override_settings(ARTIFACTS_DIR=tempfile.mkdtemp(), JOB_STEP_SECONDS=0)
class JobApiTests(APITestCase):
    def test_create_job_runs_and_log_is_available(self):
        with mock.patch("jobs.views.run_job.delay") as delay:
            resp = self.client.post("/api/jobs/", {"name": "smoke"}, format="json")
        self.assertEqual(resp.status_code, 201)
        delay.assert_called_once_with(resp.data["id"])

        run_job(resp.data["id"])  # выполняем задачу синхронно, без брокера
        job = Job.objects.get(pk=resp.data["id"])
        self.assertEqual(job.status, Job.DONE)

        log = self.client.get(f"/api/jobs/{job.pk}/log/")
        self.assertEqual(log.status_code, 200)
        self.assertIn(b"step 5/5 ok", b"".join(log.streaming_content))

    def test_list_jobs(self):
        Job.objects.create(name="a")
        resp = self.client.get("/api/jobs/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["count"], 1)

    def test_stats_counter(self):
        first = self.client.get("/api/stats/").data["requests"]
        second = self.client.get("/api/stats/").data["requests"]
        self.assertEqual(second, first + 1)
