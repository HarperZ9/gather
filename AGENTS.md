# Gather Agent Instructions

## Scope

Gather is the Project Telos research intake and provenance tool. Changes should
improve source intake, content hashing, receipt quality, adapter clarity, or
developer ergonomics without weakening the privacy boundary.

## Developer Contract

- Keep the CLI, MCP, and Python package surfaces aligned.
- Prefer path, digest, timestamp, and verdict references over raw private data.
- Do not add network behavior without a receipt shape and a testable boundary.
- Keep README, `USAGE.md`, `CHANGELOG.md`, and examples current when behavior
  changes.

## Verification

Run the targeted slice for the touched surface first:

```bash
python -m pip install -e ".[dev]"
python -m pytest
gather status --json
gather doctor --json
```

For delivery-surface changes, also run the workspace scanner from the
`public-surface-sweeper` checkout:

```bash
python -m public_surface_sweeper . --workspace --json
```
