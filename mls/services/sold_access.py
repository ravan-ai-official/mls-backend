"""HouseSigma-style sold-data access: login required for full sold prices.

Anonymous users may still receive sold stubs (cards/pins) with sensitive
fields redacted and ``sold_locked: true`` so the FE can show a sign-in overlay.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from mls.services.query_helpers import STATUS_GROUPS, _split_csv

SOLD_STATUSES = {s.lower() for s in STATUS_GROUPS.get("sold", set())}

# Fields cleared on list/detail payloads for anonymous sold views.
_REDACT_KEYS = (
    "close_price",
    "list_price",
    "previous_list_price",
    "lease_amount",
    "total_actual_rent",
    "public_remarks",
    "ai_summary_markdown",
    "rooms",
    "washrooms",
    "washroom_info",
    "features",
    "inclusions",
    "inclusions_list",
    "interior_features",
    "interior_features_list",
    "history",
    "living_area_range",
    "original_list_price",
    "tax_annual_amount",
    "association_fee",
)


def viewer_can_view_sold(user) -> bool:
    """Any authenticated account may view full sold data (v1: login-only)."""
    return bool(getattr(user, "is_authenticated", False))


def request_is_sold_query(params: Mapping[str, Any] | None) -> bool:
    """True when the request is asking for sold/closed inventory."""
    if not params:
        return False
    txn = str(params.get("transaction_type") or "").strip().lower()
    if txn == "sold":
        return True
    if params.get("sold_within_days") not in (None, ""):
        return True
    if params.get("sold_days") not in (None, ""):
        return True
    groups = {g.strip().lower() for g in _split_csv(str(params.get("status_group") or ""))}
    if "sold" in groups:
        return True
    for key in ("status", "standard_status"):
        raw = str(params.get(key) or "").strip().lower()
        if raw in SOLD_STATUSES:
            return True
    return False


def is_sold_property(prop_or_status) -> bool:
    """True when a Property instance (or status string) is in the sold group."""
    if prop_or_status is None:
        return False
    if isinstance(prop_or_status, str):
        status = prop_or_status
    else:
        status = getattr(prop_or_status, "standard_status", None) or ""
    return (status or "").strip().lower() in SOLD_STATUSES


def _thumb_only_media(media_value: Any) -> list:
    """Keep at most one media row so locked cards can still show a blurred photo."""
    if not media_value:
        return []
    if isinstance(media_value, list):
        return media_value[:1]
    return media_value


def redact_sold_property_payload(data: dict) -> dict:
    """Return a copy safe for anonymous sold cards/detail."""
    out = deepcopy(data) if isinstance(data, dict) else {}
    for key in _REDACT_KEYS:
        if key in out:
            if key in {"rooms", "washrooms", "washroom_info", "features", "inclusions_list", "interior_features_list", "history"}:
                out[key] = []
            else:
                out[key] = None
    if "media" in out:
        out["media"] = _thumb_only_media(out.get("media"))
    # Price-change / sold signals
    out["price_change_timestamp"] = None
    out["close_date"] = None
    out["sold_locked"] = True
    out["access"] = "login_required"
    return out


def redact_sold_history_payload(payload: dict) -> dict:
    """Strip prices from snapshots/history for anonymous viewers."""
    out = deepcopy(payload) if isinstance(payload, dict) else {}
    snapshots = []
    for row in out.get("snapshots") or []:
        if not isinstance(row, dict):
            continue
        item = dict(row)
        item["list_price"] = None
        snapshots.append(item)
    history = []
    for row in out.get("history") or []:
        if not isinstance(row, dict):
            continue
        item = dict(row)
        item["price"] = None
        history.append(item)
    out["snapshots"] = snapshots
    out["history"] = history
    out["sold_locked"] = True
    out["access"] = "login_required"
    return out


def locked_sold_feed_stub(*, feed: str = "sold") -> dict:
    """Empty locked payload for homepage sold rails / market trends."""
    return {
        "sold_locked": True,
        "sold_login_required": True,
        "access": "login_required",
        "feed": feed,
        "count": 0,
        "results": [],
    }
