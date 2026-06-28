# Gather Enterprise Readiness

Gather is the enterprise intake edge: it reaches sources, records how each item arrived, and emits material digests that downstream agents can cite without carrying raw private content through every context window.

This guide aligns the flagship with Project Telos context envelopes and action receipts. The goal is unattended agent work that can be left running and later inspected: what context the agent saw, what exact material it relied on, what it changed, what verified, and what remained unverifiable.

## Enterprise Role

- Convert files, feeds, web pages, papers, transcripts, APIs, browser captures, OCR, and audio into receipted `Item` records.
- Keep direct acquisition, machine transcription, compilation, and synthesis distinct through the `method` ladder.
- Emit content hashes, `derived_from` chains, digest seals, and corpus verification status for downstream replay.

## Host Commands

- `gather status --json` and `gather doctor --json` for host readiness.
- `gather docs PATH --json` for local source-ref intake.
- `gather run CONFIG --json` for multi-source witnessed CLI intake; MCP `gather.run` accepts either a config path or an inline config object for host-neutral agent calls.
- `gather corpus verify DIR` before trusting a stored corpus.
- `gather mcp` for stdio MCP hosts.

## Context Envelope Contribution

- Source refs should carry item `sha256`, `source`, `ref`, `method`, and any `derived_from` hashes.
- Context packets should prefer digest references and exact corpus paths over raw source bodies unless an edit or review needs expansion.
- Browser, OCR, transcription, and model synthesis are marked as machine or impure methods so a model never sees them as plain quotes.

## Action Receipt Contribution

- Input/material digests come from item hashes and digest seals.
- Side-effect class is usually `read` or `external_call`; authenticated APIs and browser captures must not leak credentials into receipts.
- Verification verdicts come from item verification, corpus verification, and digest seal rechecks.

## Readability Gate

Enterprise agent output should be easier for the next agent and a human reviewer to continue:

- Keep patches small enough to review and tied to one bounded work item.
- Prefer named helpers and domain terms over dense inline logic.
- Preserve public interfaces unless the receipt explains why they moved.
- Leave tests, command output, changed files, and next action in the handoff.
- Mark missing source refs, stale packets, failed tests, and verifier abstentions as UNVERIFIABLE instead of guessing.

## Platform Boundary

The flagship remains usable alone through CLI JSON and as part of a larger surface through MCP. OpenAI, Anthropic, IDE, CLI, TUI, and application hosts should consume the same tool outputs and receipt fields rather than reimplementing flagship behavior.

See Project Telos `project-telos.context-envelope/v1` and `project-telos.action-receipt/v1` for the shared cross-tool contract.
