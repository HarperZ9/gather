# Gather Discord Research Collector Design

**Date:** 2026-07-10
**Status:** Proposed; awaiting review
**Default retention:** Durable redacted evidence; transient raw API responses
**Transport:** Official Discord bot API only

## Objective

Add a fast, resumable, provenance-preserving research collector for authorized
technical Discord communities. The first research lane covers HDR Den, RenoDX,
Community Shaders, Skyrim/ENB, colorist, display, rendering, and game-engine
communities where the operator has permission and the bot can be invited.

The collector is query-first rather than a blind server mirror. It minimizes
Discord API work, storage, privacy exposure, and model tokens while preserving
enough stable evidence to verify technical claims and follow public research
leads.

## Safety Decision

The current in-flight adapter in `src/gather/discord.py` is an official-bot
prototype, not a live-ready collector. It currently places usernames, author
IDs, full attachment URLs, and raw message JSON into durable items. The new
design requires deterministic redaction before any corpus write or synthesis.

Raw Discord API payloads are transient by default. Gather computes a source
payload hash in memory, normalizes and redacts the message, commits only the
redacted item plus a sealed receipt, and then discards the raw payload. Raw chat
is not training data and does not cross into an external model endpoint.

Only a bot token stored locally as `GATHER_DISCORD_BOT_TOKEN` is supported. A
personal user token, self-bot, copied browser credential, browser-session
scraper, or UI automation path is out of scope. Credentials are never accepted
in a target, plan, command argument, receipt, URL, or chat message.

## Initial Authorized Guild Registry

The first capture plan may reference these operator-provided guild IDs:

| Profile | Guild ID | Default state |
|---|---:|---|
| HDR Den | `1161035767917850784` | Registered; no capture until bot membership and channel allowlist preflight pass |
| RenoDX | `1408098019194310818` | Registered; no capture until bot membership and channel allowlist preflight pass |
| Community Shaders | `1080142797870485606` | Registered; no capture until bot membership and channel allowlist preflight pass |

Additional Skyrim, ENB, colorist, display, rendering, or engine communities are
added through the same local registry. Possession of a guild ID is not capture
authorization. The bot must be present, the plan must allowlist technical
channels or searches, and Discord must report the needed permissions.

## Requirements

- **D1 — Sealed capture plan:** Every run references a local, canonical plan
  containing approved guild IDs, channel/thread allowlists, query profiles,
  time/snowflake bounds, page/message budgets, attachment policy, redaction
  version, and retention policy. The plan digest is in every receipt.
- **D2 — Fail-closed scope:** Unknown guilds/channels, DMs, group DMs, private
  threads, mismatched guild/channel pairs, and arbitrary token-bearing API
  origins are rejected before a credential is read or sent.
- **D3 — Official origin:** Credential-bearing requests go only to the pinned
  Discord API origin. Tests inject a fake transport rather than overriding the
  production base URL.
- **D4 — Query-first search:** Use Discord's Search Guild Messages endpoint for
  bounded, topic-focused discovery. Channel history is an allowlisted fallback,
  not the default way to mirror a server.
- **D5 — Deterministic redaction:** Redaction removes author/user IDs, names,
  avatars, member objects, raw JSON, mention IDs, and signed URL query data
  before durable storage. It preserves technical prose, code, timestamps,
  message/guild/channel locators, stable public links, and safe attachment
  descriptors.
- **D6 — Distinct evidence edges:** A canonical redacted message and the
  query/search match that discovered it are separate receipts. The same message
  deduplicates across searches without losing discovery provenance.
- **D7 — Rate-limit correctness:** The Discord transport exposes status,
  headers, and body. It honors live rate-limit headers, global/shared scope,
  `Retry-After`, 202 search-indexing responses, and bounded retry budgets using
  injected clocks/sleepers in tests.
- **D8 — Durable checkpoints:** A checkpoint advances only after its corpus
  batch and capture manifest are durable. A crash before commit repeats safely;
  a crash after commit resumes without duplicate evidence.
