"""
REALTOR.ca-aligned search + advanced filter schema for HomeAtlas.

Primary bar (always visible) + Filters panel (advanced). No Buy/Rent/Sold
page tabs — transaction type is a control inside search, like realtor.ca.
Reference: https://www.realtor.ca/map
"""

from __future__ import annotations

from typing import Any


# Sale price presets (CAD) — mirrors realtor.ca Min/Max Price lists.
_SALE_PRICE_STEPS = [
    25_000,
    50_000,
    75_000,
    100_000,
    125_000,
    150_000,
    175_000,
    200_000,
    225_000,
    250_000,
    275_000,
    300_000,
    325_000,
    350_000,
    375_000,
    400_000,
    425_000,
    450_000,
    475_000,
    500_000,
    550_000,
    600_000,
    650_000,
    700_000,
    750_000,
    800_000,
    850_000,
    900_000,
    950_000,
    1_000_000,
    1_100_000,
    1_200_000,
    1_300_000,
    1_400_000,
    1_500_000,
    1_600_000,
    1_700_000,
    1_800_000,
    1_900_000,
    2_000_000,
    2_500_000,
    3_000_000,
    4_000_000,
    5_000_000,
]

# Rent presets (CAD / month).
_RENT_PRICE_STEPS = [
    100,
    200,
    300,
    400,
    500,
    600,
    700,
    800,
    900,
    1_000,
    1_200,
    1_400,
    1_600,
    1_800,
    2_000,
    2_500,
    3_000,
    3_500,
    4_000,
    4_500,
    5_000,
    6_000,
    7_000,
    8_000,
    9_000,
    10_000,
]

_BED_BATH = [0, 1, 2, 3, 4, 5, 6]

_SQFT_STEPS = [
    500,
    750,
    1000,
    1250,
    1500,
    1750,
    2000,
    2250,
    2500,
    2750,
    3000,
    3500,
    4000,
    5000,
    7500,
]

_LAND_STEPS = [0, 25, 50, 75, 100, 150, 200, 250, 500, 1000]  # feet frontage / area band

_STOREYS = [1, 1.5, 2, 2.5, 3, 4]

_YEAR_BUILT = [
    2025,
    2020,
    2015,
    2010,
    2000,
    1990,
    1980,
    1970,
    1960,
    1950,
    1940,
    1920,
    1900,
]

_TAX_YEARLY = [
    1_000,
    2_000,
    3_000,
    4_000,
    5_000,
    6_000,
    7_500,
    10_000,
    15_000,
    20_000,
    30_000,
]

_MAINTENANCE_MONTHLY = [
    100,
    200,
    300,
    400,
    500,
    600,
    700,
    800,
    900,
    1_000,
    1_250,
    1_500,
    2_000,
    2_500,
    3_000,
]

_SOLD_WITHIN = [
    {"value": 7, "label": "7 days"},
    {"value": 14, "label": "14 days"},
    {"value": 30, "label": "30 days"},
    {"value": 90, "label": "90 days"},
    {"value": 180, "label": "6 months"},
    {"value": 365, "label": "1 year"},
]

# Building types → property_sub_type / structure filters (TREB-oriented).
BUILDING_TYPES = [
    {"value": "House", "label": "House", "params": {"property_type": "Detached,Semi-Detached"}},
    {"value": "Row / Townhouse", "label": "Row / Townhouse", "params": {"property_type": "Att/Row/Twnhouse,Townhouse,Townhome"}},
    {"value": "Apartment", "label": "Apartment", "params": {"property_type": "Condo Apt,Condo Apartment,Apartment"}},
    {"value": "Duplex", "label": "Duplex", "params": {"property_type": "Duplex"}},
    {"value": "Triplex", "label": "Triplex", "params": {"property_type": "Triplex"}},
    {"value": "Fourplex", "label": "Fourplex", "params": {"property_type": "Fourplex,Multiplex"}},
    {"value": "Mobile Home", "label": "Mobile / Manufactured", "params": {"keywords": "Mobile"}},
    {"value": "Other", "label": "Other", "params": {}},
]

PROPERTY_TYPE_GROUPS = [
    {"value": "", "label": "Any"},
    {"value": "residential", "label": "Residential"},
    {"value": "condo", "label": "Condo/Strata"},
    {"value": "vacant_land", "label": "Vacant Land"},
    {"value": "recreational", "label": "Recreational"},
    {"value": "multi_family", "label": "Multi Family"},
    {"value": "agriculture", "label": "Agriculture"},
    {"value": "parking", "label": "Parking"},
]

