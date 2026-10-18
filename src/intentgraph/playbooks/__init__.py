"""Agent instructions, examples, and external-tool recipes (installed into workspaces)."""
from pathlib import Path

_DIR = Path(__file__).parent

POINTER_BEGIN = "<!-- intentgraph:begin -->"
POINTER_END = "<!-- intentgraph:end -->"


def agent_guide_text() -> str:
    return (_DIR / "agent-guide.md").read_text(encoding="utf-8")


def pointer_text() -> str:
    body = (_DIR / "pointer.md").read_text(encoding="utf-8").strip()
    return f"{POINTER_BEGIN}\n{body}\n{POINTER_END}\n"
