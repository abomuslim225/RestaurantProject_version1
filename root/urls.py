
from django.contrib import admin
from django.urls import path, include
from django.views.generic import TemplateView
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    # ── ADMIN ─────────────────────────────────────────────
    path('admin/', admin.site.urls),
    path('api/v1/', include('apps.urls')),
    # ── API ───────────────────────────────────────────────


    # ── BOSH SAHIFA (Linktree) ──────────────────────────────
    path('', TemplateView.as_view(template_name='linktree.html')),

    # ── RESTORAN PANELI (mijozlar uchun, eski index.html) ──
    path('restaurant/', TemplateView.as_view(template_name='index.html')),

    # ── TEMPLATES ─────────────────────────────────────────

    path('menu/', TemplateView.as_view(template_name='menu.html')),
    path('owner/', TemplateView.as_view(template_name='owner_final_design.html')),
    path('waiter/', TemplateView.as_view(template_name='waiter.html')),
    path('chef/', TemplateView.as_view(template_name='chef_panel.html')),
    path('login/', TemplateView.as_view(template_name='employee_login.html')),
    path('manager/', TemplateView.as_view(template_name='manager.html')),
    path('cashier/', TemplateView.as_view(template_name='cashier.html')),
    path('accountant/', TemplateView.as_view(template_name='accountant.html')),

] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

