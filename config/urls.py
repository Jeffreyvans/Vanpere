from django.contrib import admin
from django.http import HttpResponse
from django.urls import include, path
from django.views.generic import TemplateView

admin.site.site_header = "VanPere Digital Admin"
admin.site.site_title = "VanPere Digital Admin"
admin.site.index_title = "VanPere Digital administration"


def healthz(request):
    return HttpResponse("ok")


def robots(request):
    body = "User-agent: *\nDisallow: /event/\nDisallow: /dashboard/\n"
    return HttpResponse(body, content_type="text/plain")


urlpatterns = [
    path("", TemplateView.as_view(template_name="landing.html"), name="landing"),
    path("accounts/", include("accounts.urls")),
    path("privacy/", TemplateView.as_view(template_name="legal/privacy.html"), name="privacy"),
    path("terms/", TemplateView.as_view(template_name="legal/terms.html"), name="terms"),
    path("", include("events.urls")),
    path("", include("photos.urls")),
    path("dashboard/", include("dashboard.urls")),
    path("healthz/", healthz),
    path("robots.txt", robots),
    path("admin/", admin.site.urls),
]
