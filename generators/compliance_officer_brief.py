"""
Compliance Officer Brief Generator — backward compatibility wrapper.
Delegates to generate_aml_operations_brief which replaces it.
"""

import warnings

from generators.aml_operations_brief import generate_aml_operations_brief


def generate_compliance_brief(**kwargs):
    """Deprecated: use generate_aml_operations_brief instead."""
    warnings.warn(
        "generate_compliance_brief is deprecated, use generate_aml_operations_brief instead",
        DeprecationWarning,
        stacklevel=2,
    )
    return generate_aml_operations_brief(**kwargs)


__all__ = ["generate_compliance_brief"]
