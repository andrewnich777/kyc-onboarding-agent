"""
Shared UBO field extraction helpers for brief generators.
"""


def extract_ubo_field(ubo_data: dict, screening_type: str, field: str, default: str = "Pending") -> str:
    """Extract a human-readable status from UBO screening data.

    Args:
        ubo_data: Dict with keys like "sanctions", "pep", "adverse_media",
                  each mapping to a result dict.
        screening_type: Which screening result to look up (e.g. "sanctions").
        field: The field within the screening result (e.g. "disposition").
        default: Value to return when data is missing.
    """
    if not ubo_data:
        return default
    result = ubo_data.get(screening_type)
    if not result or not isinstance(result, dict):
        return default
    value = result.get(field, default)
    if value in ("CLEAR", "NOT_PEP"):
        return "Clear"
    return str(value).replace("_", " ").title()
