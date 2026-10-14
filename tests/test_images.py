"""Upload pictures are decoded, cleaned and re-encoded; anything else is refused."""

import io

import pytest
from PIL import Image

from utils.images import COVER_SPEC, LOGO_SPEC, ImageProblem, ImageRejectedError, process_image


def picture(
    fmt: str = "JPEG", size: tuple[int, int] = (800, 1200), mode: str = "RGB", **save: object
) -> bytes:
    image = Image.new(mode, size, "white" if mode != "1" else 1)
    out = io.BytesIO()
    image.save(out, format=fmt, **save)
    return out.getvalue()


def decode(data: bytes) -> Image.Image:
    image = Image.open(io.BytesIO(data))
    image.load()
    return image


def test_cover_variants_are_webp_and_never_enlarged() -> None:
    variants = process_image(picture(size=(300, 450)), COVER_SPEC)
    assert set(variants) == {"s", "m", "l"}
    sizes = {name: decode(data).size for name, data in variants.items()}
    assert all(decode(data).format == "WEBP" for data in variants.values())
    assert sizes["s"] == (160, 240)
    assert sizes["m"] == (300, 450)  # smaller than 320 wide: kept as is
    assert sizes["l"] == (300, 450)


def test_exif_rotation_is_applied_and_metadata_dropped() -> None:
    exif = Image.Exif()
    exif[0x0112] = 6  # orientation: rotate 90° (a phone held upright)
    exif[0x8825] = {2: (41.0, 18.0, 0.0)}  # GPS latitude — must not survive
    variants = process_image(picture(size=(1200, 800), exif=exif), COVER_SPEC)
    result = decode(variants["l"])
    assert result.size[0] < result.size[1]  # portrait after rotation
    assert not result.getexif()


def test_transparent_logo_keeps_alpha() -> None:
    image = Image.new("RGBA", (600, 600), (255, 255, 255, 0))
    out = io.BytesIO()
    image.save(out, format="PNG")
    variants = process_image(out.getvalue(), LOGO_SPEC)
    assert decode(variants["s"]).mode == "RGBA"


@pytest.mark.parametrize(
    ("data", "problem"),
    [
        (b"<html>not a picture</html>", ImageProblem.NOT_AN_IMAGE),
        (picture()[:200], ImageProblem.NOT_AN_IMAGE),  # truncated JPEG
        (picture("GIF", (300, 300), mode="P"), ImageProblem.UNSUPPORTED_FORMAT),
        (picture(size=(100, 100)), ImageProblem.TOO_SMALL),
        (picture(size=(130, 1000)), ImageProblem.BAD_PROPORTIONS),
        # 10 000 x 5 000 = 50 MP of one colour compresses to a few KB: a decompression bomb.
        (picture("PNG", (10_000, 5_000), mode="1"), ImageProblem.TOO_LARGE),
    ],
)
def test_bad_uploads_are_refused(data: bytes, problem: ImageProblem) -> None:
    with pytest.raises(ImageRejectedError) as exc_info:
        process_image(data, COVER_SPEC)
    assert exc_info.value.problem == problem
