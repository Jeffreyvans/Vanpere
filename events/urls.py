from django.urls import path

from . import views

app_name = "events"
urlpatterns = [
    path("events/", views.event_list, name="list"),
    path("events/new/", views.event_create, name="create"),
    path("events/<uuid:pk>/", views.event_detail, name="detail"),
    path("events/<uuid:pk>/edit/", views.event_edit, name="edit"),
    path("events/<uuid:pk>/qr.png", views.qr_png, name="qr_png"),
    path("events/<uuid:pk>/qr.svg", views.qr_svg, name="qr_svg"),
    path("events/<uuid:pk>/poster/<slug:size>.pdf", views.poster, name="poster"),
    path("event/<str:code>/", views.event_public, name="public"),
    path("event/<str:code>/cover/", views.event_cover, name="cover"),
    path("event/<str:code>/pin/", views.event_pin, name="pin"),
]
