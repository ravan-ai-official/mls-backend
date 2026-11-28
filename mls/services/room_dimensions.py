"""Format MLS room measurements for the property detail API.

TRREB/DDF RoomLength/RoomWidth are usually metres. The frontend was treating
those decimals as feet/inches (5.4 → 5'4"), which made rooms look tiny versus
REALM and other TREB consumers that correctly label metres.

Property detail exposes both metric and imperial strings so the UI can toggle.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

_M_TO_FT = Decimal("3.28084")
_FT_TO_M = Decimal("0.3048")


def _num(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _is_metric(units: str | None) -> bool:
    text = (units or "").strip().lower()
    if not text:
        # TREB room sizes are almost always metres when units are blank.
        return True
    return text.startswith("m") or "metre" in text or "meter" in text


def _feet_inches(value: float) -> str:
    total_inches = int(round(value * 12))
    feet, inches = divmod(total_inches, 12)
    if inches:
        return f"{feet}'{inches}\""
    return f"{feet}'"


def _metric_pair(length_m: float, width_m: float) -> str:
    return f"{length_m:g} × {width_m:g} m"


def _imperial_pair(length_ft: float, width_ft: float) -> str:
    return f"{_feet_inches(length_ft)} × {_feet_inches(width_ft)}"


def format_room_dimensions(
    length: Any,
    width: Any,
    units: str | None = None,
    room_dimensions: str | None = None,
) -> str | None:
    """Default display string (metric for TREB when units blank/metric)."""
    dims = dual_room_dimensions(length, width, units, room_dimensions)
    return dims["dimensions_display"]


def meters_to_feet_display(length: Any, width: Any) -> str | None:
    """Optional imperial pair when the feed is metric (for dual-unit UIs)."""
    length_f = _num(length)
    width_f = _num(width)
    if length_f is None or width_f is None:
        return None
    return _imperial_pair(
        float(Decimal(str(length_f)) * _M_TO_FT),
        float(Decimal(str(width_f)) * _M_TO_FT),
    )


def dual_room_dimensions(
    length: Any,
    width: Any,
    units: str | None = None,
    room_dimensions: str | None = None,
) -> dict[str, str | None]:
    """
    Return both unit systems for a metric/imperial toggle.

    - dimensions_m / dimensions_ft: always filled when length×width exist
    - dimensions_display: default (metric for TREB; imperial only if feed is feet)
    """
    length_f = _num(length)
    width_f = _num(width)
    metric = _is_metric(units)
    feed_text = (room_dimensions or "").strip() or None

    dimensions_m = None
    dimensions_ft = None

    if length_f is not None and width_f is not None:
        if metric:
            dimensions_m = _metric_pair(length_f, width_f)
            dimensions_ft = _imperial_pair(
                float(Decimal(str(length_f)) * _M_TO_FT),
                float(Decimal(str(width_f)) * _M_TO_FT),
            )
        else:
            dimensions_ft = _imperial_pair(length_f, width_f)
            dimensions_m = _metric_pair(
                float(Decimal(str(length_f)) * _FT_TO_M),
                float(Decimal(str(width_f)) * _FT_TO_M),
            )

    # Prefer computed metric as default for TREB; keep feed text only when it
    # already looks unit-aware, otherwise fall back to computed.
    if metric:
        dimensions_display = dimensions_m or feed_text
    else:
        dimensions_display = dimensions_ft or feed_text

    return {
        "dimensions_display": dimensions_display,
        "dimensions_m": dimensions_m or feed_text,
        "dimensions_ft": dimensions_ft,
        "is_metric_source": metric,
    }
