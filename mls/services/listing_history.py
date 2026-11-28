"""Build Buy/Sell History intervals from PropertySnapshot points.

Raw snapshots fire on sync noise; the UI needs coalesced listing periods:
Date Start / Date End / Price / Event / Listing ID.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any


_STATUS_EVENT = {
    "active": "For Sale",
    "pending": "Pending",
    "closed": "Sold",
    "sold": "Sold",
    "expired": "Expired",
    "withdrawn": "Withdrawn",
    "canceled": "Cancelled",
    "cancelled": "Cancelled",
    "terminated": "Terminated",
}


def event_label(standard_status: str | None) -> str:
    key = (standard_status or "").strip().lower()
    return _STATUS_EVENT.get(key) or ((standard_status or "").strip() or "Unknown")


def _price_key(value: Any) -> str | None:
    if value is None:
        return None
    try:
        return str(Decimal(str(value)))
    except Exception:
        return str(value)


def _ts(value: Any):
    return value


def coalesce_snapshots(
    snapshots: list[Any],
    *,
    listing_id: str | None = None,
    listing_key: str | None = None,
) -> list[dict[str, Any]]:
    """
    Collapse consecutive same price+status snapshots into listing periods.

    ``snapshots`` should be oldest-first. Each item needs list_price,
    standard_status, and preferably source_modification_timestamp (else created_at).
    """
    periods: list[dict[str, Any]] = []
    for snap in snapshots:
        price = getattr(snap, "list_price", None)
        if isinstance(snap, dict):
            price = snap.get("list_price")
            status = (snap.get("standard_status") or "").strip()
            start = snap.get("source_modification_timestamp") or snap.get("created_at")
        else:
            status = (getattr(snap, "standard_status", None) or "").strip()
            start = getattr(snap, "source_modification_timestamp", None) or getattr(
                snap, "created_at", None
            )

        if periods:
            last = periods[-1]
            if last["_price_key"] == _price_key(price) and last["_status"] == status:
                # Same listing period — keep earliest start, ignore MT-only noise.
                continue

        periods.append(
            {
                "_price_key": _price_key(price),
                "_status": status,
                "date_start": _ts(start),
                "date_end": None,
                "price": float(price) if price is not None else None,
                "event": event_label(status),
                "standard_status": status or None,
                "listing_id": listing_id,
                "listing_key": listing_key,
            }
        )

    for i, period in enumerate(periods):
        if i + 1 < len(periods):
            period["date_end"] = periods[i + 1]["date_start"]
        # else leave open (still listed) or unknown end

    # Newest first for the property-detail table.
    out: list[dict[str, Any]] = []
    for period in reversed(periods):
        out.append(
            {
                "date_start": period["date_start"],
                "date_end": period["date_end"],
                "price": period["price"],
                "event": period["event"],
                "standard_status": period["standard_status"],
                "listing_id": period["listing_id"],
                "listing_key": period["listing_key"],
            }
        )
    return out


def build_listing_history(listing_key: str, *, limit: int = 100) -> dict[str, Any]:
    from mls.models import Property, PropertySnapshot

    key = (listing_key or "").strip()
    prop = (
        Property.objects.filter(listing_key=key).only("listing_id", "listing_key").first()
        if key
        else None
    )
    mls_id = (getattr(prop, "listing_id", None) or "").strip() or None

    qs = list(
        PropertySnapshot.objects.filter(listing_key=key)
        .order_by("created_at", "id")[:limit]
    )
    history = coalesce_snapshots(
        qs,
        listing_id=mls_id,
        listing_key=key or None,
    )
    return {
        "listing_key": key,
        "listing_id": mls_id,
        "history": history,
    }
