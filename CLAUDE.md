# Intent Graph: development notes

Read `docs/vision-and-architecture.md` before changing design. `docs/data-contract.md` is the format contract; `docs/milestones.md` is the log.

- Python package in `src/intentgraph`; install with `uv venv && uv pip install -e ".[dev]"`; test with `.venv/bin/pytest -q`.
- Keep the core small. Pydantic and NetworkX are the only runtime dependencies. Standard-library argparse for the CLI.
- CLI commands call `intentgraph/services.py`; put logic there, not in `cli/main.py`.
- Any change to storage format, vocabulary, patch semantics, or response envelope must update `docs/data-contract.md` and bump the relevant version constant in `src/intentgraph/__init__.py` when it is incompatible.
- Every guarantee listed in architecture section 22 keeps an ordinary executable test, even if it is also modeled in the graph.
- Do not fabricate completed tool checks. Where a capability is not built yet, say so (as `status` does for gates).

<!-- intentgraph:begin -->
## Intent Graph

This workspace keeps a model of software intent, design, implementation mappings and evidence in `.intentgraph/`.
Before making a substantial modeled change, read `.intentgraph/agent-guide.md` and run `intentgraph status --json`.
Edit the model only through `intentgraph patch apply`; never hand-edit `.intentgraph/model.json`.
<!-- intentgraph:end -->
