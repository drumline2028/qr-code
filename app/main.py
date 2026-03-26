import io
import os
from datetime import datetime, timezone
from typing import Literal
from urllib.request import urlopen

import qrcode
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from google.cloud import storage
from PIL import Image, ImageColor
from pydantic import BaseModel, Field, HttpUrl

# Main FastApi Application
app = FastAPI(title="m100api", version="1.0.0")

BUCKET_NAME = os.getenv("GCS_BUCKET", "m100boosters")
QR_PREFIX = os.getenv("GCS_QR_PREFIX", "media/qrcodes")
DEFAULT_QR_URL = "https://www.beltonbandboosters.org"
DEFAULT_LOGO_URL = os.getenv("QR_LOGO_URL")
STYLE2_LOGO_GSURI = "gs://m100boosters/media/logos/m100_qr_logo_v1_black.png"
CORS_ALLOW_ORIGINS = os.getenv(
    "CORS_ALLOW_ORIGINS",
    "http://localhost:3000,http://127.0.0.1:3000",
)

ALLOWED_ORIGINS = [origin.strip() for origin in CORS_ALLOW_ORIGINS.split(",") if origin.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class QRCreateRequest(BaseModel):
    url: HttpUrl
    style: Literal[1, 2] = 1
    box_size: int = Field(default=10, ge=1, le=50)
    border: int = Field(default=4, ge=0, le=20)
    error_correction: Literal["L", "M", "Q", "H"] = "M"
    fill_color: str = "black"
    back_color: str = "white"
    fit: bool = True
    output_size: int = Field(default=1200, ge=256, le=4096)
    logo_url: HttpUrl | None = None
    logo_scale: float = Field(default=0.25, ge=0.1, le=0.4)


ERROR_CORRECTION_MAP = {
    "L": qrcode.constants.ERROR_CORRECT_L,
    "M": qrcode.constants.ERROR_CORRECT_M,
    "Q": qrcode.constants.ERROR_CORRECT_Q,
    "H": qrcode.constants.ERROR_CORRECT_H,
}


def _validate_color(value: str, field_name: str) -> None:
    try:
        ImageColor.getrgb(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid {field_name}: {value}. Use named colors or hex like #00ff00.",
        ) from exc


def _download_gs_uri(gs_uri: str) -> bytes:
    if not gs_uri.startswith("gs://"):
        raise HTTPException(status_code=422, detail=f"Invalid gs uri: {gs_uri}")

    without_scheme = gs_uri[5:]
    if "/" not in without_scheme:
        raise HTTPException(status_code=422, detail=f"Invalid gs uri: {gs_uri}")

    bucket_name, object_name = without_scheme.split("/", 1)
    client = storage.Client()
    blob = client.bucket(bucket_name).blob(object_name)
    return blob.download_as_bytes()


def _load_logo_image(logo_location: str | None) -> Image.Image | None:
    if not logo_location:
        return None

    logo_location = logo_location.strip()
    if not logo_location:
        return None

    try:
        if logo_location.startswith("gs://"):
            logo_bytes = _download_gs_uri(logo_location)
        else:
            with urlopen(logo_location, timeout=10) as response:
                logo_bytes = response.read()
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Unable to load logo: {logo_location}") from exc

    try:
        return Image.open(io.BytesIO(logo_bytes)).convert("RGBA")
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Invalid image logo: {logo_location}") from exc


def simple_qrcode(payload: QRCreateRequest) -> tuple[Image.Image, str, str | None, float | None, bool]:
    _validate_color(payload.fill_color, "fill_color")
    _validate_color(payload.back_color, "back_color")

    qr = qrcode.QRCode(
        version=1,
        error_correction=ERROR_CORRECTION_MAP[payload.error_correction],
        box_size=payload.box_size,
        border=payload.border,
    )
    qr.add_data(str(payload.url))
    qr.make(fit=payload.fit)

    image = qr.make_image(
        fill_color=payload.fill_color,
        back_color=payload.back_color,
    ).convert("RGBA")

    # Force a consistent higher-resolution output image.
    image = image.resize((payload.output_size, payload.output_size), resample=Image.Resampling.NEAREST)
    return image, payload.error_correction, None, None, False


def qr_code_with_logo(payload: QRCreateRequest) -> tuple[Image.Image, str, str, float, bool]:
    _validate_color(payload.fill_color, "fill_color")
    _validate_color(payload.back_color, "back_color")

    logo_location = STYLE2_LOGO_GSURI
    logo_scale = payload.logo_scale
    effective_error_correction = "H"

    qr = qrcode.QRCode(
        version=1,
        error_correction=ERROR_CORRECTION_MAP[effective_error_correction],
        box_size=payload.box_size,
        border=payload.border,
    )
    qr.add_data(str(payload.url))
    qr.make(fit=payload.fit)

    image = qr.make_image(
        fill_color=payload.fill_color,
        back_color=payload.back_color,
    ).convert("RGBA")
    image = image.resize((payload.output_size, payload.output_size), resample=Image.Resampling.NEAREST)

    logo_image = _load_logo_image(logo_location)
    logo_applied = False
    if logo_image is not None:
        logo_target_size = max(1, int(payload.output_size * logo_scale))
        logo_image.thumbnail((logo_target_size, logo_target_size), resample=Image.Resampling.LANCZOS)

        # White backing improves contrast and scannability for centered logos.
        pad = max(2, int(logo_target_size * 0.12))

        bg_size = (logo_image.width + (pad * 2), logo_image.height + (pad * 2))
        logo_bg = Image.new("RGBA", bg_size, (255, 255, 255, 255))
        bg_x = (payload.output_size - logo_bg.width) // 2
        bg_y = (payload.output_size - logo_bg.height) // 2
        image.alpha_composite(logo_bg, (bg_x, bg_y))

        logo_x = (payload.output_size - logo_image.width) // 2
        logo_y = (payload.output_size - logo_image.height) // 2
        image.alpha_composite(logo_image, (logo_x, logo_y))
        logo_applied = True

    if not logo_applied:
        raise HTTPException(status_code=500, detail="Style 2 requires centered logo, but logo could not be applied.")

    return image, effective_error_correction, logo_location, logo_scale, logo_applied


def _create_and_upload_qr(payload: QRCreateRequest) -> dict:
    if payload.style == 2:
        image, effective_error_correction, logo_location, logo_scale, logo_applied = qr_code_with_logo(payload)
    else:
        image, effective_error_correction, logo_location, logo_scale, logo_applied = simple_qrcode(payload)

    image_bytes = io.BytesIO()
    image.save(image_bytes, format="PNG")
    image_bytes.seek(0)

    filename = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ.png")
    object_name = f"{QR_PREFIX.rstrip('/')}/{filename}"

    client = storage.Client()
    bucket = client.bucket(BUCKET_NAME)
    blob = bucket.blob(object_name)

    blob.upload_from_file(image_bytes, content_type="image/png")

    # Works when object ACLs are enabled and caller has ACL permission.
    # If Uniform Bucket-Level Access is enabled, this call can fail and the
    # public URL should be managed at bucket/IAM level instead.
    try:
        blob.make_public()
    except Exception:
        pass

    public_url = f"https://storage.googleapis.com/{BUCKET_NAME}/{object_name}"

    return {
        "ok": True,
        "source_url": str(payload.url),
        "gcs_uri": f"gs://{BUCKET_NAME}/{object_name}",
        "qrcode_url": public_url,
        "download_url": public_url,
        "public_url": public_url,
        "logo_applied": logo_applied,
        "settings": {
            "style": payload.style,
            "box_size": payload.box_size,
            "border": payload.border,
            "error_correction": effective_error_correction,
            "fill_color": payload.fill_color,
            "back_color": payload.back_color,
            "fit": payload.fit,
            "output_size": payload.output_size,
            "logo_url": logo_location,
            "logo_scale": logo_scale,
        },
    }


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.get("/status")
def status() -> dict:
    return {
        "service": "m100api",
        "status": "running",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "bucket": BUCKET_NAME,
        "prefix": QR_PREFIX,
        "revision": os.getenv("K_REVISION"),
        "service_name": os.getenv("K_SERVICE"),
    }


@app.post("/qrcreate")
def qrcreate(payload: QRCreateRequest) -> dict:
    try:
        return _create_and_upload_qr(payload)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"QR creation failed: {exc}") from exc


@app.get("/qrcreate")
def qrcreate_default(style: Literal[1, 2] = Query(default=1)) -> dict:
    try:
        default_payload = QRCreateRequest(url=DEFAULT_QR_URL, style=style)
        result = _create_and_upload_qr(default_payload)
        result["example"] = True
        return result
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"QR creation failed: {exc}") from exc
