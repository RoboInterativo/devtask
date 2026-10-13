from rest_framework import serializers

from .models import Job


class JobSerializer(serializers.ModelSerializer):
    class Meta:
        model = Job
        fields = ["id", "name", "status", "created_at", "started_at", "finished_at"]
        read_only_fields = ["status", "created_at", "started_at", "finished_at"]
