from django.urls import path

from . import api, gallery_api, social_api, views

app_name = "photos"
urlpatterns = [
    path("event/<str:code>/upload/", views.upload_page, name="upload"),
    path("api/events/<str:code>/consent/", api.consent, name="consent"),
    path("api/events/<str:code>/check-hash/", api.check_hash, name="check_hash"),
    path("api/events/<str:code>/uploads/init/", api.init_upload, name="init"),
    path("api/events/<str:code>/uploads/<uuid:photo_id>/part/", api.upload_part, name="upload_part"),
    path("api/events/<str:code>/uploads/<uuid:photo_id>/file/", api.upload_file, name="file"),
    path("api/events/<str:code>/uploads/<uuid:photo_id>/poster/", api.upload_poster, name="poster"),
    path("api/events/<str:code>/uploads/<uuid:photo_id>/abort/", api.abort_upload, name="abort_upload"),
    path("api/events/<str:code>/uploads/<uuid:photo_id>/finalise/", api.finalise, name="finalise"),
    path("event/<str:code>/gallery/", views.gallery_page, name="gallery"),
    path("event/<str:code>/slideshow/", views.slideshow_page, name="slideshow"),
    path("media/<str:token>/", views.media, name="media"),
    path("api/events/<str:code>/photos/", gallery_api.photo_list, name="photo_list"),
    path("api/events/<str:code>/slideshow/", gallery_api.slideshow_data, name="slideshow_data"),
    path("api/events/<str:code>/photos/<uuid:photo_id>/download/", gallery_api.download, name="photo_download"),
    path("api/events/<str:code>/photos/<uuid:photo_id>/report/", gallery_api.photo_report, name="photo_report"),
    path("api/events/<str:code>/photos/<uuid:photo_id>/delete/", gallery_api.photo_delete, name="photo_delete"),
    path("api/events/<str:code>/photos/<uuid:photo_id>/comments/", social_api.comment_list, name="photo_comments"),
    path("api/events/<str:code>/photos/<uuid:photo_id>/comments/create/", social_api.comment_create, name="photo_comment_create"),
    path("api/events/<str:code>/photos/<uuid:photo_id>/comments/<int:comment_id>/delete/",
         social_api.comment_delete, name="photo_comment_delete"),
    path("api/events/<str:code>/photos/<uuid:photo_id>/like/", social_api.like_toggle, name="photo_like"),
    path("event/sw.js", views.service_worker, name="service_worker"),
    path("event/<str:code>/p/<uuid:photo_id>/", views.photo_page, name="photo"),
    path("event/<str:code>/p/<uuid:photo_id>/og.jpg", views.photo_og, name="photo_og"),
]
