import socket

from django.core.cache import cache
from django.http import FileResponse, Http404
from rest_framework import mixins, viewsets
from rest_framework.decorators import action, api_view
from rest_framework.response import Response

from .models import Job
from .serializers import JobSerializer
from .tasks import artifact_path, run_job


class JobViewSet(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    queryset = Job.objects.all()
    serializer_class = JobSerializer

    def perform_create(self, serializer):
        job = serializer.save()
        run_job.delay(job.pk)

    @action(detail=True, methods=["get"])
    def log(self, request, pk=None):
        """Отдаёт лог прогона, который записал воркер."""
        path = artifact_path(pk)
        if not path.exists():
            raise Http404("log not found")
        return FileResponse(open(path, "rb"), content_type="text/plain")


@api_view(["GET"])
def stats(request):
    """Счётчик запросов к API."""
    try:
        count = cache.incr("requests")
    except ValueError:
        cache.set("requests", 1, None)
        count = 1
    return Response({"requests": count, "host": socket.gethostname()})
