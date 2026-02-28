"""
Base agent class for Claude API interactions with tool use.
"""

import asyncio
import json
import os
import anthropic
from abc import ABC, abstractmethod
from typing import Any, Optional

from tools.tool_definitions import TOOL_DEFINITIONS, execute_tool, get_tools_for_agent
from config import get_config, get_model_for_agent, get_tool_limit_for_agent
from logger import get_logger


# Module logger
logger = get_logger(__name__)


# =============================================================================
# Shared Prompt Sections - Reduce token usage by standardizing common instructions
# =============================================================================

KYC_EVIDENCE_RULES = """## Evidence Classification (V/S/I/U)
All findings MUST include evidence classification:
- [V] Verified: URL + direct quote from Tier 0/1 source (government registry, official sanctions list, regulatory database)
- [S] Sourced: URL + excerpt from Tier 1/2 source (major news, corporate filings)
- [I] Inferred: Derived from multiple signals (explain reasoning chain)
- [U] Unknown: Searched but information not found

Every claim must have a disposition:
- CLEAR: No match or concern found after thorough search
- POTENTIAL_MATCH: Possible match requiring human review (include similarity score)
- CONFIRMED_MATCH: Definitive match with strong evidence
- FALSE_POSITIVE: Initial match determined to be different entity (explain why)
- PENDING_REVIEW: Cannot determine — requires human judgment"""

KYC_OUTPUT_RULES = """## Output Format
Return findings as valid JSON in a ```json code block. Ensure all strings are properly escaped.
Include evidence_records array with each finding linked to sources."""

KYC_FALSE_POSITIVE_RULES = """## False Positive Analysis
When screening returns a potential match:
1. Compare full name, date of birth, citizenship, and any other identifiers
2. Check for common name disambiguation (different person with same name)
3. Score confidence: >0.95 = POTENTIAL_MATCH, 0.70-0.95 = investigate secondary identifiers, <0.70 = likely CLEAR
4. Document your reasoning for every disposition decision
5. When in doubt, flag as PENDING_REVIEW for human decision"""

KYC_REGULATORY_CONTEXT = """## Canadian Regulatory Context
This screening supports compliance with:
- FINTRAC (Financial Transactions and Reports Analysis Centre of Canada) — PCMLTFA
- CIRO (Canadian Investment Regulatory Organization) — KYC Rule 3202
- OFAC (if US nexus) — SDN List, 50% Rule
- FATCA (if US indicia) — IRS reporting
- CRS (Common Reporting Standard) — OECD automatic exchange"""


# Global API key storage - set once at startup
_API_KEY: str | None = None


def set_api_key(key: str):
    """Set the API key globally for all agents."""
    global _API_KEY
    _API_KEY = key
    os.environ["ANTHROPIC_API_KEY"] = key
    logger.debug("API key set globally")


def get_api_key() -> str | None:
    """Get the current API key."""
    return _API_KEY or os.environ.get("ANTHROPIC_API_KEY")


def _safe_parse_enum(enum_class, raw_value: str, default, fallback=None):
    """Parse a string into an enum, returning default/fallback on failure.

    Args:
        enum_class: The enum type (e.g. DispositionStatus).
        raw_value: Raw string to parse (will be uppercased).
        default: Default enum value if raw_value is empty/None.
        fallback: Value to return on ValueError. If None, returns default.
    """
    try:
        return enum_class(raw_value.upper() if raw_value else default.value)
    except (ValueError, AttributeError):
        return fallback if fallback is not None else default


