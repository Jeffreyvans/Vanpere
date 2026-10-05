"""Pure Pillow helpers (no Django): validation, orientation, metadata-free JPEG versions."""
import io

from PIL import Image, ImageOps

try:
    import pillow_heif
    pillow_heif.register_heif_opener()
except ImportError:  # HEIC then fails validation with a clear message
    pass

MAX_PIXELS = 50_000_000
ALLOWED_FORMATS = {"JPEG", "MPO", "PNG", "WEBP", "HEIF"}
MEDIUM_EDGE, THUMB_EDGE = 1600, 480


class PhotoRejected(ValueError):
    """The upload is not an acceptable image."""


def open_validated(raw: bytes) -> Image.Image:
    """Validate by content, apply EXIF orientation, return an RGB image."""
    try:
        probe = Image.open(io.BytesIO(raw))
        if probe.format not in ALLOWED_FORMATS:
            raise PhotoRejected("Unsupported image type.")
        if probe.width * probe.height > MAX_PIXELS:
            raise PhotoRejected("Image dimensions are too large.")
        img = ImageOps.exif_transpose(Image.open(io.BytesIO(raw)))
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


def encode_jpeg(img: Image.Image, max_edge: int | None, quality: int) -> tuple[bytes, tuple[int, int]]:
    """Re-encode from raw pixels so no EXIF, GPS or other metadata is carried over."""
    work = img.copy()
    if max_edge:
        work.thumbnail((max_edge, max_edge), Image.LANCZOS)
    clean = Image.frombytes("RGB", work.size, work.tobytes())
    buf = io.BytesIO()
    clean.save(buf, "JPEG", quality=quality, optimize=True, progressive=True)
    return buf.getvalue(), clean.size


def build_versions(raw: bytes) -> dict:
    """Return original/medium/thumb JPEG bytes plus the oriented size."""
    img = open_validated(raw)
    original, size = encode_jpeg(img, None, 90)
    medium, _ = encode_jpeg(img, MEDIUM_EDGE, 82)
    thumb, _ = encode_jpeg(img, THUMB_EDGE, 78)
    return {"original": original, "medium": medium, "thumb": thumb, "size": size}
