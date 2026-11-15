"""Upload validation and image preparation. No image is ever written to disk."""

import io
from dataclasses import dataclass

from PIL import Image, UnidentifiedImageError

# Vercel functions reject request bodies over 4.5 MB, so we cap uploads below that.
MAX_UPLOAD_BYTES = 4 * 1024 * 1024
MAX_SIDE_PX = 1024  # enough detail to recognise household items; fewer tokens means faster, cheaper scans
MAX_PIXELS = 40_000_000  # about 6300 x 6300; phone photos are around 12 megapixels
ALLOWED_FORMATS = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}
ALLOWED_CONTENT_TYPES = set(ALLOWED_FORMATS.values()) | {"image/jpg"}


class ImageValidationError(ValueError):
    """Raised with a message that is safe to show the user."""


@dataclass(frozen=True)
class PreparedImage:
    data: bytes
    media_type: str
    width: int
    height: int


def prepare_image(raw: bytes, content_type: str | None) -> PreparedImage:
    if not raw:
        raise ImageValidationError("That file is empty. Please choose a photo.")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise ImageValidationError("That photo is larger than 4 MB. Please choose a smaller photo or a lower camera resolution.")
    if content_type and content_type.lower() not in ALLOWED_CONTENT_TYPES:
        raise ImageValidationError("Please upload a JPG, PNG or WEBP photo.")

    # Check the actual bytes, not the file name or the browser's claim.
    try:
        with Image.open(io.BytesIO(raw)) as probe:
            fmt = probe.format
            width, height = probe.size
            probe.verify()
    except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError):
        raise ImageValidationError("We couldn't read that file as a photo. Please try a JPG, PNG or WEBP image.") from None
    if fmt not in ALLOWED_FORMATS:
        raise ImageValidationError("Please upload a JPG, PNG or WEBP photo.")
    # A tiny file can claim enormous dimensions ("decompression bomb"). Refuse before decoding.
    if width * height > MAX_PIXELS:
        raise ImageValidationError("That image is too large to process. Please use a normal phone photo.")

    try:
        img = Image.open(io.BytesIO(raw))
        img.load()
    except (OSError, Image.DecompressionBombError):
        raise ImageValidationError("We couldn't read that photo. Please try another one.") from None

    # Normalise: honour phone rotation, drop metadata (incl. GPS), downscale, re-encode.
    from PIL import ImageOps

    img = ImageOps.exif_transpose(img)
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    img.thumbnail((MAX_SIDE_PX, MAX_SIDE_PX))
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=85, optimize=True)
    return PreparedImage(out.getvalue(), "image/jpeg", img.width, img.height)