- **D9 — Deep-search windows:** Search pages respect Discord's 25-result page
  limit and maximum offset. Deeper collection advances bounded snowflake/time
  windows instead of looping or silently truncating at offset 9975.
- **D10 — Truthful completeness:** Short pages and changing
  `total_results` do not prove completion. Every run reports its bounds, page
  budget, retry/indexing events, skipped regions, and completeness state.
- **D11 — Safe attachments:** Default is metadata-only: stable attachment ID,
  sanitized filename, MIME, byte size, dimensions, and descriptor hash. Optional
  byte capture requires explicit plan policy, approved Discord CDN hosts,
  size/MIME/magic limits, exact byte hash, and a completeness status. External
  embed links are never followed automatically.
- **D12 — Receipt-only host surfaces:** Python, CLI, and MCP validate the same
  plan. MCP accepts an approved local plan ID, not arbitrary guild scope, and
  returns sealed summaries/receipt references rather than message bodies.
- **D13 — Diagnostic privacy:** `gather doctor --json` may report whether a
  token is present and whether capability preflight succeeded, but never token
  content, message content, user identities, or authorization headers.
- **D14 — Token-efficient synthesis:** Deterministic query, redaction, exact and
  near-duplicate filtering, thread grouping, and lexical claim extraction occur
  before a local model sees content. The model receives only bounded redacted
  evidence packets and must return claim/evidence references.
- **D15 — No automatic training use:** Durable community evidence is a research
  corpus. Fine-tuning, embedding upload, external inference, or redistribution
  requires a separately approved policy and rights review.

## Architecture

```text
approved federation row
  -> sealed Discord capture plan
  -> scope and permission preflight
  -> official Discord search/history transport
  -> transient response hash
  -> deterministic normalize + redact
  -> exact/near dedupe and thread grouping
  -> durable redacted message receipt
  -> durable search-match edge
  -> atomic corpus batch + checkpoint
  -> capture manifest
  -> bounded claim/evidence synthesis
```

### Capture plan

The plan is data, not executable code:

```json
{
  "schema_version": 1,
  "plan_id": "hdr-rendering-research-v1",
  "guilds": [
    {
      "guild_id": "1080142797870485606",
      "channels": ["approved-channel-id"],
      "include_public_threads": true,
      "include_private_threads": false
    }
  ],
  "queries": ["pq", "scRGB", "paper white", "tone mapping"],
  "after": "2023-01-01T00:00:00Z",
  "before": "2026-07-10T00:00:00Z",
  "page_budget": 100,
  "message_budget": 2000,
  "redaction_policy": "discord-technical-v1",
  "attachment_policy": "metadata-only",
  "raw_retention": "transient"
}
```

The example is illustrative. Real channel IDs are discovered during preflight
and then explicitly approved in the local plan; discovery itself does not grant
capture authority.

### Redacted message item

The durable item includes:

- stable guild, channel/thread, and message IDs;
- message timestamp and edit timestamp;
- redacted technical content;
- canonical Discord message link without credentials;
- reply/reference message locator when present;
- safe attachment descriptors and hashes;
- source-payload SHA-256 computed before redaction;
- redaction-policy version and plan digest;
- collection method (`discord-api-search` or `discord-api-history`);
- retrieval timestamp and completeness/quality flags.

The durable item excludes:

- username, display/global name, author ID, avatar, discriminator, roles, and
  member profile;
- raw author/member/interaction objects;
- full raw API JSON;
- signed attachment query parameters;
- bot token, headers, gateway/session data, and machine/user identifiers.

Mentions become typed placeholders such as `[user]`, `[role]`, and `[channel]`.
Code blocks and URLs are normalized without changing their technical meaning.

### Provenance sealing

Critical context cannot live only in mutable `Item.meta`. The canonical item
text or a new sealed receipt extension includes the guild/channel/message
locator, source payload hash, redaction version, capture-plan digest, and
retrieval method. A malformed or missing Discord snowflake is rejected rather
than replaced with a page index.

The capture manifest contains:

