"""Pre-construction photo/PDF uploads (Django admin + studio).

Assets are stored in Cloudinary. The configured flag used to incorrectly
track GCS bucket presence, which blocked every admin upload when only
Cloudinary credentials were set.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from django.conf import settings

logger = logging.getLogger(__name__)

ATTACHMENT_URL_MAX_LENGTH = 2000


def _first_nonempty(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def cloudinary_credentials_present() -> bool:
    """True when Cloudinary can accept an upload (env or settings overlay)."""
    if _first_nonempty(os.environ.get("CLOUDINARY_URL")):
        return True
    cloud = getattr(settings, "CLOUDINARY", None) or {}
    storage = getattr(settings, "CLOUDINARY_STORAGE", None) or {}
    name = _first_nonempty(
        os.environ.get("CLOUDINARY_CLOUD_NAME"),
        cloud.get("CLOUD_NAME") if isinstance(cloud, dict) else "",
        storage.get("CLOUD_NAME") if isinstance(storage, dict) else "",
    )
    key = _first_nonempty(
        os.environ.get("CLOUDINARY_API_KEY"),
        cloud.get("API_KEY") if isinstance(cloud, dict) else "",
        storage.get("API_KEY") if isinstance(storage, dict) else "",
    )
    secret = _first_nonempty(
        os.environ.get("CLOUDINARY_API_SECRET"),
        cloud.get("API_SECRET") if isinstance(cloud, dict) else "",
        storage.get("API_SECRET") if isinstance(storage, dict) else "",
    )
    return bool(name and key and secret)


def precon_asset_storage_configured() -> bool:
    """Runtime check — also true after console Cloudinary overlay is applied."""
    if cloudinary_credentials_present():
        return True
    return bool(getattr(settings, "PRECON_ASSET_STORAGE_CONFIGURED", False))


def _ensure_cloudinary_config() -> None:
    """Push env/settings credentials into the Cloudinary SDK before upload."""
    import cloudinary

    # Prefer CLOUDINARY_URL when present (SDK reads it from the environment).
    if _first_nonempty(os.environ.get("CLOUDINARY_URL")):
        cloudinary.config(secure=True)
        return
    cloud = getattr(settings, "CLOUDINARY", None) or {}
    storage = getattr(settings, "CLOUDINARY_STORAGE", None) or {}
    name = _first_nonempty(
        os.environ.get("CLOUDINARY_CLOUD_NAME"),
        cloud.get("CLOUD_NAME") if isinstance(cloud, dict) else "",
        storage.get("CLOUD_NAME") if isinstance(storage, dict) else "",
    )
    key = _first_nonempty(
        os.environ.get("CLOUDINARY_API_KEY"),
        cloud.get("API_KEY") if isinstance(cloud, dict) else "",
        storage.get("API_KEY") if isinstance(storage, dict) else "",
    )
    secret = _first_nonempty(
        os.environ.get("CLOUDINARY_API_SECRET"),
        cloud.get("API_SECRET") if isinstance(cloud, dict) else "",
        storage.get("API_SECRET") if isinstance(storage, dict) else "",
    )
    if name and key and secret:
        cloudinary.config(cloud_name=name, api_key=key, api_secret=secret, secure=True)


def upload_precon_asset(upload, *, folder: str) -> str:
    """Upload ``upload`` to Cloudinary and return its HTTPS delivery URL."""
    from cloudinary import uploader as cloudinary_uploader
    from cloudinary.exceptions import Error as CloudinaryError

    if not precon_asset_storage_configured():
        raise RuntimeError("precon_asset_storage_not_configured")

    _ensure_cloudinary_config()

    if hasattr(upload, "seek"):
        try:
            upload.seek(0)
        except (OSError, ValueError):
            pass

    try:
        uploaded = cloudinary_uploader.upload(
            upload,
            resource_type="auto",
            folder=folder,
            use_filename=True,
            unique_filename=True,
        )
    except CloudinaryError:
        logger.exception("Pre-con Cloudinary upload failed folder=%s", folder)
        raise

    url = str(uploaded.get("secure_url") or "").strip()
    if not url.startswith("https://"):
        raise CloudinaryError("Cloudinary did not return a secure delivery URL.")
    if len(url) > ATTACHMENT_URL_MAX_LENGTH:
        raise CloudinaryError("Cloudinary delivery URL is too long to store.")
    return url