OWNERSHIP_OPTIONS = [
    {"value": "", "label": "Any"},
    {"value": "Freehold", "label": "Freehold"},
    {"value": "Condominium", "label": "Condominium"},
    {"value": "Leasehold", "label": "Leasehold"},
    {"value": "Timeshare", "label": "Timeshare"},
]

TRANSACTION_OPTIONS = [
    {"value": "sale", "label": "For sale", "params": {"transaction_type": "sale", "status_group": "active"}},
    {"value": "rent", "label": "For rent", "params": {"transaction_type": "rent", "status_group": "active"}},
    {"value": "sold", "label": "Sold", "params": {"transaction_type": "sale", "status_group": "sold"}},
]

SORT_OPTIONS = [
    {"value": "newest", "label": "Newest"},
    {"value": "price_asc", "label": "Price (low to high)"},
    {"value": "price_desc", "label": "Price (high to low)"},
    {"value": "beds_desc", "label": "Bedrooms"},
    {"value": "sqft_desc", "label": "Square footage"},
]


def _num_options(steps: list, *, include_any: bool = True) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if include_any:
        out.append({"value": None, "label": "Any"})
    for n in steps:
        out.append({"value": n, "label": f"{n}+" if include_any else str(n)})
    return out


def _price_options(steps: list[int], *, prefix: str = "$") -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = [{"value": None, "label": "No min"}]
    for n in steps:
        label = f"{prefix}{n:,}"
        out.append({"value": n, "label": label})
    out.append({"value": None, "label": "No max", "role": "max_sentinel"})
    return out


