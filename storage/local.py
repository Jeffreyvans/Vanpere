import io
import shutil
import time
from pathlib import Path

from django.conf import settings
from django.core import signing


class LocalPhotoStorage:
    """Filesystem backend under MEDIA_ROOT; no presigned uploads (server fallback)."""

    def __init__(self):
        self.root = Path(settings.MEDIA_ROOT).resolve()

    def _path(self, key):
        p = (self.root / key).resolve()
        if self.root not in p.parents and p != self.root:
            raise ValueError("Invalid storage key")
        return p

    def put(self, key, data, content_type):
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "wb") as f:
            f.write(data if isinstance(data, bytes) else data.read())

    def get_stream(self, key):
        # Copy into memory so the OS handle is released immediately. FileResponse plus the
        # Django test client otherwise leave the file open on Windows (WinError 32) until
        # the streaming body is consumed, which breaks TemporaryDirectory cleanup.
        with open(self._path(key), "rb") as f:
            return io.BytesIO(f.read())

    def delete(self, key):
        self._path(key).unlink(missing_ok=True)

    def delete_prefix(self, prefix):
        shutil.rmtree(self._path(prefix), ignore_errors=True)

    def exists(self, key):
        return self._path(key).is_file()

    def url(self, key, expires=3600, download_name=None):
        token = signing.dumps({"k": key, "d": download_name, "e": int(time.time()) + expires}, salt="media")
        return f"/media/{token}/"

    def presign_upload(self, key, content_type, max_bytes, expires=600):
        return None
