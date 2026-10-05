from django.conf import settings


def get_storage():
    """Return the configured PhotoStorage (STORAGE_BACKEND=local|s3)."""
    if settings.STORAGE_BACKEND == "s3":
        from .s3 import S3PhotoStorage
        return S3PhotoStorage()
    from .local import LocalPhotoStorage
    return LocalPhotoStorage()
