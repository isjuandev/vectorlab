"""Validación del tipo real del archivo, decodificación y normalización a RGBA sRGB."""

from __future__ import annotations

import io
import warnings as pywarnings
from dataclasses import dataclass, field

import numpy as np
from PIL import Image, ImageCms, ImageOps, UnidentifiedImageError

from app.config import Settings
from app.errors import CorruptImageError, InvalidImageError, LimitExceededError

FORMATS = {"png": "image/png", "jpeg": "image/jpeg", "webp": "image/webp"}
EXTENSIONS = {"png": "png", "jpeg": "jpg", "webp": "webp"}


def sniff_format(data: bytes) -> str:
    """Determina el formato por la firma binaria, nunca por la extensión."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    raise InvalidImageError(
        "Formato no admitido: solo se aceptan PNG, JPEG y WebP (verificado por contenido, no por extensión).")


@dataclass
class DecodedImage:
    rgba: np.ndarray  # HxWx4 uint8, solo lectura
    format: str
    width: int
    height: int
    has_alpha: bool
    lossy: bool
    notes: list[str] = field(default_factory=list)


def check_size(data: bytes, settings: Settings) -> None:
    if len(data) == 0:
        raise InvalidImageError("El archivo está vacío.")
    if len(data) > settings.max_upload_bytes:
        raise LimitExceededError(
            f"El archivo supera el límite de {settings.max_upload_mb:g} MB.",
            {"bytes": len(data), "max_bytes": settings.max_upload_bytes})


def check_dimensions(width: int, height: int, settings: Settings) -> None:
    if width < settings.min_dimension or height < settings.min_dimension:
        raise LimitExceededError(
            f"Imagen demasiado pequeña ({width}x{height}); mínimo {settings.min_dimension}px por lado.")
    if max(width, height) > settings.max_dimension:
        raise LimitExceededError(
            f"Dimensión {max(width, height)}px supera el máximo de {settings.max_dimension}px.",
            {"width": width, "height": height})
    if width * height > settings.max_pixels:
        raise LimitExceededError(
            f"La imagen tiene {width * height:,} píxeles; el máximo es {settings.max_pixels:,}.",
            {"pixels": width * height})


def probe(data: bytes, settings: Settings) -> tuple[str, int, int]:
    """Validación rápida (firma + cabecera) usada antes de aceptar un trabajo."""
    check_size(data, settings)
    fmt = sniff_format(data)
    try:
        with Image.open(io.BytesIO(data)) as img:
            if (img.format or "").lower() != fmt:
                raise InvalidImageError("La firma del archivo no coincide con su contenido decodificado.")
            width, height = img.size
    except (UnidentifiedImageError, OSError, SyntaxError) as exc:
        raise CorruptImageError("No se pudo leer la cabecera de la imagen.") from exc
    check_dimensions(width, height, settings)
    return fmt, width, height


def _to_srgb(img: Image.Image, notes: list[str]) -> Image.Image:
    icc = img.info.get("icc_profile")
    if not icc:
        return img
    try:
        src = ImageCms.ImageCmsProfile(io.BytesIO(icc))
        dst = ImageCms.createProfile("sRGB")
        mode = "RGBA" if img.mode == "RGBA" else "RGB"
        img = ImageCms.profileToProfile(img.convert(mode), src, dst, outputMode=mode)
        notes.append("Perfil ICC embebido convertido a sRGB.")
    except (ImageCms.PyCMSError, OSError, ValueError):
        notes.append("Perfil ICC embebido no válido: se ignora y se asume sRGB.")
    return img


def decode(data: bytes, settings: Settings) -> DecodedImage:
    fmt, width, height = probe(data, settings)
    notes: list[str] = []
    try:
        with pywarnings.catch_warnings():
            pywarnings.simplefilter("error", Image.DecompressionBombWarning)
            Image.MAX_IMAGE_PIXELS = settings.max_pixels
            img = Image.open(io.BytesIO(data))
            if getattr(img, "n_frames", 1) > 1:
                notes.append(f"Imagen animada ({img.n_frames} fotogramas): solo se vectoriza el primero.")
            img.seek(0)
            img.load()
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise LimitExceededError("La imagen excede el límite de píxeles descomprimidos.") from exc
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as exc:
        raise CorruptImageError("La imagen está dañada o truncada y no puede decodificarse.") from exc

    transposed = ImageOps.exif_transpose(img)
    if transposed is not img and transposed.size != img.size:
        notes.append("Orientación EXIF aplicada.")
    img = transposed

    if img.mode in ("P", "PA"):
        img = img.convert("RGBA")
    elif img.mode in ("LA",):
        img = img.convert("RGBA")
    elif img.mode in ("CMYK", "YCbCr", "L", "1", "I", "I;16", "F"):
        img = img.convert("RGB")
    img = _to_srgb(img, notes)
    rgba = np.array(img.convert("RGBA"), dtype=np.uint8)
    has_alpha = bool(rgba[..., 3].min() < 255)
    rgba.setflags(write=False)
    lossy = fmt == "jpeg" or (fmt == "webp" and _webp_is_lossy(data))
    return DecodedImage(rgba=rgba, format=fmt, width=rgba.shape[1], height=rgba.shape[0],
                        has_alpha=has_alpha, lossy=lossy, notes=notes)


def _webp_is_lossy(data: bytes) -> bool:
    # Recorre los chunks RIFF: "VP8 " = con pérdida, "VP8L" = sin pérdida (VP8X es solo cabecera extendida).
    pos = 12
    while pos + 8 <= len(data):
        tag = data[pos:pos + 4]
        size = int.from_bytes(data[pos + 4:pos + 8], "little")
        if tag == b"VP8 ":
            return True
        if tag == b"VP8L":
            return False
        pos += 8 + size + (size & 1)
    return True
