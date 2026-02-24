"""
Investigation mixin for KYC Pipeline.

Handles Stage 2: AI agent execution, UBO cascade, and utility dispatch.
"""

import importlib

from logger import get_logger
from models import (
    BusinessClient, InvestigationPlan, InvestigationResults,
)
from dispatch import AGENT_DISPATCH, AGENT_RESULT_FIELD, UTILITY_DISPATCH, UTILITY_RESULT_FIELD

logger = get_logger(__name__)


class InvestigationMixin:
    """Stage 2 investigation execution."""

    async def _run_investigation(self, client, plan: InvestigationPlan) -> InvestigationResults:
        """Stage 2: Run AI agents and deterministic utilities."""
        results = InvestigationResults()

        # Run AI agents sequentially (no rate limit pauses — Claude Max)
        for agent_name in plan.agents_to_run:
            self.log(f"  Running {agent_name}...")
            try:
                result = await self._run_agent(agent_name, client, plan)
                self._store_agent_result(results, agent_name, result)
                self.log(f"  [green]{agent_name} complete[/green]")
            except Exception as e:
                self.log(f"  [red]{agent_name} error: {e}[/red]")
                logger.exception(f"Agent {agent_name} failed")

        # UBO cascade for business clients
        if plan.ubo_cascade_needed and isinstance(client, BusinessClient):
            self.log(f"\n  [bold cyan]UBO Cascade ({len(plan.ubo_names)} owners)[/bold cyan]")
            for ubo in client.beneficial_owners:
                self.log(f"  Screening UBO: {ubo.full_name} ({ubo.ownership_percentage}%)")
                ubo_results = await self._screen_ubo(ubo)
                results.ubo_screening[ubo.full_name] = ubo_results

        # Run deterministic utilities (pass partial results for EDD/compliance)
        self.log(f"\n  [bold cyan]Deterministic Utilities[/bold cyan]")
        for util_name in plan.utilities_to_run:
            self.log(f"  Running {util_name}...")
            try:
                result = await self._run_utility(util_name, client, plan, results)
                self._store_utility_result(results, util_name, result)
                self.log(f"  [green]{util_name} complete[/green]")
            except Exception as e:
                self.log(f"  [red]{util_name} error: {e}[/red]")
                logger.exception(f"Utility {util_name} failed")

        return results

    async def _run_agent(self, agent_name: str, client, plan: InvestigationPlan):
        """Dispatch to the correct agent via dispatch table."""
        if agent_name not in AGENT_DISPATCH:
            raise ValueError(f"Unknown agent: {agent_name}")
        agent_attr, kwargs_fn = AGENT_DISPATCH[agent_name]
        agent = getattr(self, agent_attr)
        kwargs = kwargs_fn(client, plan)
        # JurisdictionRisk uses a positional arg, not kwargs
        positional = kwargs.pop("_positional_arg", None)
        if positional is not None:
            return await agent.research(positional)
        return await agent.research(**kwargs)

    async def _screen_ubo(self, ubo) -> dict:
        """Screen a single beneficial owner through individual pipeline."""
        ubo_results = {}

        try:
            sanctions = await self.individual_sanctions_agent.research(
                full_name=ubo.full_name,
                date_of_birth=ubo.date_of_birth,
                citizenship=ubo.citizenship,
                context=f"UBO ({ubo.ownership_percentage}% owner)",
            )
            ubo_results["sanctions"] = sanctions.model_dump() if sanctions else None
            # Add evidence to store
            if sanctions and sanctions.evidence_records:
                for er in sanctions.evidence_records:
                    er.entity_context = f"UBO ({ubo.ownership_percentage}% owner)"
                    self.evidence_store.append(er.model_dump())
        except Exception as e:
            logger.error(f"UBO sanctions screening failed for {ubo.full_name}: {e}")

        try:
            pep = await self.pep_detection_agent.research(
                full_name=ubo.full_name,
                citizenship=ubo.citizenship,
                pep_self_declaration=ubo.pep_self_declaration,
            )
            ubo_results["pep"] = pep.model_dump() if pep else None
            if pep and pep.evidence_records:
                for er in pep.evidence_records:
                    er.entity_context = f"UBO ({ubo.ownership_percentage}% owner)"
                    self.evidence_store.append(er.model_dump())
        except Exception as e:
            logger.error(f"UBO PEP detection failed for {ubo.full_name}: {e}")

        try:
            adverse = await self.individual_adverse_media_agent.research(
                full_name=ubo.full_name,
                citizenship=ubo.citizenship,
            )
            ubo_results["adverse_media"] = adverse.model_dump() if adverse else None
            if adverse and adverse.evidence_records:
                for er in adverse.evidence_records:
                    er.entity_context = f"UBO ({ubo.ownership_percentage}% owner)"
                    self.evidence_store.append(er.model_dump())
        except Exception as e:
            logger.error(f"UBO adverse media failed for {ubo.full_name}: {e}")

        return ubo_results

    async def _run_utility(self, util_name: str, client, plan: InvestigationPlan,
                           investigation: InvestigationResults = None):
        """Dispatch to the correct utility via dispatch table."""
        if util_name not in UTILITY_DISPATCH:
            raise ValueError(f"Unknown utility: {util_name}")
        module_path, func_name, args_fn = UTILITY_DISPATCH[util_name]
        module = importlib.import_module(module_path)
        func = getattr(module, func_name)
        args, kwargs = args_fn(client, plan, investigation)
        return func(*args, **kwargs)

    def _store_agent_result(self, results: InvestigationResults, agent_name: str, result):
        """Store agent result in the appropriate field and update evidence store."""
        field = AGENT_RESULT_FIELD.get(agent_name)
        if field:
            setattr(results, field, result)

        # Add evidence records to central store
        if hasattr(result, 'evidence_records'):
            for er in result.evidence_records:
                self.evidence_store.append(er.model_dump() if hasattr(er, 'model_dump') else er)

    def _store_utility_result(self, results: InvestigationResults, util_name: str, result: dict):
        """Store utility result and update evidence store."""
        field = UTILITY_RESULT_FIELD.get(util_name)
        if field:
            setattr(results, field, result)

        # Add evidence records from utility (utilities use "evidence" key)
        if isinstance(result, dict):
            evidence = result.get("evidence_records") or result.get("evidence") or []
            self.evidence_store.extend(evidence)
