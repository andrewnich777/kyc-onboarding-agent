"""
Investigation planner — builds agent + utility execution plan based on client type and risk.
"""

import re
from datetime import datetime
from models import (
    IndividualClient, BusinessClient, ClientType,
    InvestigationPlan, RiskAssessment,
)
from utilities.risk_scoring import calculate_individual_risk_score, calculate_business_risk_score
from utilities.regulation_detector import detect_applicable_regulations


def _generate_client_id(client) -> str:
    """Generate a filesystem-safe client ID."""
    if isinstance(client, IndividualClient):
        name = client.full_name
    else:
        name = client.legal_name
    
    # Convert to filesystem-safe string
    safe = re.sub(r'[^a-z0-9]+', '_', name.lower()).strip('_')
    return safe


def build_investigation_plan(client) -> InvestigationPlan:
    """
    Build the investigation plan for a client.
    Determines which agents and utilities to run.
    """
    client_type = client.client_type
    client_id = _generate_client_id(client)
    
    # Calculate preliminary risk
    if isinstance(client, IndividualClient):
        risk = calculate_individual_risk_score(client)
    else:
        risk = calculate_business_risk_score(client)
    
    # Detect applicable regulations
    regulations = detect_applicable_regulations(client)
    
    # Determine agents to run
    agents = []
    utilities = []
    ubo_cascade = False
    ubo_names = []
    
    if client_type == ClientType.INDIVIDUAL:
        # Individual path
        agents = [
            "IndividualSanctions",
            "PEPDetection",
            "IndividualAdverseMedia",
            "JurisdictionRisk",
        ]
        utilities = [
            "id_verification",
            "suitability",
            "individual_fatca_crs",
            "edd_requirements",
            "compliance_actions",
        ]
    
    elif client_type == ClientType.BUSINESS:
        # Business path
        agents = [
            "EntityVerification",
            "EntitySanctions",
            "BusinessAdverseMedia",
            "JurisdictionRisk",
        ]
        utilities = [
            "id_verification",
            "suitability",
            "entity_fatca_crs",
            "business_risk_assessment",
            "edd_requirements",
            "compliance_actions",
        ]
        
        # UBO cascade — screen each beneficial owner individually
        if isinstance(client, BusinessClient) and client.beneficial_owners:
            ubo_cascade = True
            ubo_names = [ubo.full_name for ubo in client.beneficial_owners]
    
    # Add OFAC-specific checks if applicable
    if "OFAC" in regulations and "EntitySanctions" not in agents:
        pass  # OFAC checks are built into sanctions agents
    
    return InvestigationPlan(
        client_type=client_type,
        client_id=client_id,
        agents_to_run=agents,
        utilities_to_run=utilities,
        ubo_cascade_needed=ubo_cascade,
        ubo_names=ubo_names,
        applicable_regulations=regulations,
        preliminary_risk=risk,
    )
