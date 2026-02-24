"""
Checkpoint mixin for KYC Pipeline.

Handles checkpoint save/load and investigation serialization/deserialization.
"""

import json
from pathlib import Path

from logger import get_logger
from models import (
    InvestigationResults,
    SanctionsResult, PEPClassification, AdverseMediaResult,
    EntityVerification, JurisdictionRiskResult,
)

logger = get_logger(__name__)


class CheckpointMixin:
    """Checkpoint persistence for pipeline state."""

    def _get_checkpoint_path(self, client_id: str) -> Path:
        return self.output_dir / client_id / "checkpoint.json"

    def _load_checkpoint(self, client_id: str) -> dict:
        if not self.resume:
            return {}
        cp_path = self._get_checkpoint_path(client_id)
        if cp_path.exists():
            try:
                data = json.loads(cp_path.read_text(encoding="utf-8"))
                self.log(f"  [green]Loaded checkpoint (stage {data.get('completed_stage', 0)})[/green]")
                return data
            except Exception as e:
                self.log(f"  [yellow]Could not load checkpoint: {e}[/yellow]")
        return {}

    def _save_checkpoint(self, client_id: str, data: dict):
        cp_path = self._get_checkpoint_path(client_id)
        cp_path.parent.mkdir(parents=True, exist_ok=True)
        cp_path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")

    def _serialize_investigation(self, investigation: InvestigationResults) -> dict:
        """Serialize investigation results for checkpoint."""
        data = {}
        for field_name in [
            "individual_sanctions", "pep_classification", "individual_adverse_media",
            "entity_verification", "entity_sanctions", "business_adverse_media",
            "jurisdiction_risk",
        ]:
            val = getattr(investigation, field_name, None)
            data[field_name] = val.model_dump() if val else None

        for field_name in [
            "id_verification", "suitability_assessment", "fatca_crs",
            "edd_requirements", "compliance_actions", "business_risk_assessment",
            "document_requirements",
        ]:
            data[field_name] = getattr(investigation, field_name, None)

        data["ubo_screening"] = investigation.ubo_screening
        return data

    def _deserialize_investigation(self, data: dict) -> InvestigationResults:
        """Deserialize investigation results from checkpoint."""
        results = InvestigationResults()

        model_map = {
            "individual_sanctions": SanctionsResult,
            "pep_classification": PEPClassification,
            "individual_adverse_media": AdverseMediaResult,
            "entity_verification": EntityVerification,
            "entity_sanctions": SanctionsResult,
            "business_adverse_media": AdverseMediaResult,
            "jurisdiction_risk": JurisdictionRiskResult,
        }

        for field_name, model_class in model_map.items():
            val = data.get(field_name)
            if val:
                try:
                    setattr(results, field_name, model_class(**val))
                except Exception as e:
                    logger.warning(f"Could not deserialize {field_name}: {e}")

        for field_name in [
            "id_verification", "suitability_assessment", "fatca_crs",
            "edd_requirements", "compliance_actions", "business_risk_assessment",
            "document_requirements",
        ]:
            setattr(results, field_name, data.get(field_name))

        results.ubo_screening = data.get("ubo_screening", {})
        return results
