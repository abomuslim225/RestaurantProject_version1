from django.urls import path, re_path

from apps.consumers import DashboardConsumer, WaiterConsumer, ChefConsumer, ManagerConsumer, CashierConsumer

websocket_urlpatterns = [
    re_path(r"^ws/waiter/$", WaiterConsumer.as_asgi()),
    re_path(r"^ws/chef/$", ChefConsumer.as_asgi()),
    re_path(r"^ws/manager/$", ManagerConsumer.as_asgi()),
    re_path(r"^ws/dashboard/$", DashboardConsumer.as_asgi()),  # ← QO'SHISH
    re_path(r"^ws/cashier/$", CashierConsumer.as_asgi()),
]
