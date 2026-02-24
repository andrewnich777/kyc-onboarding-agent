"""
Configuration management for KYC Client Onboarding Intelligence System.

Loads configuration from environment variables with sensible defaults.
"""

import os
import logging
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field


def _load_dotenv():
    """Load .env file - uses python-dotenv if available, otherwise manual loading."""
    env_path = Path(__file__).parent / ".env"

    # Try python-dotenv first
    try:
        from dotenv import load_dotenv
        if env_path.exists():
            load_dotenv(env_path)
            return
    except ImportError:
        pass  # python-dotenv not installed

    # Fallback: manually parse .env file
    if env_path.exists():
        try:
            with open(env_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    if '=' in line:
                        key, value = line.split('=', 1)
                        key = key.strip()
                        value = value.strip()
                        if (value.startswith('"') and value.endswith('"')) or \
                           (value.startswith("'") and value.endswith("'")):
                            value = value[1:-1]
                        if key and key not in os.environ:
                            os.environ[key] = value
        except Exception:
            pass


# Load .env file on module import
_load_dotenv()


# =============================================================================
# Model Routing for KYC Agents
# =============================================================================

# Opus 4.6 for complex reasoning/synthesis; Sonnet 4.6 for research agents
AGENT_MODELS = {
    # Complex reasoning - Opus 4.6
    "KYCSynthesis": "claude-opus-4-6",
    "ReviewSession": "claude-opus-4-6",
    # Research agents - Sonnet 4.6
    "IndividualSanctions": "claude-sonnet-4-6",
    "PEPDetection": "claude-sonnet-4-6",
    "IndividualAdverseMedia": "claude-sonnet-4-6",
    "EntityVerification": "claude-sonnet-4-6",
    "EntitySanctions": "claude-sonnet-4-6",
    "BusinessAdverseMedia": "claude-sonnet-4-6",
    "JurisdictionRisk": "claude-sonnet-4-6",
    # Default
    "default": "claude-sonnet-4-6",
}


def get_model_for_agent(agent_name: str) -> str:
    """Get the appropriate model for an agent based on its role."""
    return AGENT_MODELS.get(agent_name, AGENT_MODELS["default"])


# =============================================================================
# Agent Tool Limits
# =============================================================================

AGENT_TOOL_LIMITS = {
    # Research agents get more tool calls for thorough investigation
    "IndividualSanctions": 15,
    "PEPDetection": 12,
    "IndividualAdverseMedia": 15,
    "EntityVerification": 15,
    "EntitySanctions": 15,
    "BusinessAdverseMedia": 15,
    "JurisdictionRisk": 12,
    # Synthesis uses no tools (pure reasoning)
    "KYCSynthesis": 5,
    "ReviewSession": 5,
    # Default
    "default": 12,
}


def get_tool_limit_for_agent(agent_name: str) -> int:
    """Get the appropriate tool call limit for an agent."""
    return AGENT_TOOL_LIMITS.get(agent_name, AGENT_TOOL_LIMITS["default"])


# =============================================================================
# Screening List Configuration
# =============================================================================

SCREENING_LIST_PATH = os.environ.get(
    "SCREENING_LIST_PATH",
    str(Path(__file__).parent / "screening_lists")
)


# =============================================================================
# Application Configuration
# =============================================================================

@dataclass
class Config:
    """Application configuration loaded from environment variables."""

    # API Configuration
    api_key: Optional[str] = field(default_factory=lambda: os.environ.get("ANTHROPIC_API_KEY"))
    model: str = field(default_factory=lambda: os.environ.get("MODEL", "claude-sonnet-4-6"))

    # Output Configuration
    output_dir: str = field(default_factory=lambda: os.environ.get("OUTPUT_DIR", "results"))

    # Logging Configuration
    log_level: str = field(default_factory=lambda: os.environ.get("LOG_LEVEL", "INFO"))
    log_format: str = field(
        default_factory=lambda: os.environ.get(
            "LOG_FORMAT",
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
    )

    # Rate Limiting (kept for resilience, no inter-agent delays with Claude Max)
    max_retries: int = field(default_factory=lambda: int(os.environ.get("MAX_RETRIES", "5")))
    initial_backoff: int = field(default_factory=lambda: int(os.environ.get("INITIAL_BACKOFF", "30")))
    agent_delay: int = field(default_factory=lambda: int(os.environ.get("AGENT_DELAY", "0")))

    # Screening list path
    screening_list_path: str = field(default_factory=lambda: SCREENING_LIST_PATH)

    # Verbose output (for CLI)
    verbose: bool = field(default_factory=lambda: os.environ.get("VERBOSE", "").lower() in ("true", "1", "yes"))

    def __post_init__(self):
        """Validate configuration after initialization."""
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        if self.log_level.upper() not in valid_levels:
            self.log_level = "INFO"
        self.log_level = self.log_level.upper()

    def get_log_level(self) -> int:
        """Get the logging level as an integer."""
        return getattr(logging, self.log_level, logging.INFO)


# Global configuration instance
_config: Optional[Config] = None


def get_config() -> Config:
    """Get the global configuration instance."""
    global _config
    if _config is None:
        _config = Config()
    return _config


def set_config(config: Config):
    """Set the global configuration instance."""
    global _config
    _config = config
