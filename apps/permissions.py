from rest_framework.permissions import BasePermission

from apps.models import User


class IsOwner(BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.role == "owner")

    def has_object_permission(self, request, view, obj):
        return obj != request.user

class IsManager(BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.role == "manager")

class IsChef(BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.role == "chef")

class IsWaiter(BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.role == "waiter")

class IsAccountant(BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.role == "accountant")


class IsCashier(BasePermission):
    def has_permission(self, request, view):
        return (
                request.user.is_authenticated
                and request.user.role in ('cashier', 'manager', 'owner')
        )
class IsMe(BasePermission):
    def has_permission(self, request, view):
        pass