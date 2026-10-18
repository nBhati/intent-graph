"""Intent Graph: a local, agent-operated annotated graph of software intent,
design, implementation mappings, and evidence.

Version constants are separated deliberately (see architecture section 9.5):
the storage format, the core vocabulary, and the tool are versioned
independently so migrations can be explicit.
"""

TOOL_VERSION = "0.0.1"
FORMAT_VERSION = "0.1"
CORE_VOCABULARY_VERSION = "core/0.2"

__all__ = ["TOOL_VERSION", "FORMAT_VERSION", "CORE_VOCABULARY_VERSION"]
