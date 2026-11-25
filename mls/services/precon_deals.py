"""Homepage Pre-Construction Deals rail.

Order (mirrors Featured listings):
1. Team-pinned featured projects (published, not sold out)
2. Near the visitor — search-history cities when present, else IP city
3. When search history includes beds/baths/price (or cities), apply those
   filters to the history fill
4. Newest published fill so the rail never blanks

Browse catalog at ``/precon-properties/`` stays uncached and never implies IP
city filtering; this rail is personalization-only.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from django.core.cache import cache
from django.db.models import F

from mls.models import Content, PreComProperty
from mls.serializers_precon import PreComPropertySerializer
from mls.services.visitor_place import (
    cities_for_request,
    ip_city_from_request,
    parse_cities_param,
)

PRECON_DEALS_DEFAULT_LIMIT = 6
PRECON_DEALS_CACHE_TTL_SECONDS = 300


def _base_qs():
    """Published, still-active inventory (exclude sold out)."""
    return (
        PreComProperty.objects.select_related("content")
        .filter(content__status=Content.PUBLISH)
        .exclude(sales_stage=PreComProperty.SALES_STAGE_SOLD_OUT)
        .prefetch_related("content__attachments")
    )


def _newest_order():
    return (
        F("content__published_at").desc(nulls_last=True),
        "-id",
    )


def _apply_history_filters(qs, params):
    """Beds / baths / price from last-search — cities handled separately."""
    from mls.views_precon import _precon_parse_decimal, _precon_parse_int

    beds_min = _precon_parse_int(params.get("beds_min") or params.get("bedrooms"))
    if beds_min is not None:
        qs = qs.filter(bedrooms__gte=beds_min)

    baths_min = _precon_parse_decimal(params.get("baths_min") or params.get("bathrooms"))
    if baths_min is not None:
        qs = qs.filter(bathrooms__gte=baths_min)

    price_min = _precon_parse_decimal(params.get("price_min"))
    if price_min is not None:
        qs = qs.filter(price__gte=price_min)
    price_max = _precon_parse_decimal(params.get("price_max"))
    if price_max is not None:
        qs = qs.filter(price__lte=price_max)
    return qs


def _cache_digest(params, *, has_search_history: bool, cities: list[str]) -> str:
    from mls.views_precon import PRECON_HISTORY_FILTER_KEYS

    items: list[tuple[str, str]] = [
        ("hist", "1" if has_search_history else "0"),
        ("cities", ",".join(cities)),
    ]
    for key in sorted(PRECON_HISTORY_FILTER_KEYS | {"limit", "fill"}):
        if key in {"limit", "fill", "cities", "city"}:
            continue
        raw = params.get(key) if hasattr(params, "get") else None
        if raw in (None, "", "null", "undefined"):
            continue
        items.append((key, str(raw)))
    return hashlib.md5(json.dumps(items, default=str).encode("utf-8")).hexdigest()


def build_precon_deals(
    request,
    *,
    limit: int = PRECON_DEALS_DEFAULT_LIMIT,
    fill: bool = True,
) -> dict[str, Any]:
    """Return the homepage Pre-Construction Deals payload."""
    from mls.views_precon import (
        _precon_explicit_cities,
        _precon_has_search_history,
        _precon_place_q,
    )

    params = request.query_params
    has_search_history = _precon_has_search_history(params)
    # Near-visitor cities: explicit history cities first, else IP.
    cities = cities_for_request(request)
    history_cities = _precon_explicit_cities(params)

    cache_key = (
        f"precon-deals:v1:{limit}:{int(fill)}:"
        f"{_cache_digest(params, has_search_history=has_search_history, cities=cities)}"
    )
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    newest = _newest_order()
    base = _base_qs()

    pinned = list(
        base.filter(is_featured=True)
        .order_by(F("featured_order").asc(nulls_last=True), *newest)[:limit]
    )
    rows: list[tuple[PreComProperty, str]] = [(p, "pinned") for p in pinned]
    used_ids = {p.id for p in pinned}
    history_count = 0
    local_count = 0
    newest_count = 0

    if fill and len(rows) < limit and has_search_history:
        # Search-history fill: place + beds/baths/price from last search.
        history_qs = base.exclude(id__in=used_ids)
        place_cities = history_cities or cities
        if place_cities:
            history_qs = history_qs.filter(_precon_place_q(place_cities))
        history_qs = _apply_history_filters(history_qs, params)
        history = list(history_qs.order_by(*newest)[: limit - len(rows)])
        rows += [(p, "history") for p in history]
        used_ids.update(p.id for p in history)
        history_count = len(history)
    elif fill and len(rows) < limit and cities:
        # No search-history filters — near visitor via history cities or IP.
        local = list(
            base.exclude(id__in=used_ids)
            .filter(_precon_place_q(cities))
            .order_by(*newest)[: limit - len(rows)]
        )
        rows += [(p, "local") for p in local]
        used_ids.update(p.id for p in local)
        local_count = len(local)

    if fill and len(rows) < limit:
        filler = list(
            base.exclude(id__in=used_ids).order_by(*newest)[: limit - len(rows)]
        )
        rows += [(p, "newest") for p in filler]
        newest_count = len(filler)

    serializer = PreComPropertySerializer(
        [p for p, _ in rows],
        many=True,
        context={"request": request},
    )
    results = [
        {**data, "deal_source": source}
        for data, (_, source) in zip(serializer.data, rows)
    ]

    # Echo cities used for personalization (history or IP), not an empty list
    # when IP alone drove the local stage.
    echoed = history_cities or cities
    if not echoed:
        ip_city = ip_city_from_request(request)
        echoed = [ip_city] if ip_city else []
    # Prefer canonical parse when the query had cities=.
    parsed = parse_cities_param(params.get("cities") or params.get("city"))
    if parsed:
        echoed = parsed

    payload = {
        "count": len(results),
        "pinned_count": len(pinned),
        "history_count": history_count,
        "local_count": local_count,
        "newest_count": newest_count,
        "cities": echoed,
        "has_search_history": has_search_history,
        "results": results,
    }
    cache.set(cache_key, payload, PRECON_DEALS_CACHE_TTL_SECONDS)
    return payload