def get_search_filters_schema() -> dict[str, Any]:
    """Payload for FE to render primary bar + Filters panel (no status tabs)."""
    return {
        "version": 1,
        "reference": "https://www.realtor.ca/map",
        "ui": {
            "keep_existing_layout": True,
            "eliminate_tabs": True,
            "notes": (
                "Keep the current search layout. Only remove Buy/Rent tabs and "
                "the secondary For Sale / For Lease / Sold (etc.) tab strip. "
                "Replace them with dropdowns: Transaction Type, Min Price, "
                "Max Price, Beds, Baths. Put remaining filters in the existing "
                "Filters sheet; sheet fields change by transaction_type "
                "(sale vs rent vs sold), like REALTOR.ca."
            ),
            "remove": [
                "Buy tab",
                "Rent tab",
                "For Sale tab",
                "For Lease / For Rent secondary tab",
                "Sold / status tab strip under search",
            ],
            "primary_controls": [
                "transaction_type (dropdown)",
                "price_min (dropdown)",
                "price_max (dropdown)",
                "bedrooms (dropdown)",
                "bathrooms (dropdown)",
            ],
        },
        "primary_bar": [
            {
                "id": "search",
                "type": "search",
                "param": "search",
                "placeholder": "City, Neighbourhood, Address or MLS® number",
            },
            {
                "id": "transaction_type",
                "type": "select",
                "param": "transaction_type",
                "label": "Transaction Type",
                "options": TRANSACTION_OPTIONS,
                "default": "sale",
            },
            {
                "id": "price_min",
                "type": "select",
                "param": "price_min",
                "label": "Min Price",
                "options_key": "price",
                "options_by_transaction": {
                    "sale": "price_sale",
                    "sold": "price_sale",
                    "rent": "price_rent",
                },
            },
            {
                "id": "price_max",
                "type": "select",
                "param": "price_max",
                "label": "Max Price",
                "options_key": "price",
                "options_by_transaction": {
                    "sale": "price_sale",
                    "sold": "price_sale",
                    "rent": "price_rent",
                },
            },
            {
                "id": "bedrooms",
                "type": "select",
                "param": "bedrooms",
                "label": "Beds",
                "options": _num_options(_BED_BATH),
            },
            {
                "id": "bathrooms",
                "type": "select",
                "param": "bathrooms",
                "label": "Baths",
                "options": _num_options(_BED_BATH),
            },
            {"id": "search_submit", "type": "button", "label": "Search"},
            {"id": "filters_open", "type": "button", "label": "Filters"},
            {"id": "save_search", "type": "button", "label": "Save Search"},
        ],
        "sheet_visibility_by_transaction": {
            "sale": {
                "show": [
                    "property_type_group",
                    "building_area_min",
                    "building_area_max",
                    "lot_size_min",
                    "lot_size_max",
                    "listed_since",
                    "structure_type",
                    "stories_min",
                    "stories_max",
                    "common_interest",
                    "association_fee_min",
                    "association_fee_max",
                    "tax_min",
                    "tax_max",
                    "year_built_min",
                    "year_built_max",
                    "open_house_only",
                    "keywords",
                ],
                "hide": ["sold_within_days"],
                "price_options": "price_sale",
                "price_label": "Price",
            },
            "rent": {
                "show": [
                    "property_type_group",
                    "building_area_min",
                    "building_area_max",
                    "listed_since",
                    "structure_type",
                    "stories_min",
                    "stories_max",
                    "common_interest",
                    "association_fee_min",
                    "association_fee_max",
                    "year_built_min",
                    "year_built_max",
                    "open_house_only",
                    "keywords",
                ],
                "hide": ["sold_within_days", "tax_min", "tax_max", "lot_size_min", "lot_size_max"],
                "price_options": "price_rent",
                "price_label": "Rent",
            },
            "sold": {
                "show": [
                    "sold_within_days",
                    "property_type_group",
                    "building_area_min",
                    "building_area_max",
                    "lot_size_min",
                    "lot_size_max",
                    "structure_type",
                    "stories_min",
                    "stories_max",
                    "common_interest",
                    "tax_min",
                    "tax_max",
                    "year_built_min",
                    "year_built_max",
                    "keywords",
                ],
                "hide": ["open_house_only", "listed_since"],
                "price_options": "price_sale",
                "price_label": "Sold Price",
            },
        },
        "advanced_panel": {
            "title": "Filters",
            "market_toggle": [
                {"value": "residential", "label": "Residential"},
                {"value": "commercial", "label": "Commercial"},
            ],
            "sections": [
                {
                    "id": "location",
                    "fields": [
                        {
                            "id": "search",
                            "type": "search",
                            "param": "search",
                            "placeholder": "City, Neighbourhood, Address or MLS® number",
                        }
                    ],
                },
                {
                    "id": "transaction",
                    "label": "Transaction Type",
                    "fields": [
                        {
                            "id": "transaction_type",
                            "type": "radio",
                            "param": "transaction_type",
                            "options": TRANSACTION_OPTIONS,
                        },
                        {
                            "id": "sold_within_days",
                            "type": "select",
                            "param": "sold_within_days",
                            "label": "Sold in Last",
                            "visible_when": {"transaction_type": "sold"},
                            "options": [{"value": None, "label": "Any"}, *_SOLD_WITHIN],
                        },
                    ],
                },
                {
                    "id": "property",
                    "fields": [
                        {
                            "id": "property_type_group",
                            "type": "select",
                            "param": "property_type_group",
                            "label": "Property Type",
                            "options": PROPERTY_TYPE_GROUPS,
                        },
                        {
                            "id": "price_min",
                            "type": "select",
                            "param": "price_min",
                            "label": "Price",
                            "options_key": "price",
                        },
                        {
                            "id": "price_max",
                            "type": "select",
                            "param": "price_max",
                            "label": "Price",
                            "options_key": "price",
                        },
                        {
                            "id": "bedrooms",
                            "type": "select",
                            "param": "bedrooms",
                            "label": "Beds",
                            "options": _num_options(_BED_BATH),
                        },
                        {
                            "id": "bathrooms",
                            "type": "select",
                            "param": "bathrooms",
                            "label": "Baths",
                            "options": _num_options(_BED_BATH),
                        },
                        {
                            "id": "building_area_min",
                            "type": "select",
                            "param": "building_area_min",
                            "label": "Square Footage",
                            "options": [{"value": None, "label": "No min"}]
                            + [{"value": n, "label": f"{n:,}+"} for n in _SQFT_STEPS],
                        },
                        {
                            "id": "building_area_max",
                            "type": "select",
                            "param": "building_area_max",
                            "label": "Square Footage",
                            "options": [{"value": None, "label": "No max"}]
                            + [{"value": n, "label": f"{n:,}"} for n in _SQFT_STEPS],
                        },
                        {
                            "id": "lot_size_min",
                            "type": "select",
                            "param": "lot_size_min",
                            "label": "Land Size",
                            "options": [{"value": None, "label": "No min"}]
                            + [{"value": n, "label": str(n)} for n in _LAND_STEPS],
                        },
                        {
                            "id": "lot_size_max",
                            "type": "select",
                            "param": "lot_size_max",
                            "label": "Land Size",
                            "options": [{"value": None, "label": "No max"}]
                            + [{"value": n, "label": str(n)} for n in _LAND_STEPS],
                        },
                        {
                            "id": "listed_since",
                            "type": "date",
                            "param": "listed_since",
                            "label": "Listed Since",
                            "placeholder": "mm/dd/yyyy",
                        },
                        {
                            "id": "structure_type",
                            "type": "select",
                            "param": "building_type",
                            "label": "Building Type",
                            "options": [{"value": "", "label": "Any"}, *BUILDING_TYPES],
                        },
                        {
                            "id": "stories_min",
                            "type": "select",
                            "param": "stories_min",
                            "label": "Storeys",
                            "options": [{"value": None, "label": "No min"}]
                            + [{"value": n, "label": str(n)} for n in _STOREYS],
                        },
                        {
                            "id": "stories_max",
                            "type": "select",
                            "param": "stories_max",
                            "label": "Storeys",
                            "options": [{"value": None, "label": "No max"}]
                            + [{"value": n, "label": str(n)} for n in _STOREYS],
                        },
                        {
                            "id": "common_interest",
                            "type": "select",
                            "param": "common_interest",
                            "label": "Ownership/Title",
                            "options": OWNERSHIP_OPTIONS,
                        },
                        {
                            "id": "association_fee_min",
                            "type": "select",
                            "param": "association_fee_min",
                            "label": "Maintenance Fees - Monthly",
                            "options": [{"value": None, "label": "No min"}]
                            + [{"value": n, "label": f"${n:,}"} for n in _MAINTENANCE_MONTHLY],
                        },
                        {
                            "id": "association_fee_max",
                            "type": "select",
                            "param": "association_fee_max",
                            "label": "Maintenance Fees - Monthly",
                            "options": [{"value": None, "label": "No max"}]
                            + [{"value": n, "label": f"${n:,}"} for n in _MAINTENANCE_MONTHLY],
                        },
                        {
                            "id": "tax_min",
                            "type": "select",
                            "param": "tax_min",
                            "label": "Property Tax - Yearly",
                            "options": [{"value": None, "label": "No min"}]
                            + [{"value": n, "label": f"${n:,}"} for n in _TAX_YEARLY],
                        },
                        {
                            "id": "tax_max",
                            "type": "select",
                            "param": "tax_max",
                            "label": "Property Tax - Yearly",
                            "options": [{"value": None, "label": "No max"}]
                            + [{"value": n, "label": f"${n:,}"} for n in _TAX_YEARLY],
                        },
                        {
                            "id": "year_built_min",
                            "type": "select",
                            "param": "year_built_min",
                            "label": "Year Built",
                            "options": [{"value": None, "label": "No min"}]
                            + [{"value": n, "label": str(n)} for n in _YEAR_BUILT],
                        },
                        {
                            "id": "year_built_max",
                            "type": "select",
                            "param": "year_built_max",
                            "label": "Year Built",
                            "options": [{"value": None, "label": "No max"}]
                            + [{"value": n, "label": str(n)} for n in _YEAR_BUILT],
                        },
                        {
                            "id": "open_house_only",
                            "type": "checkbox",
                            "param": "open_house",
                            "label": "Open Houses Only",
                            "true_value": "1",
                        },
                        {
                            "id": "keywords",
                            "type": "text",
                            "param": "keywords",
                            "label": "Keywords",
                            "placeholder": "Waterfront, Garage, Pool…",
                        },
                    ],
                },
            ],
            "actions": [
                {"id": "reset", "label": "Reset"},
                {"id": "search", "label": "Search"},
            ],
        },
        "option_sets": {
            "price_sale": _price_options(_SALE_PRICE_STEPS),
            "price_rent": _price_options(_RENT_PRICE_STEPS),
        },
        "sort": SORT_OPTIONS,
        "query_param_map": {
            "transaction_type": "sale | rent | sold",
            "status_group": "active | sold (set automatically from transaction)",
            "price_min": "number",
            "price_max": "number",
            "bedrooms": "min beds",
            "bathrooms": "min baths",
            "building_area_min": "sqft min (effective living area)",
            "building_area_max": "sqft max",
            "lot_size_min": "number",
            "lot_size_max": "number",
            "listed_since": "YYYY-MM-DD",
            "property_type_group": "residential|condo|vacant_land|recreational|multi_family|agriculture|parking",
            "building_type": "House|Row / Townhouse|Apartment|…",
            "property_type": "CSV of PropertySubType",
            "stories_min": "number",
            "stories_max": "number",
            "common_interest": "Freehold|Condominium|…",
            "association_fee_min": "monthly condo fee",
            "association_fee_max": "monthly condo fee",
            "tax_min": "yearly tax",
            "tax_max": "yearly tax",
            "year_built_min": "year",
            "year_built_max": "year",
            "open_house": "1",
            "keywords": "CSV or free text",
            "sold_within_days": "7|14|30|90|180|365",
            "search": "location / MLS text",
            "sort": "newest|price_asc|price_desc|…",
        },
    }
