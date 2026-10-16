from __future__ import annotations

import io

import numpy as np
import pytest
from PIL import Image

from app.config import Settings
from app.errors import CorruptImageError, InvalidImageError, LimitExceededError
from app.preprocessing.decode import decode, probe, sniff_format
from tests.conftest import cartoon, encode


@pytest.mark.parametrize("fmt,kw,expected", [("PNG", {}, "png"), ("JPEG", {"quality": 90}, "jpeg"),
                                             ("WEBP", {"lossless": True}, "webp")])
def test_sniff_and_decode_supported(settings: Settings, fmt: str, kw: dict, expected: str) -> None:
    data = encode(cartoon(), fmt, **kw)
    assert sniff_format(data) == expected
    img = decode(data, settings)
    assert img.rgba.shape == (160, 160, 4)
    assert img.rgba.dtype == np.uint8
    assert not img.rgba.flags.writeable  # copia inmutable


def test_lossy_flags(settings: Settings) -> None:
    assert decode(encode(cartoon(), "JPEG"), settings).lossy
    assert decode(encode(cartoon(), "WEBP", quality=80), settings).lossy
    assert not decode(encode(cartoon(), "WEBP", lossless=True), settings).lossy
    assert not decode(encode(cartoon(), "PNG"), settings).lossy


def test_alpha_detected(settings: Settings) -> None:
    assert decode(encode(cartoon(transparent=True)), settings).has_alpha
    assert not decode(encode(cartoon()), settings).has_alpha


@pytest.mark.parametrize("payload", [b"GIF89a" + b"\x00" * 50, b"<svg xmlns='http://www.w3.org/2000/svg'/>",
                                     b"%PDF-1.7", b"hello world"])
def test_rejects_unsupported_content(settings: Settings, payload: bytes) -> None:
    with pytest.raises(InvalidImageError):
        probe(payload, settings)


def test_extension_is_irrelevant_content_decides(settings: Settings) -> None:
    gif = io.BytesIO()
    Image.new("RGB", (20, 20)).save(gif, "GIF")
    with pytest.raises(InvalidImageError):
        probe(gif.getvalue(), settings)  # aunque el usuario lo llame "foto.png"


def test_rejects_truncated(settings: Settings) -> None:
    data = encode(cartoon(), "PNG")
    with pytest.raises(CorruptImageError):
        decode(data[: len(data) // 2], settings)


def test_rejects_empty(settings: Settings) -> None:
    with pytest.raises(InvalidImageError):
        probe(b"", settings)


def test_dimension_and_pixel_limits(tmp_path) -> None:
    small = Settings(data_dir=tmp_path, max_dimension=100)
    with pytest.raises(LimitExceededError):
        probe(encode(cartoon(160)), small)
    few = Settings(data_dir=tmp_path, max_pixels=10_000)
    with pytest.raises(LimitExceededError):
        probe(encode(cartoon(160)), few)
    tiny = Settings(data_dir=tmp_path, min_dimension=200)
    with pytest.raises(LimitExceededError):
        probe(encode(cartoon(160)), tiny)


def test_size_limit(tmp_path) -> None:
    s = Settings(data_dir=tmp_path, max_upload_mb=0.001)
    with pytest.raises(LimitExceededError):
        probe(encode(cartoon(160)), s)


def test_palette_png_is_normalized(settings: Settings) -> None:
    img = Image.fromarray(cartoon()[..., :3]).convert("P", palette=Image.Palette.ADAPTIVE, colors=16)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    out = decode(buf.getvalue(), settings)
    assert out.rgba.shape[2] == 4
