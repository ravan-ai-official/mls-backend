"""Nominatim geocode helper when a listing has no lat/lng."""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Optional

import requests
from django.core.cache import cache

if TYPE_CHECKING:
    from mls.models import Property

logger = logging.getLogger(__name__)


def _nominatim_search(query: str) -> tuple[Optional[float], Optional[float]]:
    cleaned = " ".join((query or "").split()).strip()
    if len(cleaned) < 5:
        return None, None

    cache_key = f"valuation-geocode:{cleaned.lower()[:200]}"
    cached = cache.get(cache_key)
    if isinstance(cached, dict):
        try:
            return float(cached["lat"]), float(cached["lng"])
        except (KeyError, TypeError, ValueError):
            pass

    try:
        response = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={
                "q": cleaned,
                "format": "jsonv2",
                "limit": 1,
                "countrycodes": "ca,us",
            },
            headers={
                "User-Agent": os.environ.get(
                    "MAP_GEOCODER_USER_AGENT", "HomeAtlasValuation/1.0"
                ),
                "Accept-Language": "en",
            },
            timeout=8,
        )
        response.raise_for_status()
        rows = response.json()
    except (requests.RequestException, ValueError, TypeError):
        logger.exception("Valuation geocode failed for %r", cleaned)
        return None, None

    if not isinstance(rows, list) or not rows:
        return None, None
    row = rows[0] if isinstance(rows[0], dict) else {}
    try:
        lat = float(row["lat"])
        lng = float(row["lon"])
    except (KeyError, TypeError, ValueError):
        return None, None

    cache.set(cache_key, {"lat": lat, "lng": lng}, 60 * 60 * 24)
    return lat, lng


def geocode_address(
    query: str,
    *,
    city: str | None = None,
    postal_code: str | None = None,
    province: str = "Ontario",
    country: str = "Canada",
) -> tuple[Optional[float], Optional[float]]:
    """Return (lat, lng) for an address, trying postal-aware fallbacks."""
    primary = " ".join((query or "").split()).strip()
    city = (city or "").strip()
    postal = " ".join((postal_code or "").split()).strip().upper()
    province = (province or "").strip()
    country = (country or "").strip()

    candidates: list[str] = []
    if primary:
        candidates.append(primary)
    # Street + city + postal is usually more reliable than a long free-text blob.
    street = primary.split(",")[0].strip() if primary else ""
    compact = ", ".join(
        part for part in (street or primary, city, postal, province, country) if part
    )
    if compact and compact not in candidates:
        candidates.append(compact)
    if street and city:
        short = ", ".join(part for part in (street, city, province, country) if part)
        if short not in candidates:
            candidates.append(short)
    if postal and city:
        postal_only = ", ".join(part for part in (postal, city, province, country) if part)
        if postal_only not in candidates:
            candidates.append(postal_only)

    for candidate in candidates:
        lat, lng = _nominatim_search(candidate)
        if lat is not None and lng is not None:
            return lat, lng
    return None, None


def ensure_property_coordinates(p: "Property") -> tuple[Optional[float], Optional[float]]:
    """Return stored coords, or geocode + persist so detail/schools/valuation share one location.

    Property detail and the schools tab read ``latitude``/``longitude`` from the
    listing payload. Valuation used to geocode on the side, so Network could show
    coords on an estimate request while the property page still said location was
    missing. Filling here keeps those surfaces aligned.
    """
    lat = float(p.latitude) if p.latitude is not None else None
    lng = float(p.longitude) if p.longitude is not None else None
    if lat is not None and lng is not None:
        return lat, lng

    geo_lat, geo_lng = geocode_address(
        p.unparsed_address or "",
        city=p.city or "",
        postal_code=p.postal_code or "",
    )
    if geo_lat is None or geo_lng is None:
        return None, None

    from mls.models import Property

    Property.objects.filter(pk=p.pk).update(latitude=geo_lat, longitude=geo_lng)
    p.latitude = geo_lat
    p.longitude = geo_lng
    return geo_lat, geo_lng
