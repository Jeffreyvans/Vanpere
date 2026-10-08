"""Pure Pillow helpers (no Django): validation, orientation, WebP derivatives.

`build_versions` decodes from a file path so huge originals are read from disk and
never held whole in memory besides the decoded pixels themselves.
"""
import io
import hashlib

from PIL import Image, ImageOps

try:
    import pillow_heif
    pillow_heif.register_heif_opener()
except ImportError:  # HEIC then fails validation with a clear message
    pass

MAX_PIXELS = 50_000_000
ALLOWED_FORMATS = {"JPEG", "MPO", "PNG", "WEBP", "HEIF"}


class PhotoRejected(ValueError):
    """The upload is not an acceptable image."""


def open_validated_path(path: str) -> Image.Image:
    """Validate by content, apply EXIF orientation and return an RGB image."""
    try:
        probe = Image.open(path)
        if probe.format not in ALLOWED_FORMATS:
            raise PhotoRejected("Unsupported image type.")
        if probe.width * probe.height > MAX_PIXELS:
            raise PhotoRejected("Image dimensions are too large.")
        img = ImageOps.exif_transpose(Image.open(path))
        if img.mode in ("RGBA", "LA", "P"):
            rgba = img.convert("RGBA")
            flat = Image.new("RGB", rgba.size, "white")
            flat.paste(rgba, mask=rgba.getchannel("A"))
            return flat
        return img.convert("RGB")
    except PhotoRejected:
        raise
    except Exception as exc:
        raise PhotoRejected("The file is not a valid image.") from exc


def encode_webp(img: Image.Image, max_edge: int | None, quality: int) -> tuple[bytes, tuple[int, int]]:
    """Re-encode from raw pixels so no EXIF, GPS or other metadata is carried over."""
    work = img.copy()
    if max_edge:
        work.thumbnail((max_edge, max_edge), Image.LANCZOS)
    clean = Image.frombytes("RGB", work.size, work.tobytes())
    buf = io.BytesIO()
    clean.save(buf, "WEBP", quality=quality, method=6)
    return buf.getvalue(), clean.size


def encode_jpeg(img: Image.Image, max_edge: int | None, quality: int = 82) -> tuple[bytes, tuple[int, int]]:
    """JPEG re-encode (used for event covers); also strips metadata like encode_webp."""
    work = img.copy()
    if max_edge:
        work.thumbnail((max_edge, max_edge), Image.LANCZOS)
    clean = Image.frombytes("RGB", work.size, work.tobytes())
    buf = io.BytesIO()
    clean.save(buf, "JPEG", quality=quality, optimize=True, progressive=True)
    return buf.getvalue(), clean.size


def build_versions(path: str, thumb_edge: int, preview_edge: int) -> dict:
    """Return thumb/preview WebP bytes plus the oriented source size."""
    img = open_validated_path(path)
    thumb, _ = encode_webp(img, thumb_edge, 72)
    preview, size = encode_webp(img, preview_edge, 80)
    return {"thumb": thumb, "preview": preview, "size": size}


def file_sha256(path: str) -> str:
    """Streaming SHA-256 so digesting a huge original uses constant memory."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()