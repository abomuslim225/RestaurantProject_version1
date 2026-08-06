
from django.apps import AppConfig

class AppsConfig(AppConfig):
    name = 'apps'

    def ready(self):
        import apps.signals
