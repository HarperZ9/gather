# Gather Usage

Gather turns difficult source intake into replayable, digest-backed research
packets. It is designed for local CLI use, MCP hosts, and larger Project Telos
workflows that need provenance before synthesis.

## Install

```bash
python -m pip install gather-engine
```

From a source checkout:

```bash
python -m pip install -e ".[dev]"
```

## Run

```bash
gather status --json
gather doctor --json
gather demo --json
gather --help
```

The same package can be exercised from source with:

```bash
python -m gather --help
```

## Federation

Validate a source-federation registry and compile its capture plans, all offline:

```bash
gather federation validate registry.json --json
gather federation plan registry.json --json
```

A registry file is a list of source rows or `{"sources": [...]}`; each row carries
`id`, `system`, `family`, `domain`, `access`, `adapter`, `url`, `scope`, and
`priority`. Validation is a closed contract: unknown access tokens, priorities, or
extra fields are typed rejections, and the validated snapshot is sealed, so a row
cannot be edited after witnessing without breaking the seal. `plan` adds one
deterministic capture plan per source, derived from its access policy. Neither
command probes a source, and a registry row is never reported as coverage or
availability.

## MCP

Use `gather mcp` when a host needs the tool over stdio. The MCP surface should
stay aligned with the CLI envelope and receipt fields.

```bash
gather mcp
```

## Verify

```bash
python -m pytest
python examples/demo.py
python examples/pipeline.py
```

For public/developer delivery checks:

```bash
python -m public_surface_sweeper . --workspace --json
```

## Boundary

Gather may collect material from live sources, but outward-facing receipts
should prefer source references, content hashes, timestamps, and verdicts. Do
not publish raw private payloads, secrets, credentials, or source material whose
license or privacy posture does not allow redistribution.
