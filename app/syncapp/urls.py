from django.contrib import admin
from django.urls import include, path
from django.http import JsonResponse

def healthz(request):
    return JsonResponse({"status": "ok"})

urlpatterns = [
    path("healthz", healthz),
    path("admin/", admin.site.urls),
    path("api/", include("jobs.urls")),
]
