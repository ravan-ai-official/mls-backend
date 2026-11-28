"""
On-demand refresh of a single listing from AMPRE.

Used when the rolling DDF cache is stale (Celery not running, or a listing
left the Active-only DDF feed without a status write). Soft-fails so detail
pages still render from the local row.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal, InvalidOperation

from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from mls.models import Property
from mls.services.ampre_client import AmpreClientError, fetch_property_page

logger = logging.getLogger(__name__)

# Active rows older than this are considered stale enough to re-check AMPRE.
STALE_ACTIVE_HOURS = 36

# Core fields known to work on AMPRE Property $select.
SELECT_FIELDS_CORE = [
    "ListingKey",
    "ListingId",
    "StandardStatus",
    "ListPrice",
    "OriginalListPrice",
    "ClosePrice",
    "CloseDate",
    "PreviousListPrice",
    "PriceChangeTimestamp",
    "UnparsedAddress",
    "City",
    "CityRegion",
    "StateOrProvince",
    "PostalCode",
    "PropertySubType",
    "StructureType",
    "PropertyAttachedYN",
    "BedroomsTotal",
    "BedroomsAboveGrade",
    "BedroomsBelowGrade",
    "BathroomsTotalInteger",
    # LivingArea* / BuildingFeatures / CommonInterest are not in AMPRE Property.
    "AboveGradeFinishedArea",
    "BuildingAreaTotal",
    "YearBuilt",
    "ApproximateAge",
    "TaxAnnualAmount",
    "AssociationFee",
    "AssociationFeeFrequency",
    "AssociationFeeIncludes",
    "ParkingTotal",
    "ParkingFeatures",
    "ListOfficeName",
    "ListOfficeKey",
    "ArchitecturalStyle",
    "ConstructionMaterials",
    "ExteriorFeatures",
    "Appliances",
    "OtherEquipment",
    "Inclusions",
    "InteriorFeatures",
    "Features",
    "PropertyFeatures",
    "BathroomsPartial",
    "GarageYN",
    "FamilyRoomYN",
    "DirectionFaces",
    "RoomsTotal",
    "OpenParkingSpaces",
    "CrossStreet",
    "TaxLegalDescription",
    "Possession",
    "LaundryFeatures",
    "Locker",
    "LinkYN",
    "Roof",
    "FoundationDetails",
    "PublicRemarks",
    "OriginalEntryTimestamp",
    "ModificationTimestamp",
    "TransactionType",
]

# Extended garage / kitchen / stories fields — retry without these on AMPRE 400.
SELECT_FIELDS_EXTENDED = [
    *SELECT_FIELDS_CORE,
    "GarageSpaces",
    "CoveredSpaces",
    "GarageType",
    "NumberOfKitchens",
    "KitchensTotalInteger",
    "Stories",
    "StoriesTotal",
]

# Back-compat alias used by tests / callers.
SELECT_FIELDS = SELECT_FIELDS_EXTENDED


def _dec(value):
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _int(value):
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _dt(value):
    """Parse AMPRE timestamps as timezone-aware UTC.

    Offsetless strings are treated as UTC. Returning naive datetimes
    triggers Django RuntimeWarnings under USE_TZ and pollutes
    PropertySnapshot.source_modification_timestamp writes.
    """
    if not value:
        return None
    if isinstance(value, str):
        parsed = parse_datetime(value.replace("Z", "+00:00"))
    elif isinstance(value, datetime):
        parsed = value
    else:
        return None
    if parsed is None:
        return None
    if timezone.is_naive(parsed):
        return timezone.make_aware(parsed, dt_timezone.utc)
    return parsed.astimezone(dt_timezone.utc)


def _date(value):
    if not value:
        return None
    if isinstance(value, str):
        return parse_date(value[:10])
    return value


def _str_or_join(value, limit=2000):
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        text = ", ".join(str(item) for item in value if item not in (None, ""))
    else:
        text = str(value)
    text = text.strip()
    return text[:limit] if text else None


def _year_from_age(raw):
    age = _int(raw)
    if age is None or age < 0 or age >= 300:
        return None
    return timezone.now().year - age


def map_ampre_row(row: dict) -> dict:
    living = _dec(row.get("LivingArea"))
    living_min = _dec(row.get("LivingAreaMinimum"))
    living_max = _dec(row.get("LivingAreaMaximum"))
    if living is None:
        living = living_min or living_max

    structure = row.get("StructureType")
    if isinstance(structure, list):
        structure = structure[0] if structure else None

    garage_type = row.get("GarageType")
    if isinstance(garage_type, list):
        garage_type = ", ".join(str(x) for x in garage_type if x) or None

    return {
        "listing_id": (_str_or_join(row.get("ListingId") or row.get("ListingKey"), 50)),
        "standard_status": (_str_or_join(row.get("StandardStatus"), 50) or "Active"),
        "list_price": _dec(row.get("ListPrice")),
        "original_list_price": _dec(row.get("OriginalListPrice")),
        "close_price": _dec(row.get("ClosePrice")),
        "close_date": _date(row.get("CloseDate")),
        "previous_list_price": _dec(row.get("PreviousListPrice")),
        "price_change_timestamp": _dt(row.get("PriceChangeTimestamp")),
        "unparsed_address": _str_or_join(row.get("UnparsedAddress")),
        "city": _str_or_join(row.get("City")),
        "city_region": _str_or_join(row.get("CityRegion")),
        "state_or_province": _str_or_join(row.get("StateOrProvince"), 100) or "Ontario",
        "postal_code": _str_or_join(row.get("PostalCode"), 20),
        "property_sub_type": _str_or_join(row.get("PropertySubType"), 100),
        "structure_type": _str_or_join(structure, 100),
        "property_attached_yn": row.get("PropertyAttachedYN"),
        "bedrooms_total": _int(row.get("BedroomsTotal")),
        "bedrooms_above_grade": _int(row.get("BedroomsAboveGrade")),
        "bedrooms_below_grade": _int(row.get("BedroomsBelowGrade")),
        "bathrooms_total_integer": _int(row.get("BathroomsTotalInteger")),
        "bathrooms_partial": _int(row.get("BathroomsPartial")),
        "appliances": _str_or_join(row.get("Appliances")),
        "other_equipment": _str_or_join(row.get("OtherEquipment")),
        "inclusions": _str_or_join(row.get("Inclusions")),
        "interior_features": _str_or_join(
            row.get("InteriorFeatures") or row.get("Features")
        ),
        "living_area": living,
        "living_area_minimum": living_min,
        "living_area_maximum": living_max,
        "above_grade_finished_area": _dec(row.get("AboveGradeFinishedArea")),
        "building_area_total": _dec(row.get("BuildingAreaTotal")),
        "year_built": _int(row.get("YearBuilt")) or _year_from_age(row.get("ApproximateAge")),
        "tax_annual_amount": _dec(row.get("TaxAnnualAmount")),
        "association_fee": _dec(row.get("AssociationFee")),
        "association_fee_frequency": _str_or_join(row.get("AssociationFeeFrequency"), 50),
        "association_fee_includes": _str_or_join(row.get("AssociationFeeIncludes")),
        "parking_total": _int(row.get("ParkingTotal")),
        "parking_features": _str_or_join(row.get("ParkingFeatures")),
        "garages": _int(
            row.get("GarageSpaces")
            if row.get("GarageSpaces") is not None
            else row.get("CoveredSpaces")
        ),
        "garage_size": _str_or_join(garage_type),
        "garage_yn": (
            True
            if str(row.get("GarageYN") or "").strip().lower() in {"y", "yes", "true", "1"}
            else (
                False
                if str(row.get("GarageYN") or "").strip().lower() in {"n", "no", "false", "0"}
                else None
            )
        ),
        "open_parking_spaces": _int(
            row.get("OpenParkingSpaces")
            if row.get("OpenParkingSpaces") is not None
            else row.get("ParkingSpaces")
        ),
        "kitchens": _int(
            row.get("NumberOfKitchens")
            if row.get("NumberOfKitchens") is not None
            else row.get("KitchensTotalInteger")
        ),
        "rooms_total": _int(row.get("RoomsTotal")),
        "family_room_yn": (
            True
            if str(row.get("FamilyRoomYN") or "").strip().lower() in {"y", "yes", "true", "1"}
            else (
                False
                if str(row.get("FamilyRoomYN") or "").strip().lower() in {"n", "no", "false", "0"}
                else None
            )
        ),
        "direction_faces": _str_or_join(row.get("DirectionFaces"), 50),
        "cross_street": _str_or_join(row.get("CrossStreet")),
        "tax_legal_description": _str_or_join(row.get("TaxLegalDescription")),
        "possession": _str_or_join(row.get("Possession") or row.get("PossessionRemarks")),
        "laundry_features": _str_or_join(row.get("LaundryFeatures")),
        "locker": _str_or_join(row.get("Locker"), 120),
        "link_yn": (
            True
            if str(row.get("LinkYN") or "").strip().lower() in {"y", "yes", "true", "1"}
            else (
                False
                if str(row.get("LinkYN") or "").strip().lower() in {"n", "no", "false", "0"}
                else None
            )
        ),
        "property_features": _str_or_join(
            row.get("PropertyFeatures") or row.get("Features")
        ),
        "stories": _int(row.get("Stories") or row.get("StoriesTotal")),
        "architectural_style": _str_or_join(row.get("ArchitecturalStyle")),
        "construction_materials": _str_or_join(row.get("ConstructionMaterials")),
        "exterior_features": _str_or_join(row.get("ExteriorFeatures")),
        "roof": _str_or_join(row.get("Roof")),
        "foundation_details": _str_or_join(row.get("FoundationDetails")),
        "list_office_name": _str_or_join(row.get("ListOfficeName"), 2000),
        "list_office_key": _str_or_join(row.get("ListOfficeKey")),
        "building_features": _str_or_join(row.get("BuildingFeatures")),
        "common_interest": _str_or_join(row.get("CommonInterest"), 100),
        "public_remarks": row.get("PublicRemarks") or "",
        "original_entry_timestamp": _dt(row.get("OriginalEntryTimestamp")),
        "modification_timestamp": _dt(row.get("ModificationTimestamp")) or timezone.now(),
        "status_change_timestamp": _dt(row.get("ModificationTimestamp")) or timezone.now(),
    }


def listing_is_stale_active(prop: Property, *, hours: int = STALE_ACTIVE_HOURS) -> bool:
    status = (prop.standard_status or "").strip().lower()
    if status != "active":
        return False
    mod = prop.modification_timestamp
    if mod is None:
        return True
    return timezone.now() - mod >= timedelta(hours=hours)


def refresh_listing_from_ampre(prop: Property) -> Property | None:
    """
    Re-fetch one listing from AMPRE by ListingId / ListingKey and apply updates.

    Returns the saved property, or None when AMPRE has no row / is unavailable.
    When AMPRE has no match for a stale Active row, mark it Expired so the
    site stops advertising it as For Sale.
    """
    keys = []
    for raw in (prop.listing_id, prop.listing_key):
        value = (raw or "").strip()
        if value and value not in keys:
            keys.append(value)
    if not keys:
        return None

    clauses = []
    for key in keys:
        safe = key.replace("'", "''")
        clauses.append(f"ListingId eq '{safe}'")
        clauses.append(f"ListingKey eq '{safe}'")
    filter_expression = " or ".join(clauses)

    fetch_kwargs = dict(
        filter_expression=filter_expression,
        top=5,
        max_rows=5,
    )
    try:
        try:
            rows = fetch_property_page(
                select_fields=SELECT_FIELDS_EXTENDED,
                **fetch_kwargs,
            )
        except AmpreClientError as exc:
            msg = str(exc).lower()
            if "400" not in msg and "bad request" not in msg and "select" not in msg:
                raise
            logger.warning(
                "AMPRE refresh extended $select rejected for %s; retrying core: %s",
                prop.listing_key,
                exc,
            )
            rows = fetch_property_page(
                select_fields=SELECT_FIELDS_CORE,
                **fetch_kwargs,
            )
    except AmpreClientError as exc:
        logger.warning("AMPRE refresh skipped for %s: %s", prop.listing_key, exc)
        return None

    if not rows:
        # Gone from AMPRE too — treat as off-market rather than forever-Active.
        if listing_is_stale_active(prop):
            prop.standard_status = "Expired"
            prop.status_change_timestamp = timezone.now()
            prop.save(
                update_fields=["standard_status", "status_change_timestamp"]
            )
            return prop
        return None

    row = rows[0]
    defaults = map_ampre_row(row)
    old_price = prop.list_price
    new_price = defaults.get("list_price")
    if (
        old_price is not None
        and new_price is not None
        and old_price != new_price
        and not defaults.get("previous_list_price")
    ):
        defaults["previous_list_price"] = old_price
        defaults["price_change_timestamp"] = (
            defaults.get("modification_timestamp") or timezone.now()
        )

    changed = []
    for field, value in defaults.items():
        if value is None:
            continue
        if getattr(prop, field, None) != value:
            setattr(prop, field, value)
            changed.append(field)
    if changed:
        prop.save(update_fields=changed)
    return prop


def maybe_refresh_stale_listing(prop: Property) -> Property:
    """Refresh when Active and stale; otherwise return the row unchanged."""
    if not listing_is_stale_active(prop):
        return prop
    return refresh_listing_from_ampre(prop) or prop
