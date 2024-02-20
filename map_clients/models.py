from django.db import models


class MapClientManager(models.Model):
    current_map_client = models.CharField(default="tomtom")
