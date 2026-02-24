"""
Compliance Officer Brief Generator — backward compatibility wrapper.
Delegates to generate_aml_operations_brief which replaces it.
"""

from generators.aml_operations_brief import generate_aml_operations_brief as generate_compliance_brief

__all__ = ["generate_compliance_brief"]