```text
plan ID and digest
redaction policy and digest
query/profile hashes
time and snowflake bounds
pages requested and responses accepted
202/429/retry events and waits
transient source-payload aggregate hash
durable item and discovery-edge hashes
checkpoint before and after
typed warnings and completeness state
```

### Transport and retry model

A Discord-specific transport returns `status`, normalized response headers,
and bounded body bytes. It maps:

- `200` to an accepted page;
- `202` to indexing-in-progress with bounded `retry_after` handling;
- `401` to invalid bot credential without echoing content;
- `403` to missing guild/channel permission with an actionable preflight error;
- `404` to unavailable or out-of-plan resource;
- `429` to a rate-limit event honoring header/body retry timing;
- transient `5xx` to bounded exponential retry with jitter supplied by an
  injected deterministic policy in tests;
- malformed or truncated JSON to a typed incomplete capture.

The production transport cannot redirect the `Authorization` header to another
origin. Rate limits are learned from response headers, not hard-coded.

### Search and checkpoint model

Each query/channel/time window is an independent cursor lane. Search results are
flattened from Discord's nested message arrays, exact-deduplicated by message
snowflake, and committed in small batches. Beyond Discord's maximum offset, the
collector closes the current snowflake/time window and starts the next bounded
window.

The atomic checkpoint key includes plan digest, redaction version, query hash,
guild/channel scope, and cursor bounds. Changing any of them invalidates or
forks the checkpoint instead of mixing incompatible runs.

## Token-Efficient Research Synthesis

The collector does not send a whole server to a model. It uses this funnel:

1. Discord-side query and channel/time bounds.
2. Deterministic redaction and boilerplate removal.
3. Exact message deduplication by snowflake and content hash.
4. Near-duplicate clustering for repeated announcements/cross-posts.
5. Thread/reply grouping and technical-term scoring.
6. Link and citation extraction; public links become separate Gather leads.
7. Fixed-size evidence packets with stable receipt IDs.
8. Local-model claim extraction constrained to `{claim, evidence_refs,
   confidence, status, followup_leads}`.
9. Deterministic rejection of a claim with missing or unknown evidence refs.
10. Cross-source corroboration through Gather/Crucible before a claim becomes a
    product requirement or conformance assertion.

Suggested initial query profiles are versioned and reviewable:

- **display measurement:** EOTF, PQ, ST 2084, peak nits, ABL, APL, thermal,
  chromaticity, white point, DisplayHDR;
- **Windows output:** scRGB, Advanced Color, paper white, SDR white, DXGI, HDR
  metadata, swapchain, FP16;
- **rendering:** tone mapping, gamut mapping, ICtCp, JzAzBz, ACES, LUT, exposure,
  local exposure, dithering, banding;
- **Skyrim/ENB/CS:** Community Shaders HDR, ENB adaptation, weather, bloom,
  UI composition, post-processing, shader validation;
- **colorist/mastering:** grade once/output many, reference white, mastering
  peak, BT.2390, BT.2408, BT.2446, scopes, test patterns.

Query profiles are discovery aids, not truth filters. Negative results mean only
that the bounded plan found no match.

## Privacy, Rights, and Clean-Room Use

Every captured item is labeled `community_claim` until corroborated. The
collector preserves stable message evidence without author profiling. Public
papers, standards, issues, repositories, or vendor documentation found through
messages become separate direct-source items.

Implementation synthesis follows a clean-room corridor:

1. researcher records the redacted claim, public lead, black-box behavior, and
   source revision;
2. verifier finds standards or primary public evidence where possible;
3. architect writes an independent behavior specification and tests;
4. implementer receives the specification/tests, not protected or decompiled
   implementation text;
5. provenance and license review gates public release.

Community permission to research does not erase copyright, license, privacy,
platform, or redistribution obligations. Deobfuscation or protected-source
analysis is handled only where authorized and remains a behavioral lead unless
a separate rights review permits more.

## Surface Design

- `gather discord plan validate PLAN --json` — pure validation and digest.
- `gather discord preflight PLAN --json` — permission/scope check, no messages.
- `gather discord capture PLAN --json` — resumable redacted capture.
- `gather discord status PLAN --json` — read-only checkpoint/manifest summary.
- `gather discord doctor --json` — local dependency/token-presence diagnostics.
- MCP exposes validate, preflight, capture-by-plan-ID, and status with
  receipt-only outputs.
