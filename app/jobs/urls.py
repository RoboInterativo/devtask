from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import JobViewSet, stats

router = DefaultRouter()
router.register("jobs", JobViewSet, basename="job")

urlpatterns = [
    path("stats/", stats),
    path("", include(router.urls)),
]