class BaseAgent(ABC):
    """
    Base class for all research agents.

    Handles Claude API communication and tool use loops.
    Subclasses define the system prompt and which tools to use.
    """

    def __init__(
        self,
        model: str | None = None,
        max_tokens: int = 4096,
        max_tool_calls: int | None = None,
        api_key: str | None = None,
    ):
        config = get_config()

        # Use provided key, global key, or environment variable
        key = api_key or get_api_key()
        # Let SDK handle retries with proper retry-after header parsing
        if key:
            self.client = anthropic.Anthropic(api_key=key, max_retries=5)
        else:
            self.client = anthropic.Anthropic(max_retries=5)

        # Store explicit model override, otherwise use lazy lookup
        self._explicit_model = model
        self.max_tokens = max_tokens
        # Store explicit tool limit override, otherwise use lazy lookup
        self._explicit_tool_limit = max_tool_calls
        self._config = config
        self._hit_rate_limit = False  # Track if rate limit was encountered

        # Search monitoring
        self._web_search_count = 0
        self._web_fetch_count = 0
        self._search_queries = []  # Track actual queries for monitoring

        # Search context from pipeline (to avoid duplicate queries)
        self._search_context = ""

        # Token usage from last API call (preserved for pipeline metrics)
        self._last_usage = {"input_tokens": 0, "output_tokens": 0}

    @property
    def model(self) -> str:
        """Get the model for this agent - uses routing based on agent name."""
        if self._explicit_model:
            return self._explicit_model
        # Use agent-specific model routing (Haiku for data gathering, Sonnet for reasoning)
        return get_model_for_agent(self.name)

    @model.setter
    def model(self, value: str):
        """Allow explicit model override."""
        self._explicit_model = value

    @property
    def max_tool_calls(self) -> int:
        """Get the max tool calls for this agent - uses routing based on agent name."""
        if self._explicit_tool_limit is not None:
            return self._explicit_tool_limit
        # Use agent-specific tool limit routing
        return get_tool_limit_for_agent(self.name)

    @max_tool_calls.setter
    def max_tool_calls(self, value: int):
        """Allow explicit tool limit override."""
        self._explicit_tool_limit = value

    @property
    @abstractmethod
    def name(self) -> str:
        """Agent name for logging."""
        pass

    @property
    @abstractmethod
    def system_prompt(self) -> str:
        """System prompt for this agent."""
        pass

    @property
    @abstractmethod
    def tools(self) -> list[str]:
        """List of tool names this agent can use."""
        pass

    def get_tool_definitions(self) -> list[dict]:
        """Get Claude API tool definitions for this agent's tools."""
        tools = get_tools_for_agent(self.tools)

        # Add Claude's native web search if agent requested web_search
        if "web_search" in self.tools:
            tools.append({
                "type": "web_search_20250305",
                "name": "web_search"
            })

        return tools

    def reset_search_stats(self):
        """Reset search monitoring counters before a new run."""
        self._web_search_count = 0
        self._web_fetch_count = 0
        self._search_queries = []

    @property
    def search_stats(self) -> dict:
        """Get current search statistics."""
        return {
            "web_search_count": self._web_search_count,
            "web_fetch_count": self._web_fetch_count,
            "search_queries": self._search_queries.copy(),
        }

    @property
    def search_context(self) -> str:
        """Get search context from pipeline (previously searched queries)."""
        return self._search_context or ""

    # =========================================================================
    # Evidence Record Helpers
    # =========================================================================

    def _build_finding_record(
        self,
        evidence_id: str,
        entity: str,
        claim: str,
        supporting_data: list = None,
        *,
        evidence_level=None,
        disposition=None,
        confidence=None,
    ):
        """Build a standard evidence record for a finding.

        Imports are done at call time to avoid circular imports at module level.
        """
        from models import EvidenceRecord, EvidenceClass, DispositionStatus, Confidence as Conf
        return EvidenceRecord(
            evidence_id=evidence_id,
            source_type="agent",
            source_name=self.name,
            entity_screened=entity,
            claim=claim,
            evidence_level=evidence_level or EvidenceClass.SOURCED,
            supporting_data=supporting_data or [],
            disposition=disposition or DispositionStatus.PENDING_REVIEW,
            confidence=confidence or Conf.MEDIUM,
        )

    def _build_clear_record(
        self,
        evidence_id: str,
        entity: str,
        claim: str,
        supporting_data: list = None,
        *,
        disposition_reasoning: str = None,
    ):
        """Build a standard 'no findings' evidence record."""
        from models import EvidenceRecord, EvidenceClass, DispositionStatus, Confidence as Conf
        return EvidenceRecord(
            evidence_id=evidence_id,
            source_type="agent",
            source_name=self.name,
            entity_screened=entity,
            claim=claim,
            evidence_level=EvidenceClass.SOURCED,
            supporting_data=supporting_data or [],
            disposition=DispositionStatus.CLEAR,
            disposition_reasoning=disposition_reasoning,
            confidence=Conf.HIGH,
        )

    @staticmethod
    def _attach_search_queries(result_obj, raw_result: dict):
        """Attach search_queries_executed from API result to a model object."""
        result_obj.search_queries_executed = raw_result.get("search_stats", {}).get("search_queries", [])

    async def execute_tool_call(self, tool_name: str, tool_input: dict) -> Any:
        """
        Execute a tool call and return the result.

        Override this in subclasses to add custom tool handling.
        """
        return await execute_tool(tool_name, tool_input)

    async def run(self, user_message: str, context: dict = None) -> dict:
        """
        Run the agent with the given user message.

        Handles the tool use loop automatically.
        Returns the final response and any structured data extracted.
        """
        # Reset search stats for this run
        self.reset_search_stats()

        logger.debug(f"[{self.name}] Using model: {self.model}")
        messages = [{"role": "user", "content": user_message}]
        tool_definitions = self.get_tool_definitions()

        tool_call_count = 0

        while tool_call_count < self.max_tool_calls:
            # Call Claude - only include tools parameter if we have tools
            api_kwargs = {
                "model": self.model,
                "max_tokens": self.max_tokens,
                "system": self.system_prompt,
                "messages": messages,
            }
            if tool_definitions:
                api_kwargs["tools"] = tool_definitions

            # Handle rate limits properly - wait and retry, never skip
            response = None
            max_rate_limit_retries = 10  # Will retry up to 10 times for rate limits

            for rate_limit_attempt in range(max_rate_limit_retries):
                try:
                    # SDK has max_retries=5 for quick transient errors
                    response = self.client.messages.create(**api_kwargs)

                    # If we recovered from rate limit, add buffer to let bucket refill
                    if rate_limit_attempt > 0:
                        self._hit_rate_limit = True
                        logger.info(f"[{self.name}] Rate limit recovered, adding 30s buffer")
                        await asyncio.sleep(30)

                    break  # Success - exit retry loop

                except anthropic.RateLimitError as e:
                    if rate_limit_attempt == max_rate_limit_retries - 1:
                        logger.error(f"[{self.name}] Rate limit exceeded after {max_rate_limit_retries} attempts")
                        raise

                    # Extract wait time from error message or headers
                    wait_time = 60  # Default: wait full minute for per-minute limits

                    try:
                        # Try to get retry-after from response
                        if hasattr(e, 'response') and e.response is not None:
                            retry_after = e.response.headers.get('retry-after')
                            if retry_after:
                                wait_time = int(float(retry_after)) + 5  # Add 5s buffer
                    except (ValueError, AttributeError, TypeError):
                        pass

                    logger.warning(f"[{self.name}] Rate limited, waiting {wait_time}s then retrying (attempt {rate_limit_attempt + 1}/{max_rate_limit_retries})")
                    await asyncio.sleep(wait_time)

            if response is None:
                raise RuntimeError(f"[{self.name}] Failed to get response after rate limit retries")

            # Check if we're done (no tool use)
            if response.stop_reason == "end_turn":
                return self._extract_response(response, messages)

            # Process tool calls
            if response.stop_reason == "tool_use":
                # Add assistant's response to messages
                messages.append({
                    "role": "assistant",
                    "content": response.content
                })

                # Execute each tool call (skip server-side tools like web_search)
                tool_results = []
                for block in response.content:
                    if block.type == "tool_use":
                        # Skip server-side tools - Claude handles these automatically
                        if block.name == "web_search":
                            tool_call_count += 1
                            self._web_search_count += 1
                            # Track query for monitoring
                            query = block.input.get("query", "") if hasattr(block, "input") else ""
                            if query:
                                self._search_queries.append(query)
                            logger.info(f"[{self.name}] Web search #{self._web_search_count}: {query[:50]}...")
                            continue

                        tool_call_count += 1
                        # Track web_fetch calls for monitoring
                        if block.name == "web_fetch":
                            self._web_fetch_count += 1
                        logger.info(f"[{self.name}] Calling {block.name}")

                        result = await self.execute_tool_call(
                            block.name,
                            block.input
                        )

                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": json.dumps(result) if isinstance(result, dict) else str(result)
                        })

                # Add tool results to messages (only if we have results to add)
                if tool_results:
                    messages.append({
                        "role": "user",
                        "content": tool_results
                    })
            else:
                # Unexpected stop reason
                break

        # Max tool calls reached
        return self._extract_response(response, messages)

    def _extract_response(self, response: anthropic.types.Message, messages: list) -> dict:
        """Extract the final text response and any JSON data."""
        # Preserve cumulative token usage for pipeline metrics
        self._last_usage = {
            "input_tokens": self._last_usage["input_tokens"] + response.usage.input_tokens,
            "output_tokens": self._last_usage["output_tokens"] + response.usage.output_tokens,
        }

        text_content = ""
        for block in response.content:
            if hasattr(block, "text"):
                text_content += block.text

        # Try to extract JSON from the response
        json_data = None
        try:
            # Look for JSON in code blocks
            import re
            json_match = re.search(r'```json\s*(.*?)\s*```', text_content, re.DOTALL)
            if json_match:
                json_data = json.loads(json_match.group(1))
            else:
                # Try to parse the whole response as JSON
                json_data = json.loads(text_content)
        except (json.JSONDecodeError, AttributeError):
            pass

        return {
            "text": text_content,
            "json": json_data,
            "messages": messages,
            "model": self.model,
            "usage": {
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
            },
            "hit_rate_limit": self._hit_rate_limit,
            # Search monitoring stats
            "search_stats": {
                "web_search_count": self._web_search_count,
                "web_fetch_count": self._web_fetch_count,
                "search_queries": self._search_queries.copy(),
            },
        }


class SimpleAgent(BaseAgent):
    """
    A simple agent that can be configured at runtime.

    Useful for one-off tasks or testing.
    """

    def __init__(
        self,
        agent_name: str,
        system: str,
        agent_tools: list[str] = None,
        **kwargs
    ):
        super().__init__(**kwargs)
        self._name = agent_name
        self._system_prompt = system
        self._tools = agent_tools or []

    @property
    def name(self) -> str:
        return self._name

    @property
    def system_prompt(self) -> str:
        return self._system_prompt

    @property
    def tools(self) -> list[str]:
        return self._tools
