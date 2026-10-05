"""Cover image handling (Pillow). Re-encodes so no metadata is kept."""
import io

from PIL import Image, ImageOps

MAX_COVER_BYTES = 10 * 1024 * 1024
MAX_PIXELS = 40_000_000
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}


def process_cover(fileobj) -> bytes:
    """Validate by content and return a metadata-free JPEG (max 1600 px). Raises ValueError."""
    data = fileobj.read()
    if len(data) > MAX_COVER_BYTES:
        raise ValueError("Cover image must be 10 MB or smaller.")
    try:
        probe = Image.open(io.BytesIO(data))
        if probe.format not in ALLOWED_FORMATS:
            raise ValueError("Cover image must be a JPG, PNG or WEBP file.")
        if probe.width * probe.height > MAX_PIXELS:
            raise ValueError("Cover image dimensions are too large.")
        img = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("That file is not a valid image.") from exc
    img.thumbnail((1600, 1600), Image.LANCZOS)
    clean = Image.frombytes("RGB", img.size, img.tobytes())
    out = io.BytesIO()
    clean.save(out, "JPEG", quality=85, optimize=True)
    return out.getvalue()
