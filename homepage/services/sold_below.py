"""Repeat sales that closed below the home's previous sale price.

AMPRE keeps roughly two years of closed history, so a home that sold twice
inside that window can be compared with itself. Addresses are normalised
(case, whitespace, unit markers) before matching; the same property is
recognised only by its full street address including unit, never by street
alone, so neighbouring units are never conflated.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Iterable

from .ampre import parse_date
from .common import base_city, to_float

# Two sales of one home within a few weeks are usually a data correction or a
# collapsed deal re-entered, not a real resale.
MIN_DAYS_BETWEEN_SALES = 60
# Losses beyond this are almost always a unit mismatch or a typo.
MAX_LOSS_PCT = 45.0
# Same guard for gains (Profitable Investments): unrealistic appreciation.
MAX_GAIN_PCT = 45.0
# Profitable Investments: both sales must fall inside this lookback.
GAIN_LOOKBACK_DAYS = 365

_SPACES = re.compile(r"\s+")
_UNIT_WORDS = re.compile(r"\b(unit|suite|apt|apartment|#)\s*", re.IGNORECASE)


def normalise_address(raw: str | None) -> str:
    """'1240 Marlborough Court  704, Oakville, ON L6H 3K7' → '1240 marlborough court 704'.

    Only the street part (before the first comma) is kept: city / postal
    formatting varies between records of the same home.
    """
    street = (raw or "").split(",")[0]
    street = _UNIT_WORDS.sub("", street)
    return _SPACES.sub(" ", street).strip().lower()


@dataclass(frozen=True)
class RepeatSaleLoss:
    listing_key: str
    address: str
    city: str
    property_sub_type: str
    bedrooms: int | None
    bathrooms: int | None
    close_price: float
    close_date: date
    previous_close_price: float
    previous_close_date: date

    @property
    def loss_pct(self) -> float:
        return (self.previous_close_price - self.close_price) / self.previous_close_price * 100


def find_repeat_sale_losses(rows: Iterable[dict[str, Any]]) -> list[RepeatSaleLoss]:
    """Latest sale of each home compared with the one before it."""
    by_address: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        key = normalise_address(row.get("UnparsedAddress"))
        if key and parse_date(row.get("CloseDate")) and to_float(row.get("ClosePrice")):
            by_address[key].append(row)

    losses: list[RepeatSaleLoss] = []
    for sales in by_address.values():
        if len(sales) < 2:
            continue
        sales.sort(key=lambda r: parse_date(r["CloseDate"]))
        latest, previous = sales[-1], sales[-2]
        latest_date, previous_date = parse_date(latest["CloseDate"]), parse_date(previous["CloseDate"])
        if (latest_date - previous_date) < timedelta(days=MIN_DAYS_BETWEEN_SALES):
            continue
        latest_price, previous_price = to_float(latest["ClosePrice"]), to_float(previous["ClosePrice"])
        if latest_price >= previous_price:
            continue
        loss = RepeatSaleLoss(
            listing_key=latest["ListingKey"],
            address=(latest.get("UnparsedAddress") or "").split(",")[0].strip(),
            city=base_city(latest.get("City")),
            property_sub_type=latest.get("PropertySubType") or "",
            bedrooms=latest.get("BedroomsTotal"),
            bathrooms=latest.get("BathroomsTotalInteger"),
            close_price=latest_price,
            close_date=latest_date,
            previous_close_price=previous_price,
            previous_close_date=previous_date,
        )
        if loss.loss_pct <= MAX_LOSS_PCT:
            losses.append(loss)
    losses.sort(key=lambda loss: loss.close_date, reverse=True)
    return losses


@dataclass(frozen=True)
class RepeatSaleGain:
    listing_key: str
    address: str
    city: str
    property_sub_type: str
    bedrooms: int | None
    bathrooms: int | None
    close_price: float
    close_date: date
    previous_close_price: float
    previous_close_date: date

    @property
    def gain_pct(self) -> float:
        return (self.close_price - self.previous_close_price) / self.previous_close_price * 100

    @property
    def gain_amount(self) -> float:
        return self.close_price - self.previous_close_price


def find_repeat_sale_gains(
    rows: Iterable[dict[str, Any]],
    *,
    as_of: date | None = None,
) -> list[RepeatSaleGain]:
    """Homes sold 2+ times in the last 12 months where the latest price is higher.

    Skips too-quick resales and unrealistically large gains (same odd-case
    filters as repeat-sale losses, inverted for appreciation).
    """
    today = as_of or date.today()
    window_start = today - timedelta(days=GAIN_LOOKBACK_DAYS)

    by_address: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        key = normalise_address(row.get("UnparsedAddress"))
        close_date = parse_date(row.get("CloseDate"))
        if key and close_date and to_float(row.get("ClosePrice")):
            by_address[key].append(row)

    gains: list[RepeatSaleGain] = []
    for sales in by_address.values():
        recent = [
            row
            for row in sales
            if (parse_date(row["CloseDate"]) or date.min) >= window_start
        ]
        if len(recent) < 2:
            continue
        recent.sort(key=lambda r: parse_date(r["CloseDate"]))
        latest, previous = recent[-1], recent[-2]
        latest_date = parse_date(latest["CloseDate"])
        previous_date = parse_date(previous["CloseDate"])
        if (latest_date - previous_date) < timedelta(days=MIN_DAYS_BETWEEN_SALES):
            continue
        latest_price = to_float(latest["ClosePrice"])
        previous_price = to_float(previous["ClosePrice"])
        if latest_price <= previous_price:
            continue
        gain = RepeatSaleGain(
            listing_key=latest["ListingKey"],
            address=(latest.get("UnparsedAddress") or "").split(",")[0].strip(),
            city=base_city(latest.get("City")),
            property_sub_type=latest.get("PropertySubType") or "",
            bedrooms=latest.get("BedroomsTotal"),
            bathrooms=latest.get("BathroomsTotalInteger"),
            close_price=latest_price,
            close_date=latest_date,
            previous_close_price=previous_price,
            previous_close_date=previous_date,
        )
        if gain.gain_pct <= MAX_GAIN_PCT:
            gains.append(gain)
    gains.sort(key=lambda g: (g.gain_pct, g.close_date), reverse=True)
    return gains
