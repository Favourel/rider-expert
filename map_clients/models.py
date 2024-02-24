from django.db import models


class MapClientManager(models.Model):
    current_map_client = models.CharField(default="tomtom", max_length=20)

    def __str__(self):
        return self.current_map_client
