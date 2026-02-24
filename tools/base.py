"""
Base classes for tools in the KYC Client Onboarding Intelligence System.

Provides abstract interfaces for tool implementations.
"""

from abc import ABC, abstractmethod
from typing import Any, Optional
from dataclasses import dataclass, field

from logger import get_logger

logger = get_logger(__name__)


@dataclass
class ToolResult:
    """Standard result format for tool operations."""

    success: bool
    data: Any = None
    error: Optional[str] = None
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Convert to dictionary for API responses."""
        result = {"success": self.success}
        if self.success:
            if isinstance(self.data, dict):
                result.update(self.data)
            else:
                result["data"] = self.data
        else:
            result["error"] = self.error
        if self.metadata:
            result["metadata"] = self.metadata
        return result


class BaseTool(ABC):
    """
    Abstract base class for all tools.

    Tools provide specific functionality that agents can use
    to gather information or perform actions.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique name for this tool."""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """Description of what this tool does."""
        pass

    @property
    @abstractmethod
    def input_schema(self) -> dict:
        """JSON schema for tool input parameters."""
        pass

    @abstractmethod
    async def execute(self, **kwargs) -> ToolResult:
        """
        Execute the tool with the given parameters.

        Returns:
            ToolResult with success status and data or error
        """
        pass

    def get_definition(self) -> dict:
        """Get the tool definition for Claude API."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema
        }

    async def __call__(self, **kwargs) -> dict:
        """Allow tool to be called as a function."""
        result = await self.execute(**kwargs)
        return result.to_dict()


class ToolRegistry:
    """
    Registry for managing available tools.

    Provides centralized tool registration and lookup.
    """

    def __init__(self):
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool):
        """Register a tool instance."""
        if tool.name in self._tools:
            logger.warning(f"Tool '{tool.name}' already registered, overwriting")
        self._tools[tool.name] = tool
        logger.debug(f"Registered tool: {tool.name}")

    def get(self, name: str) -> Optional[BaseTool]:
        """Get a tool by name."""
        return self._tools.get(name)

    def get_all(self) -> list[BaseTool]:
        """Get all registered tools."""
        return list(self._tools.values())

    def get_definitions(self, tool_names: list[str] = None) -> list[dict]:
        """Get tool definitions for Claude API."""
        if tool_names:
            tools = [self._tools[name] for name in tool_names if name in self._tools]
        else:
            tools = self.get_all()
        return [tool.get_definition() for tool in tools]

    async def execute(self, name: str, **kwargs) -> dict:
        """Execute a tool by name."""
        tool = self.get(name)
        if not tool:
            logger.error(f"Unknown tool: {name}")
            return {"success": False, "error": f"Unknown tool: {name}"}
        return await tool(**kwargs)


# Global tool registry
_registry: Optional[ToolRegistry] = None


def get_tool_registry() -> ToolRegistry:
    """Get the global tool registry."""
    global _registry
    if _registry is None:
        _registry = ToolRegistry()
    return _registry
