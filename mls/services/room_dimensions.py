"""Format MLS room measurements for the property detail API.

TRREB/DDF RoomLength/RoomWidth are usually metres. The frontend was treating
those decimals as feet/inches (5.4 → 5'4"), which made rooms look tiny versus
REALM and other TREB consumers that correctly label metres.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any


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


def format_room_dimensions(
    length: Any,
    width: Any,
    units: str | None = None,
    room_dimensions: str | None = None,
) -> str | None:
    """Human-readable size: prefer feed text, else length × width with units."""
    text = (room_dimensions or "").strip()
    if text:
        return text
    length_f = _num(length)
    width_f = _num(width)
    if length_f is None or width_f is None:
        return None
    if _is_metric(units):
        return f"{length_f:g} × {width_f:g} m"
    return f"{_feet_inches(length_f)} × {_feet_inches(width_f)}"


def meters_to_feet_display(length: Any, width: Any) -> str | None:
    """Optional imperial pair when the feed is metric (for dual-unit UIs)."""
    length_f = _num(length)
    width_f = _num(width)
    if length_f is None or width_f is None:
        return None
    ft = Decimal("3.28084")
    return (
        f"{_feet_inches(float(Decimal(str(length_f)) * ft))} × "
        f"{_feet_inches(float(Decimal(str(width_f)) * ft))}"
    )
