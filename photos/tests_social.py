from datetime import timedelta

from django.test import override_settings
from django.urls import reverse

from events import timeutils
from .models import Comment, Like, Photo
from .security import device_hash
from .tests_gallery import GalleryBase, TOKEN


class SocialBase(GalleryBase):
    def list_comments(self, photo, token=TOKEN):
        return self.client.get(self.url("photo_comments", photo_id=photo.id),
                               HTTP_X_DEVICE_TOKEN=token)

    def create_comment(self, photo, body, name="", token=TOKEN, **extra):
        return self.post("photo_comment_create", {"body": body, "name": name}, token=token,
                         photo_id=photo.id, **extra)

    def delete_comment(self, photo, comment, token=TOKEN):
        return self.post("photo_comment_delete", token=token,
                         photo_id=photo.id, comment_id=comment.id)

    def toggle_like(self, photo, token=TOKEN):
        return self.post("photo_like", token=token, photo_id=photo.id)


class CommentTests(SocialBase):
    def test_create_list_mine_delete_own(self):
        p = self.make_photo()
        self.assertEqual(self.create_comment(p, "Lovely!").status_code, 200)
        self.assertEqual(self.create_comment(p, "Second!", name="Ann",
                                             token="b" * 32).status_code, 200)
        data = self.list_comments(p).json()
        self.assertEqual([c["body"] for c in data["comments"]], ["Lovely!", "Second!"])
        self.assertEqual(data["count"], 2)
        mine = data["comments"][0]
        not_mine = data["comments"][1]
        self.assertTrue(mine["mine"])
        self.assertFalse(not_mine["mine"])
        self.assertEqual(mine["name"], "")
        self.assertEqual(not_mine["name"], "Ann")
        self.assertEqual(self.delete_comment(p, Comment.objects.get(body="Second!"),
                                             token=TOKEN).status_code, 403)
        self.assertEqual(self.delete_comment(p, mine["id"] and Comment.objects.get(body="Lovely!"),
                                             token="b" * 32).status_code, 403)
        self.assertEqual(self.delete_comment(p, Comment.objects.get(body="Lovely!")).status_code, 200)
        self.assertEqual(Comment.objects.count(), 1)

    def test_validation_and_sanitisation(self):
        p = self.make_photo()
        self.assertEqual(self.create_comment(p, "   ").status_code, 400)
        self.assertEqual(self.create_comment(p, "").status_code, 400)
        self.assertEqual(self.create_comment(p, "x" * 501).status_code, 400)
        self.assertEqual(self.create_comment(p, "hi", token="bad token!").status_code, 400)
        self.assertEqual(self.create_comment(p, "\x00<b>safe</b>\r\ntext\x7f  ").status_code, 200)
        self.assertEqual(Comment.objects.get().body, "<b>safe</b>\ntext")
        self.assertEqual(Comment.objects.get().name, "")
        self.assertEqual(self.create_comment(p, "Merci beaucoup — émoji 🎉").status_code, 200)
        self.assertEqual(Comment.objects.order_by("-id").first().body, "Merci beaucoup — émoji 🎉")

    def test_approved_only_and_event_scoped(self):
        pending = self.make_photo(status=Photo.Status.PENDING)
        self.assertEqual(self.create_comment(pending, "nope").status_code, 404)
        self.assertEqual(self.list_comments(pending).status_code, 404)
        other = self.make_photo(status=Photo.Status.APPROVED)
        self.assertEqual(self.post("photo_like", photo_id=other.id, token=TOKEN).status_code, 200)

    def test_pin_and_expiry_enforced_owner_bypasses(self):
        p = self.make_photo()
        self.lock_with_pin()
        self.assertEqual(self.create_comment(p, "hi").status_code, 403)
        self.assertEqual(self.toggle_like(p).status_code, 403)
        self.client.post(reverse("events:pin", args=[self.event.public_code]), {"pin": "4821"})
        self.assertEqual(self.create_comment(p, "hi").status_code, 200)
        self.event.expires_at = timeutils.end_of_day(timeutils.local_today() - timedelta(days=1))
        self.event.save()
        self.assertEqual(self.create_comment(p, "gone").status_code, 410)
        self.assertEqual(self.toggle_like(p).status_code, 410)
        self.client.force_login(self.owner)
        self.assertEqual(self.create_comment(p, "owner").status_code, 200)
        self.assertEqual(self.toggle_like(p).status_code, 200)

    @override_settings(COMMENT_RATE_PER_DEVICE=2, COMMENT_RATE_PER_IP=1000)
    def test_comment_rate_limit(self):
        p = self.make_photo()
        self.assertEqual(self.create_comment(p, "one").status_code, 200)
        self.assertEqual(self.create_comment(p, "two").status_code, 200)
        self.assertEqual(self.create_comment(p, "three").status_code, 429)


class LikeTests(SocialBase):
    def test_toggle_and_server_authoritative_count(self):
        p = self.make_photo()
        self.assertEqual(self.toggle_like(p).json(), {"liked": True, "count": 1})
        self.assertEqual(self.toggle_like(p).json(), {"liked": False, "count": 0})
        self.assertEqual(self.toggle_like(p).json()["liked"], True)
        self.assertEqual(self.toggle_like(p, token="b" * 32).json()["count"], 2)
        self.assertEqual(self.toggle_like(p, token="b" * 32).json()["count"], 1)

    def test_unique_constraint_on_like_actor_and_photo(self):
        from django.db import IntegrityError

        p = self.make_photo()
        Like.objects.create(photo=p, actor_hash=device_hash(TOKEN))
        with self.assertRaises(IntegrityError):
            Like.objects.create(photo=p, actor_hash=device_hash(TOKEN))

    def test_counts_cascaded_when_photo_deleted(self):
        p = self.make_photo()
        self.toggle_like(p)
        self.create_comment(p, "bye")
        self.assertEqual(self.post("photo_delete", photo_id=p.id).status_code, 200)
        self.assertEqual(Like.objects.count(), 0)
        self.assertEqual(Comment.objects.count(), 0)

    def test_like_requires_token(self):
        self.assertEqual(self.post("photo_like", token=None, photo_id=self.make_photo().id).status_code, 400)

    @override_settings(LIKE_RATE_PER_DEVICE=2, LIKE_RATE_PER_IP=1000)
    def test_like_rate_limit(self):
        p = self.make_photo()
        codes = [self.toggle_like(p).status_code for _ in range(3)]
        self.assertEqual(codes, [200, 200, 429])


class CountsInGalleryTests(SocialBase):
    def test_photo_list_includes_likes_and_comments(self):
        p = self.make_photo()
        self.toggle_like(p)
        self.create_comment(p, "nice", token="b" * 32)
        data = self.client.get(self.url("photo_list"), HTTP_X_DEVICE_TOKEN=TOKEN).json()
        item = data["photos"][0]
        self.assertEqual(item["likes"], 1)
        self.assertEqual(item["liked"], True)
        self.assertEqual(item["comments"], 1)
        other = self.client.get(self.url("photo_list"), HTTP_X_DEVICE_TOKEN="c" * 32).json()["photos"][0]
        self.assertFalse(other["liked"])
        self.assertEqual(other["likes"], 1)
        self.assertEqual(other["comments"], 1)