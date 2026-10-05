from django.urls import path

from . import views

app_name = "dashboard"
urlpatterns = [
    path("", views.overview, name="overview"),
    path("events/<uuid:pk>/", views.event_dashboard, name="event"),
    path("events/<uuid:pk>/photos/", views.photos, name="photos"),
    path("events/<uuid:pk>/review/", views.review, name="review"),
    path("events/<uuid:pk>/bulk/", views.bulk, name="bulk"),
    path("events/<uuid:pk>/reports/", views.reports, name="reports"),
    path("events/<uuid:pk>/reports/<uuid:photo_id>/", views.report_action, name="report_action"),
    path("events/<uuid:pk>/contributors/", views.contributors, name="contributors"),
    path("events/<uuid:pk>/contributors/remove/", views.contributor_remove, name="contributor_remove"),
    path("events/<uuid:pk>/photos.zip", views.download_zip, name="download_zip"),
    path("events/<uuid:pk>/toggle/<slug:field>/", views.toggle, name="toggle"),
    path("events/<uuid:pk>/regenerate-code/", views.regenerate, name="regenerate"),
    path("events/<uuid:pk>/delete/", views.delete_event, name="delete"),
]
