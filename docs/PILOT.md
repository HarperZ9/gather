# Gather Pilot Evidence Engine

The `gather pilot` command turns Gather's existing adapters into a retained,
verifiable research corpus: one closed manifest drives an offline or
controlled-live capture, every captured item lands in a content-addressed
corpus with a hash-chained witness, and the result is a redacted report and
receipt bundle any third party re-verifies without private source material.

Gather is a **retained** capability of Zain Dana Harper. This page describes
what the pilot command does and how to verify its output.

## Customer outcome

Turn difficult mixed sources (web pages, feeds, scholarly graphs, video
metadata, JSON APIs, local documents) into one continuously monitored,
locally retained, independently verifiable research corpus, with change
custody and a privacy boundary between private evidence and shareable
receipts.

## Three representative mission classes

The showcase (`examples/pilot/showcase-offline.json`) exercises all three:

1. **Venture market diligence**: monitor a portfolio page for change, extract
   structured organization fields, and capture founder pages.
2. **Technical and scientific research**: federate scholarly graphs by DOI with
   citation-edge provenance, plus local release-note documents.
3. **Media and operational intelligence**: ingest newsroom feeds, video
   metadata with comments, JSON engagement records, and a private operator memo.

## Deployment choices

- **Workstation**: the operator runs the pilot on their own machine against
  allowlisted local roots and controlled hosts. The showcase runs this way.
- **Customer-hosted**: the pilot runs inside the customer's network, and
  private payloads stay there. Gather receives the redacted receipts the
  customer chooses to share.
- **Provider-managed** (manifest value `provider_managed`): the provider,
  Zain Dana Harper, runs the pilot on a customer's behalf under a custody
  agreement; the same manifest and verification apply.

The manifest names the deployment in `deployment.mode` (`workstation`,
`customer_hosted` or `provider_managed`) and who holds the evidence in
`deployment.custodian` (`customer`, `provider` or `shared`).

Compatibility note, 2026-11-15: manifest format 2 (`gather.pilot-manifest/2`)
replaced two format 1 values, mode `zentropy_managed` and custodian `zentropy`,
with `provider_managed` and `provider`. Gather still reads a format 1 manifest,
prints a deprecation line for each difference, and writes only format 2.
`gather pilot migrate-manifest <manifest.json>` shows the change and `--write`
applies it. An evidence root sealed in format 1 still verifies; one that holds
either old value is closed to `refresh`, and a new capture starts from the
migrated manifest in a new output directory.

In every deployment, a shared bundle carries receipts, hashes, redacted refs
and verdicts. Raw private payloads stay in the local adapters.

## Manifest safety boundary

A pilot manifest is a closed schema: unknown fields, wildcard hosts, ports,
userinfo, IP literals, `..` paths, and absolute paths are all rejected. Offline
network adapters require a fixture; live adapters require an exact allowed
host. Browser navigation is **not** safe for hostile arbitrary URLs and is
disabled by default: this is a known limitation, not a feature gap.

## Commands

```text
gather pilot run MANIFEST --output DIR          # capture once, write report + receipt
gather pilot refresh DIR                        # re-capture monitored sources, archive the prior view
gather pilot verify DIR                         # network-free verification of the whole root
gather pilot bundle DIR --output FILE --visibility shared
gather pilot bundle DIR --output FILE --visibility full --include-private-evidence
```

Exit semantics: manifest refusal exits `2`; a required-source failure or
verification failure exits `1`; success exits `0`.

## Artifact inventory and independent verification

A pilot evidence root contains:

```
manifest.json          pilot-receipt.json      report.json
report.html            monitor-state.json      corpus/   history/
```

`gather pilot verify DIR` re-derives every binding from the local bytes: the
manifest digest, the semantic report digest, the deterministic HTML, the
receipt's byte bindings, every corpus body and run witness, the monitor
ledger, and the history chain. It runs offline. A tampered byte anywhere in
the chain flips the verdict to `false`.

## Private and shared evidence boundary

- **Private** sources keep their mission/source id, adapter, visibility,
  status, item count, and receipt digests in the bundle. Their target, body and
  extraction value stay local.
- **Shared** bundles omit the corpus, monitor state, history, and normalized
  manifest entirely. A full bundle (which includes private evidence) requires
  explicit `--include-private-evidence` confirmation.

## Retained capability

Gather is retained by Zain Dana Harper. The pilot is the first shipped subproject
of a larger SaaS roadmap (a FastAPI control plane, React application, billing,
and deployment system). The pilot command is what ships today; the rest of the
roadmap is planned work.

## Scope

The pilot is a single-operator command. It captures from the domains in its
manifest and records what each source said, with a hash for every byte. A
receipt shows what was captured and when. The truth of a captured statement,
and the accuracy of OCR, transcription and outside metadata, are for the reader
to check. Each report lists its own scope in its `limitations` and
`does_not_prove` fields.
