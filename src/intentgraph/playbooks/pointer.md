## Intent Graph

This workspace keeps a model of software intent, design, implementation mappings and evidence in `.intentgraph/`.
Before making a substantial modeled change, read `.intentgraph/agent-guide.md` and run `intentgraph status --json`.
Edit the model only through `intentgraph patch apply`; never hand-edit `.intentgraph/model.json`.
