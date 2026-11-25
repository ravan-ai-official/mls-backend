"""Shared OData filters for DDF / AMPRE listing catalogue sync."""

# CREA DDF has no PropertyType field — type is carried on PropertySubType
# (observed values include Single Family, Industrial, Agriculture, Retail…).
# Sync everything except agriculture / industrial.
# Note: 'Farm' is NOT a valid DDF PropertySubType enum constant (HTTP 400).
EXCLUDE_AG_INDUSTRY_CLAUSE = (
    "PropertySubType ne 'Agriculture' "
    "and PropertySubType ne 'Industrial'"
)


def and_filters(*parts: str | None) -> str | None:
    """Join non-empty OData filter fragments with ``and``."""
    bits = [p.strip() for p in parts if p and str(p).strip()]
    if not bits:
        return None
    return " and ".join(bits)
