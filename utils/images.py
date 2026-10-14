"""
Image processing for uploads
============================
Every uploaded picture is decoded and re-encoded by us; the original bytes are
never stored or served. That:

  * rejects anything that is not really a JPEG, PNG or WebP picture
    (a renamed .exe or an HTML file with an image extension is refused);
  * drops EXIF metadata, which can carry the GPS position of the phone that took
    the photo;
  * applies the EXIF rotation, so phone photos are not sideways;
  * produces small WebP variants, so a storefront page loads fast on mobile data.

Decompression bombs (a tiny file that decodes to gigapixels) are refused from
the image header, before the pixels are decoded.

CPU-bound: call `process_image` through `asyncio.to_thread`.
"""

import io
import warnings
from dataclasses import dataclass
from enum import StrEnum

from PIL import Image, ImageOps, UnidentifiedImageError

ALLOWED_FORMATS = frozenset({"JPEG", "PNG", "WEBP"})
MAX_PIXELS = 40_000_000  # ~ 8000 x 5000; phone cameras stay well below
WEBP_QUALITY = 82

# Never decode more than this, even if a caller forgets to check the header.
Image.MAX_IMAGE_PIXELS = MAX_PIXELS


class ImageProblem(StrEnum):
    NOT_AN_IMAGE = "not_an_image"
    UNSUPPORTED_FORMAT = "unsupported_format"
    TOO_LARGE = "too_large"  # in pixels
    TOO_SMALL = "too_small"
    BAD_PROPORTIONS = "bad_proportions"  # e.g. a 100 x 2000 strip


class ImageRejectedError(ValueError):
    def __init__(self, problem: ImageProblem) -> None:
        super().__init__(problem.value)
        self.problem = problem


@dataclass(frozen=True, slots=True)
class ImageSpec:
    """Variants to produce: name -> longest allowed width in pixels."""

    widths: dict[str, int]
    min_side: int  # smaller pictures are refused: they would look broken
    max_aspect: float = 3.0  # height / width (and the reverse) at most this


COVER_SPEC = ImageSpec(widths={"s": 160, "m": 320, "l": 640}, min_side=120)
LOGO_SPEC = ImageSpec(widths={"s": 128, "l": 512}, min_side=64)
# Payment receipts: bank-app screenshots, often long and narrow; one readable size.
RECEIPT_SPEC = ImageSpec(widths={"l": 1600}, min_side=200, max_aspect=5.0)


def variant_key(base_key: str, name: str) -> str:
    return f"{base_key}-{name}.webp"


def process_image(data: bytes, spec: ImageSpec) -> dict[str, bytes]:
    """Decoded, cleaned WebP variants keyed by spec name. Raises ImageRejectedError."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            image = Image.open(io.BytesIO(data))
            if image.format not in ALLOWED_FORMATS:
                raise ImageRejectedError(ImageProblem.UNSUPPORTED_FORMAT)
            width, height = image.size  # from the header: nothing decoded yet
            if width * height > MAX_PIXELS:
                raise ImageRejectedError(ImageProblem.TOO_LARGE)
            image.load()
    except ImageRejectedError:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ImageRejectedError(ImageProblem.TOO_LARGE) from None
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError):
        raise ImageRejectedError(ImageProblem.NOT_AN_IMAGE) from None

    if min(width, height) < spec.min_side:
        raise ImageRejectedError(ImageProblem.TOO_SMALL)
    if max(width / height, height / width) > spec.max_aspect:
        raise ImageRejectedError(ImageProblem.BAD_PROPORTIONS)

    image = ImageOps.exif_transpose(image)
    has_alpha = image.mode in ("RGBA", "LA") or (image.mode == "P" and "transparency" in image.info)
    image = image.convert("RGBA" if has_alpha else "RGB")

    variants: dict[str, bytes] = {}
    for name, max_width in spec.widths.items():
        copy = image.copy()
        # thumbnail() keeps the aspect ratio and never enlarges a small picture.
        copy.thumbnail((max_width, round(max_width * spec.max_aspect)), Image.Resampling.LANCZOS)
        out = io.BytesIO()
        copy.save(out, format="WEBP", quality=WEBP_QUALITY, method=4)  # no exif= : metadata dropped
        variants[name] = out.getvalue()
    return variants