- `gather run` may compose an approved Discord plan with other source jobs, but
  may not inline arbitrary guild scope from an MCP caller.

Exact command names can narrow during planning, but Python, CLI, and MCP must
share one validation and execution engine.

## Verification Strategy

1. Golden redaction fixtures remove all identity and credential-shaped fields
   while preserving code and technical prose.
2. Unknown guilds, DMs, private threads, guild mismatch, and alternate API
   origins fail before credential use.
3. Search tests cover query encoding, 25-result pages, nested arrays, deep
   snowflake windows, duplicate messages, and drifting totals.
4. Retry tests cover 202, proactive rate waits, 429 header/body timing, global
   limits, zero retry, 5xx budgets, malformed and truncated responses without
   real sleeping.
5. Checkpoint crash tests cover failure before commit, after commit, corrupt
   state, and incompatible plan/redaction/query revisions.
6. Attachment tests prove metadata-only does no fetch; optional capture validates
   host, MIME/magic, size, hash, and completeness.
7. Corpus roundtrip tests prove sealed locators, payload hash, plan digest, and
   discovery edges survive without relying on mutable metadata.
8. Python/CLI/MCP parity tests validate the same plan and confirm dry-run or
   preflight modes cannot fetch message content.
9. Full pytest, Ruff, Mypy, secret scan, public-surface sweep, and fixture-based
   three-guild profiles pass.
10. Live smoke is environment-gated, bounded to an approved test channel, and
    never runs in ordinary CI.

## Delivery Sequence

1. Freeze the current dirty prototype as evidence and replace its raw-message
   persistence tests with redaction-first contracts.
2. Add capture-plan schema, canonical digest, and scope preflight.
3. Add Discord response transport, retry/indexing state machine, and fake
   transport tests.
4. Add query-first search, history fallback, archived public-thread pagination,
   and deep windowing.
5. Add deterministic redaction, canonical message/search-match receipts, and
   attachment descriptors.
6. Add batch commit, atomic checkpoints, and capture manifests.
7. Align Python, CLI, MCP, README, USAGE, CHANGELOG, architecture/threat model,
   examples, status, and doctor.
8. Run local quality gates and a secret-free fixture acceptance suite.
9. Operator creates/invites the bot and stores the token locally, never in chat.
10. Run bounded preflight, review discovered channel list, seal allowlists, then
    perform the first three-guild research capture.

## Success Criteria

- [ ] No durable item, receipt, manifest, checkpoint, log, or MCP response
  contains a bot token, authorization header, username, author ID, avatar,
  member object, full raw JSON, or signed URL query.
- [ ] Every capture is bounded by a sealed, approved plan and rejects DMs and
  private threads by default.
- [ ] Search, rate-limit, 202 indexing, deep pagination, and checkpoint recovery
  pass deterministic tests.
- [ ] The corpus stores redacted messages and separate discovery edges without
  losing provenance or duplicating content.
- [ ] A bounded three-guild capture emits verifiable manifests and resumes
  without duplicate durable evidence.
- [ ] Local synthesis consumes only redacted, deduplicated evidence packets and
  cannot emit a claim without valid receipt references.
- [ ] Public-source leads and community claims are distinguishable throughout
  the Telos evidence graph.

## Approval Gate

Do not run the current prototype against live guilds and do not implement this
design while its status is `Proposed`. After review, mark it `Approved`, write a
test-first implementation plan, and implement against fixtures before asking the
operator to provision or invite a bot.

## Primary Discord References

- [Message resource and guild message search](https://docs.discord.com/developers/resources/message)
- [Rate limits](https://docs.discord.com/developers/topics/rate-limits)
- [Channel and thread resources](https://docs.discord.com/developers/resources/channel)
- [Discord self-bot policy](https://support.discord.com/hc/en-us/articles/115002192352-Automated-User-Accounts-Self-Bots)
