# Redacted Official Discord Bot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a resumable Discord research collector that uses only an official bot, durably stores deterministic redacted evidence and separate discovery edges, and never exposes raw community payloads or credentials to the corpus, host surfaces, or model layer.

**Architecture:** A closed capture plan is authorized against Gather's existing federation registry and sealed before a credential can be read. Typed Discord routes feed a pinned-origin transport, deterministic retry/search/redaction stages, canonical message and discovery-edge receipts, and a crash-safe corpus/checkpoint store; Python, CLI, and MCP call that one engine and return receipt-only payloads. Local synthesis receives only bounded redacted evidence packets.

**Tech Stack:** Python 3.11+, standard library only at runtime (`dataclasses`, `hashlib`, `json`, `urllib`, `pathlib`), Gather's existing `Item`/`Corpus`/federation/digest contracts, pytest, Ruff, Mypy, and the public-surface sweeper.

## Global Constraints

- Implement against the approved design at `docs/superpowers/DISCORD-RESEARCH-COLLECTOR-DESIGN.md`.
- Begin execution in a consent-recorded isolated worktree created with `superpowers:using-git-worktrees` from the dynamically resolved, reviewed plan tip. The tip must descend from approved design commit `e84f423`, contain this plan, and have no committed prototype-file diff from `e84f423`.
- Leave the dirty prototype files in `C:\dev\public\gather` untouched: `README.md`, `src/gather/method.py`, `src/gather/run_config.py`, `src/gather/discord.py`, and `tests/test_discord.py`.
- Rebuild from failing tests in the isolated worktree. Do not copy or cherry-pick the unsafe prototype.
- Runtime support remains Python `>=3.11` with zero mandatory third-party dependencies.
- Default retention is durable redacted evidence with transient raw API responses.
- Credential-bearing traffic uses only the official Discord bot REST API at `https://discord.com/api/v10`.
- The only supported credential variable is `GATHER_DISCORD_BOT_TOKEN`. User tokens, self-bots, browser credentials, browser-session scraping, and UI automation are prohibited.
- A plan, route, command argument, receipt, log, manifest, checkpoint, or model packet must never contain a token, authorization header, username, author ID, avatar, member object, full raw JSON, or signed attachment query.
- Every capture is bounded by an approved sealed plan containing guild/channel/thread scope, queries, time or snowflake bounds, page/message/batch/retry budgets, redaction policy, attachment policy, and retention policy.
- Unknown guilds/channels, DMs, group DMs, private threads, guild/channel mismatches, alternate origins, and malformed snowflakes fail closed.
- Search is query-first. Channel history is used only for explicitly allowlisted fallback channels.
- Metadata-only attachments are the sole v1 policy. No attachment bytes or external embed targets are fetched.
- A canonical message and each search/history discovery edge are separate sealed Items.
- A checkpoint advances only after the corpus batch and capture manifest are durable.
- Short search pages and changing `total_results` never prove completeness.
- CLI, MCP, and Python use one validation/execution engine. MCP accepts a local approved plan ID, never arbitrary guild scope or a plan body.
- Raw chat is research evidence, not training data. Upload, fine-tuning, remote inference, embedding export, and redistribution require a separate approved policy.
- No live guild request occurs in ordinary CI. Bot creation, invitation, token provisioning, and the first bounded live smoke remain explicit operator gates after fixture acceptance.

---

## File and Responsibility Map

- Create `src/gather/discord_plan.py`: closed plan schema, federation authorization, canonical plan seal, approved plan lookup.
- Create `src/gather/discord_transport.py`: typed routes, official-origin transport, bounded raw response, rate/indexing retry client.
- Create `src/gather/discord_redaction.py`: source hashes, identity lexicon, mention/link normalization, attachment descriptors, durable privacy guard.
- Create `src/gather/discord_receipts.py`: canonical message Items and separate discovery-edge Items.
- Create `src/gather/discord_preflight.py`: metadata-only guild/channel/thread discovery and permission evaluation.
- Create `src/gather/discord_search.py`: query lanes, nested result parsing, deep windows, explicit history fallback, archived public-thread discovery.
- Create `src/gather/discord_store.py`: capture manifests, checkpoint keys, ordered crash-safe batch commit, read-only status.
- Create `src/gather/discord_synthesis.py`: deterministic dedupe/grouping, bounded evidence packets, claim/evidence-reference gate.
- Create `src/gather/discord.py`: shared Python orchestration facade and receipt-only result types.
- Create `src/gather/discord_cmd.py`: Discord CLI handlers only.
- Modify `src/gather/method.py`: register three direct Discord receipt methods.
- Modify `src/gather/cli.py`: nested `gather discord` command tree.
- Modify `src/gather/mcp.py`: receipt-only Discord tools with closed argument schemas.
- Modify `src/gather/flagship.py`: status/doctor parity without sensitive values.
- Modify `src/gather/credentials.py`: non-revealing credential-state diagnostic.
- Modify `src/gather/__init__.py`: export only the stable high-level Discord facade/result types.
- Keep `src/gather/run_config.py` free of direct `discord` and `discord_guild` targets. The existing Source seam cannot guarantee transactional batch/checkpoint behavior.
- Add focused tests under `tests/test_discord_*.py` and secret-free fixtures under `tests/fixtures/discord/`.
- Update `README.md`, `USAGE.md`, `CHANGELOG.md`, `ARCHITECTURE.md`, and `docs/ENTERPRISE-READINESS.md` only after the engine and parity tests are green.

## Stable Interfaces Shared Across Tasks

The implementation must converge on these names and signatures:

~~~python
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol

def parse_capture_plan(
    data: object,
    *,
    federation_rows: Sequence[dict[str, Any]],
) -> SealedCapturePlan: ...

def load_approved_plan(
    plan_id: str,
    *,
    plan_root: Path,
    federation_rows: Sequence[dict[str, Any]],
) -> SealedCapturePlan: ...

class DiscordTransport(Protocol):
    def send(self, request: DiscordRequest) -> DiscordResponse: ...

def redact_message(
    message: Mapping[str, Any],
    *,
    guild_id: str,
    channel_id: str,
    thread_id: str | None,
    plan_digest: str,
    response_body_sha256: str,
) -> RedactedMessage: ...

def message_item(message: RedactedMessage, *, fetched_at: float) -> Item: ...
def discovery_edge_item(edge: DiscoveryEdge, *, fetched_at: float) -> Item: ...

def validate_plan(
    plan: SealedCapturePlan,
    *,
    federation_rows: Sequence[dict[str, Any]],
) -> PlanValidationReceipt: ...
def preflight_plan(plan: SealedCapturePlan, *, client: DiscordClient) -> PreflightReceipt: ...
def discover_guild_channels(
    federation_id: str,
    *,
    federation_rows: Sequence[dict[str, Any]],
    client: DiscordClient,
) -> DiscoveryReceipt: ...
def capture_plan(
    plan: SealedCapturePlan,
    *,
    federation_rows: Sequence[dict[str, Any]],
    client: DiscordClient,
    store: DiscordCaptureStore,
) -> CaptureReceipt: ...
def status_plan(
    plan: SealedCapturePlan,
    *,
    store: DiscordCaptureStore,
) -> CaptureStatusReceipt: ...

def official_client_after_validation(
    plan: SealedCapturePlan,
    *,
    federation_rows: Sequence[dict[str, Any]],
    secret_reader: Callable[[str], str | None] = os.environ.get,
) -> DiscordClient: ...

def official_discovery_client_after_authorization(
    federation_id: str,
    *,
    federation_rows: Sequence[dict[str, Any]],
    secret_reader: Callable[[str], str | None] = os.environ.get,
) -> DiscordClient: ...
~~~

### Review-Integrated Safety Invariants

These requirements are normative. Where an abbreviated code fragment later in the plan omits one, the implementation and tests in the same task must still satisfy this section:

1. `capture_plan` runs `preflight_plan` before loading a checkpoint or issuing a search/history request and proceeds only on an exact `MATCH`. CLI and MCP capture call only `capture_plan`; they do not bypass this gate.
2. A `MATCH` requires the returned guild ID to equal the sealed guild ID, a capability row for every approved channel, a nonempty approved channel set, all required permissions, and exact treatment of `include_public_threads`. Missing channels, private objects, malformed metadata, or permission gaps are terminal mismatches. No vacuous `all(...)` may produce `MATCH`.
3. Search/history message locators are validated against the sealed lane before redaction. Expected IDs come from the sealed lane, never from the message payload. A response guild/channel/thread mismatch produces no message or edge Item and no durable raw data.
4. Capture state is keyed by a stable lane identity, not a moving page cursor. The sealed next cursor is loaded before the first request; after a durable page commit, a restart begins at that cursor. A terminal transport response, `202`, malformed response, or indexing-incomplete response never advances it.
5. Search remains the default. Channel history runs only for `history_channels`. Active and archived public-thread metadata are paginated when `include_public_threads` is true; private threads always fail closed; capture still requires every thread ID to be explicitly sealed.
6. Manifests and receipts describe the whole run, including plan/policy identities, bounds and budgets, requested/accepted page counts, all retry/indexing events, skipped regions, transient-response hash aggregation, durable hashes, cursor movement, and worst-case aggregate completeness. A later successful page cannot erase an earlier warning.
7. The sealed plan is reparsed against trusted federation rows and its invariants/digest are compared before `GATHER_DISCORD_BOT_TOKEN` is read. Tampering proves zero secret reads.
8. Evidence preparation deterministically groups replies/threads, scores technical relevance, and extracts public-link leads before bounded packets reach a local model.
9. Metadata discovery may enumerate accessible public channel IDs for a federation-authorized guild without granting capture authority. It persists no names or identities. Capture requires a newly sealed, nonempty channel allowlist.
10. Manifest identity is deterministic and plan/lane/batch scoped. Identical existing bytes are idempotent; different bytes at the same identity fail without overwrite. Capture uses a single-writer lock.

### Task 0: Consent Record, Worktree Isolation, and Clean Baseline

**Files:**
- Read: `C:\dev\public\gather\docs\superpowers\DISCORD-RESEARCH-COLLECTOR-DESIGN.md`
- Preserve: `C:\dev\public\gather\README.md`
- Preserve: `C:\dev\public\gather\src\gather\method.py`
- Preserve: `C:\dev\public\gather\src\gather\run_config.py`
- Preserve: `C:\dev\public\gather\src\gather\discord.py`
- Preserve: `C:\dev\public\gather\tests\test_discord.py`
- Create worktree: `C:\dev\worktrees\gather-discord-redacted` (the verified centralized workspace convention).

**Interfaces:**
- Consumes: approved design commit `e84f423`, the dynamically resolved reviewed plan tip, and the recorded operator decision `redacted + official bot`.
- Produces: clean branch `feat/discord-redacted-official-bot` whose initial tree contains the reviewed plan but excludes all five dirty prototype changes.

- [ ] **Step 1: Invoke the required worktree skill and verify the approval record**

Run:

~~~powershell
$repo = "C:\dev\public\gather"
$planPath = "docs/superpowers/plans/2026-07-10-redacted-official-discord-bot.md"
$planTip = (git -C $repo rev-parse "HEAD^{commit}").Trim()
if ($LASTEXITCODE -ne 0) { throw "cannot resolve reviewed plan tip" }
git -C $repo merge-base --is-ancestor e84f423 $planTip
if ($LASTEXITCODE -ne 0) { throw "reviewed plan tip does not descend from approved design" }
git -C $repo cat-file -e "$($planTip):$planPath"
if ($LASTEXITCODE -ne 0) { throw "reviewed plan is not committed at plan tip" }
git -C $repo show e84f423:docs/superpowers/DISCORD-RESEARCH-COLLECTOR-DESIGN.md | Select-String -Pattern "Status: Approved for implementation","official Discord bot API only"

$forbidden = @("README.md","src/gather/method.py","src/gather/run_config.py","src/gather/discord.py","tests/test_discord.py")
$committedNames = @(git -C $repo diff --name-only e84f423..$planTip)
$prototypeDiff = @($committedNames | Where-Object { $forbidden -contains $_ })
if ($prototypeDiff.Count -ne 0) { throw "plan tip contains prototype files: $($prototypeDiff -join ', ')" }
git -C $repo config gather.discordPlanTip $planTip
if ((git -C $repo config --get gather.discordPlanTip).Trim() -ne $planTip) {
  throw "reviewed plan tip was not recorded"
}
Write-Output "reviewed-plan-tip=$planTip"
$committedNames
~~~

Expected: the dynamic tip is a descendant of `e84f423`; the approved design phrases print; the committed plan object exists; the committed diff contains plan/design documentation only and none of the five protected prototype paths. The exact tip is durably recorded in repository-local Git config as `gather.discordPlanTip`; no later step depends on a process environment variable. Do not paste a future plan-tip hash into this plan, because doing so would make the plan self-referential.

- [ ] **Step 2: Record the dirty prototype identities without modifying them**

Run:

~~~powershell
$files = @("README.md","src/gather/method.py","src/gather/run_config.py","src/gather/discord.py","tests/test_discord.py")
Set-Location C:\dev\public\gather
foreach ($file in $files) {
  $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $file).Hash
  Write-Output "$hash  $file"
}
git status --short
~~~

Expected: the three modified and two untracked files are listed; no file timestamp or content changes.

- [ ] **Step 3: Create the isolated worktree from the reviewed plan tip**

Run:

~~~powershell
$repo = "C:\dev\public\gather"
$planPath = "docs/superpowers/plans/2026-07-10-redacted-official-discord-bot.md"
$planTip = (git -C $repo config --get gather.discordPlanTip).Trim()
if (-not $planTip) { throw "reviewed plan tip is not recorded" }
git -C $repo merge-base --is-ancestor e84f423 $planTip
if ($LASTEXITCODE -ne 0) { throw "recorded tip no longer verifies" }
git -C $repo cat-file -e "$($planTip):$planPath"
if ($LASTEXITCODE -ne 0) { throw "recorded tip does not contain the plan" }
$forbidden = @("README.md","src/gather/method.py","src/gather/run_config.py","src/gather/discord.py","tests/test_discord.py")
$prototypeDiff = @(git -C $repo diff --name-only e84f423..$planTip | Where-Object { $forbidden -contains $_ })
if ($prototypeDiff.Count -ne 0) { throw "recorded tip contains prototype files" }
git -C $repo worktree add C:\dev\worktrees\gather-discord-redacted -b feat/discord-redacted-official-bot $planTip
~~~

Expected: Git reports a worktree at the dynamically resolved reviewed plan tip on `feat/discord-redacted-official-bot`.

- [ ] **Step 4: Prove the worktree is clean and the unsafe prototype is absent**

Run:

~~~powershell
$repo = "C:\dev\public\gather"
$worktree = "C:\dev\worktrees\gather-discord-redacted"
$planTip = (git -C $repo config --get gather.discordPlanTip).Trim()
if (-not $planTip) { throw "reviewed plan tip is not recorded" }
git -C $repo merge-base --is-ancestor e84f423 $planTip
if ($LASTEXITCODE -ne 0) { throw "recorded tip no longer verifies" }
Set-Location $worktree
if ((git rev-parse "HEAD^{commit}").Trim() -ne $planTip) { throw "worktree did not start at recorded tip" }
git status --porcelain=v1
Test-Path src/gather/discord.py
Test-Path tests/test_discord.py
Test-Path docs/superpowers/plans/2026-07-10-redacted-official-discord-bot.md
git diff --exit-code $planTip --
~~~

Expected: status and diff output are empty; the prototype `Test-Path` calls print `False`; the plan `Test-Path` call prints `True`.

- [ ] **Step 5: Run the clean baseline**

Run:

~~~powershell
python -m pytest -q
python -m ruff check src tests examples
python -m mypy src/gather
~~~

Expected: the clean baseline passes all three commands. Record the exact test count in the execution log.

### Task 1: Closed Plan Schema and Federation Authorization

**Files:**
- Create: `src/gather/discord_plan.py`
- Create: `tests/test_discord_plan.py`
- Create: `tests/fixtures/discord/plan-valid.json`
- Create: `tests/fixtures/discord/federation-valid.json`

**Interfaces:**
- Consumes: `gather.federation.validate_registry(rows) -> list[dict]` and `gather.federation.registry_digest(rows) -> Digest`.
- Produces: `GuildScope`, `CapturePlan`, `SealedCapturePlan`, `PlanError`, `authorized_guild_id(...)`, `parse_capture_plan(data, *, federation_rows)`, and `load_approved_plan(plan_id, *, plan_root, federation_rows)`.

- [ ] **Step 1: Add a valid plan fixture and its federation authorization**

Write `tests/fixtures/discord/federation-valid.json`:

~~~json
{"sources":[{"id":"community-shaders-discord","system":"Discord","family":"Community Shaders","domain":"rendering","access":"account_required","adapter":"discord","url":"discord://guild/1080142797870485606","scope":"authorized technical channels only","priority":"high"}]}
~~~

Write `tests/fixtures/discord/plan-valid.json`:

~~~json
{"schema_version":1,"plan_id":"hdr-rendering-research-v1","guilds":[{"federation_id":"community-shaders-discord","guild_id":"1080142797870485606","channels":["1081121447960915989"],"threads":[],"history_channels":[],"include_public_threads":true,"include_private_threads":false}],"queries":["pq","scRGB","paper white","tone mapping"],"after":"2023-01-01T00:00:00Z","before":"2026-07-10T00:00:00Z","page_budget":100,"message_budget":2000,"batch_size":50,"retry_budget":4,"indexing_retry_budget":6,"redaction_policy":"discord-technical-v1","attachment_policy":"metadata-only","raw_retention":"transient"}
~~~

- [ ] **Step 2: Write the failing valid-plan and deterministic-seal tests**

Add to `tests/test_discord_plan.py`:

~~~python
import json
from pathlib import Path

from gather.discord_plan import parse_capture_plan

FIXTURES = Path(__file__).parent / "fixtures" / "discord"


def _load(name: str) -> object:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_valid_plan_is_authorized_and_sealed_deterministically() -> None:
    rows = _load("federation-valid.json")["sources"]
    first = parse_capture_plan(_load("plan-valid.json"), federation_rows=rows)
    second = parse_capture_plan(_load("plan-valid.json"), federation_rows=list(reversed(rows)))
    assert first == second
    assert first.plan.plan_id == "hdr-rendering-research-v1"
    assert first.plan.guilds[0].guild_id == "1080142797870485606"
    assert len(first.digest) == 64
    assert len(first.authorization_digest) == 64
    assert len(first.redaction_digest) == 64
    assert '"raw_retention":"transient"' in first.canonical_json
~~~

- [ ] **Step 3: Run the valid-plan test and observe the red state**

Run:

~~~powershell
python -m pytest tests/test_discord_plan.py::test_valid_plan_is_authorized_and_sealed_deterministically -q
~~~

Expected: FAIL during collection because `gather.discord_plan` does not exist.

- [ ] **Step 4: Add the immutable plan types and canonical helpers**

Create `src/gather/discord_plan.py` with:

~~~python
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from gather.federation import registry_digest, validate_registry

PLAN_FIELDS = frozenset({"schema_version","plan_id","guilds","queries","after","before","page_budget","message_budget","batch_size","retry_budget","indexing_retry_budget","redaction_policy","attachment_policy","raw_retention"})
GUILD_FIELDS = frozenset({"federation_id","guild_id","channels","threads","history_channels","include_public_threads","include_private_threads"})
PLAN_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
DISCORD_GUILD_PREFIX = "discord://guild/"
REDACTION_POLICY = "discord-technical-v1"
ATTACHMENT_POLICY = "metadata-only"
RAW_RETENTION = "transient"


class PlanError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class GuildScope:
    federation_id: str
    guild_id: str
    channels: tuple[str, ...]
    threads: tuple[str, ...]
    history_channels: tuple[str, ...]
    include_public_threads: bool
    include_private_threads: bool


@dataclass(frozen=True, slots=True)
class CapturePlan:
    schema_version: int
    plan_id: str
    guilds: tuple[GuildScope, ...]
    queries: tuple[str, ...]
    after: str
    before: str
    page_budget: int
    message_budget: int
    batch_size: int
    retry_budget: int
    indexing_retry_budget: int
    redaction_policy: str
    attachment_policy: str
    raw_retention: str


@dataclass(frozen=True, slots=True)
class SealedCapturePlan:
    plan: CapturePlan
    canonical_json: str
    digest: str
    authorization_digest: str
    redaction_digest: str


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _snowflake(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.isdigit() or value.startswith("0"):
        raise PlanError(f"{field} must be a decimal Discord snowflake")
    parsed = int(value)
    if parsed <= 0 or parsed >= 2 ** 64:
        raise PlanError(f"{field} is outside the unsigned 64-bit snowflake range")
    return value


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _authorized_guilds(rows: Sequence[dict[str, Any]]) -> tuple[dict[str, str], str]:
    clean = validate_registry(rows)
    authorized: dict[str, str] = {}
    for row in clean:
        if row["adapter"] == "discord" and row["access"] == "account_required" and row["url"].startswith(DISCORD_GUILD_PREFIX):
            authorized[row["id"]] = _snowflake(row["url"].removeprefix(DISCORD_GUILD_PREFIX), f"federation row {row['id']} guild")
    return authorized, registry_digest(clean).seal


def authorized_guild_id(
    federation_id: str,
    federation_rows: Sequence[dict[str,Any]],
) -> str:
    authorized,_digest = _authorized_guilds(federation_rows)
    try:
        return authorized[federation_id]
    except KeyError as exc:
        raise PlanError("federation ID is not an authorized Discord guild") from exc
~~~

- [ ] **Step 5: Add closed-shape parsing and sealing**

Append to `src/gather/discord_plan.py`:

~~~python
def _closed_object(value: object, fields: frozenset[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise PlanError(f"{label} must be an object")
    extra = sorted(set(value) - fields)
    missing = sorted(fields - set(value))
    if extra:
        raise PlanError(f"{label} has unknown fields: {extra}")
    if missing:
        raise PlanError(f"{label} is missing fields: {missing}")
    return value


def _string_list(value: object, field: str, *, allow_empty: bool) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise PlanError(f"{field} must be a list of strings")
    clean = tuple(item.strip() for item in value if item.strip())
    if not allow_empty and not clean:
        raise PlanError(f"{field} must not be empty")
    if len(clean) != len(set(clean)):
        raise PlanError(f"{field} must not contain duplicates")
    return clean


def _positive_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise PlanError(f"{field} must be a positive integer")
    return value


def _utc_timestamp(value: object, field: str) -> str:
    if not isinstance(value,str):
        raise PlanError(f"{field} must be an ISO 8601 UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z","+00:00"))
    except ValueError as exc:
        raise PlanError(f"{field} must be an ISO 8601 UTC timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise PlanError(f"{field} must be UTC")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00","Z")


def parse_capture_plan(data: object, *, federation_rows: Sequence[dict[str, Any]]) -> SealedCapturePlan:
    raw = _closed_object(data, PLAN_FIELDS, "capture plan")
    if raw["schema_version"] != 1:
        raise PlanError("schema_version must be 1")
    if not isinstance(raw["plan_id"], str) or not PLAN_ID.fullmatch(raw["plan_id"]):
        raise PlanError("plan_id must be a lowercase hyphenated slug")
    authorized, authorization_digest = _authorized_guilds(federation_rows)
    if not isinstance(raw["guilds"], list) or not raw["guilds"]:
        raise PlanError("guilds must be a non-empty list")
    guilds: list[GuildScope] = []
    seen_guilds: set[str] = set()
    for index, value in enumerate(raw["guilds"]):
        row = _closed_object(value, GUILD_FIELDS, f"guilds[{index}]")
        federation_id = row["federation_id"]
        if not isinstance(federation_id, str) or federation_id not in authorized:
            raise PlanError(f"guilds[{index}] references an unauthorized federation row")
        guild_id = _snowflake(row["guild_id"], f"guilds[{index}].guild_id")
        if authorized[federation_id] != guild_id:
            raise PlanError(f"guilds[{index}] does not match its federation guild")
        if guild_id in seen_guilds:
            raise PlanError(f"duplicate guild scope: {guild_id}")
        seen_guilds.add(guild_id)
        channels = tuple(_snowflake(v, f"guilds[{index}].channels") for v in _string_list(row["channels"], f"guilds[{index}].channels", allow_empty=False))
        threads = tuple(_snowflake(v, f"guilds[{index}].threads") for v in _string_list(row["threads"], f"guilds[{index}].threads", allow_empty=True))
        history = tuple(_snowflake(v, f"guilds[{index}].history_channels") for v in _string_list(row["history_channels"], f"guilds[{index}].history_channels", allow_empty=True))
        if not set(history) <= set(channels):
            raise PlanError("history_channels must be a subset of channels")
        if row["include_private_threads"] is not False:
            raise PlanError("include_private_threads must be false")
        if not isinstance(row["include_public_threads"], bool):
            raise PlanError("include_public_threads must be boolean")
        if threads and row["include_public_threads"] is not True:
            raise PlanError("threads require include_public_threads=true")
        guilds.append(GuildScope(federation_id,guild_id,channels,threads,history,row["include_public_threads"],False))
    queries = _string_list(raw["queries"], "queries", allow_empty=False)
    if any(len(query) > 1024 for query in queries):
        raise PlanError("each query must contain at most 1024 characters")
    if raw["redaction_policy"] != REDACTION_POLICY:
        raise PlanError(f"redaction_policy must be {REDACTION_POLICY}")
    if raw["attachment_policy"] != ATTACHMENT_POLICY:
        raise PlanError(f"attachment_policy must be {ATTACHMENT_POLICY}")
    if raw["raw_retention"] != RAW_RETENTION:
        raise PlanError(f"raw_retention must be {RAW_RETENTION}")
    after = _utc_timestamp(raw["after"],"after")
    before = _utc_timestamp(raw["before"],"before")
    if datetime.fromisoformat(after.replace("Z","+00:00")) >= datetime.fromisoformat(before.replace("Z","+00:00")):
        raise PlanError("after must be earlier than before")
    normalized = {**raw,"after":after,"before":before}
    plan = CapturePlan(1,raw["plan_id"],tuple(guilds),queries,after,before,_positive_int(raw["page_budget"],"page_budget"),_positive_int(raw["message_budget"],"message_budget"),_positive_int(raw["batch_size"],"batch_size"),_positive_int(raw["retry_budget"],"retry_budget"),_positive_int(raw["indexing_retry_budget"],"indexing_retry_budget"),REDACTION_POLICY,ATTACHMENT_POLICY,RAW_RETENTION)
    redaction_digest = _sha(REDACTION_POLICY)
    canonical_json = _canonical(normalized)
    digest = _sha(_canonical({"plan":normalized,"authorization_digest":authorization_digest,"redaction_digest":redaction_digest}))
    return SealedCapturePlan(plan,canonical_json,digest,authorization_digest,redaction_digest)


def load_approved_plan(plan_id: str, *, plan_root: Path, federation_rows: Sequence[dict[str, Any]]) -> SealedCapturePlan:
    if not PLAN_ID.fullmatch(plan_id):
        raise PlanError("plan_id must be a lowercase hyphenated slug")
    root = plan_root.resolve()
    path = (root / f"{plan_id}.json").resolve()
    if path.parent != root:
        raise PlanError("plan_id escaped the approved plan root")
    sealed = parse_capture_plan(json.loads(path.read_text(encoding="utf-8")), federation_rows=federation_rows)
    if sealed.plan.plan_id != plan_id:
        raise PlanError("plan filename and embedded plan_id do not match")
    return sealed
~~~

- [ ] **Step 6: Run the valid test and confirm the first green state**

Run:

~~~powershell
python -m pytest tests/test_discord_plan.py::test_valid_plan_is_authorized_and_sealed_deterministically -q
~~~

Expected: PASS.

- [ ] **Step 7: Add fail-closed plan matrix tests**

Append to `tests/test_discord_plan.py`:

~~~python
import copy

import pytest

from gather.discord_plan import PlanError, load_approved_plan


@pytest.mark.parametrize(("mutate","message"),[
    (lambda p:p.update({"token":"fixture-secret"}),"unknown fields"),
    (lambda p:p.update({"raw_retention":"durable"}),"raw_retention"),
    (lambda p:p.update({"attachment_policy":"bytes"}),"attachment_policy"),
    (lambda p:p["guilds"][0].update({"include_private_threads":True}),"include_private_threads"),
    (lambda p:p["guilds"][0].update({"guild_id":"42"}),"does not match"),
    (lambda p:p.update({"page_budget":0}),"page_budget"),
    (lambda p:p.update({"queries":[]}),"queries"),
    (lambda p:p.update({"after":"2026-07-11T00:00:00Z"}),"earlier than"),
])
def test_plan_rejects_unsafe_or_unbounded_shapes(mutate, message: str) -> None:
    plan = copy.deepcopy(_load("plan-valid.json"))
    mutate(plan)
    rows = _load("federation-valid.json")["sources"]
    with pytest.raises(PlanError, match=message):
        parse_capture_plan(plan, federation_rows=rows)


def test_plan_id_lookup_cannot_escape_approved_root(tmp_path: Path) -> None:
    rows = _load("federation-valid.json")["sources"]
    with pytest.raises(PlanError, match="slug"):
        load_approved_plan("../outside", plan_root=tmp_path, federation_rows=rows)
~~~

- [ ] **Step 8: Run the complete plan slice**

Run:

~~~powershell
python -m pytest tests/test_discord_plan.py tests/test_federation.py -q
python -m ruff check src/gather/discord_plan.py tests/test_discord_plan.py
python -m mypy src/gather/discord_plan.py
~~~

Expected: all commands pass.

- [ ] **Step 9: Commit the sealed plan contract**

Run:

~~~powershell
git add src/gather/discord_plan.py tests/test_discord_plan.py tests/fixtures/discord/plan-valid.json tests/fixtures/discord/federation-valid.json
git commit -m "feat(discord): seal approved capture plans"
~~~

Expected: one commit containing only the four listed files.

### Task 2: Typed Official-Origin Transport

**Files:**
- Create: `src/gather/discord_transport.py`
- Create: `tests/test_discord_transport.py`

**Interfaces:**
- Consumes: validated snowflakes and scopes from `SealedCapturePlan`.
- Produces: `DiscordRequest`, `DiscordResponse`, `DiscordTransport`, `DiscordHTTPTransport`, `DiscordTransportError`, and typed request factories.

- [ ] **Step 1: Write failing tests for typed requests and the pinned origin**

Create `tests/test_discord_transport.py`:

~~~python
import inspect
import json

import pytest

from gather.discord_transport import (
    DISCORD_API_ORIGIN,
    DiscordHTTPTransport,
    DiscordRequest,
    DiscordTransportError,
    guild_channels_request,
    guild_search_request,
)


def test_request_factories_create_relative_official_routes_only() -> None:
    channels = guild_channels_request("1080142797870485606")
    search = guild_search_request("1080142797870485606",content="paper white",channel_ids=("1081121447960915989",),limit=25,offset=0,min_id=None,max_id=None)
    assert DISCORD_API_ORIGIN == "https://discord.com"
    assert channels.path == "/guilds/1080142797870485606/channels"
    assert search.path == "/guilds/1080142797870485606/messages/search"
    assert search.query.count(("channel_id","1081121447960915989")) == 1


def test_raw_absolute_or_cross_origin_request_is_rejected() -> None:
    with pytest.raises(DiscordTransportError, match="relative"):
        DiscordRequest("unsafe","https://example.com/api",(),"x")


def test_transport_repr_never_contains_credential() -> None:
    transport = DiscordHTTPTransport("Bot fixture-secret")
    assert "fixture-secret" not in repr(transport)


def test_production_transport_has_no_origin_or_base_url_parameter() -> None:
    params = inspect.signature(DiscordHTTPTransport).parameters
    assert {"origin","api_base","base_url"}.isdisjoint(params)
~~~

- [ ] **Step 2: Run the typed-request tests and observe the red state**

Run:

~~~powershell
python -m pytest tests/test_discord_transport.py -q
~~~

Expected: FAIL during collection because `gather.discord_transport` does not exist.

- [ ] **Step 3: Add request/response types and route factories**

Create `src/gather/discord_transport.py` with:

~~~python
from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Protocol

from gather.net import DEFAULT_UA

DISCORD_API_ORIGIN = "https://discord.com"
DISCORD_API_PREFIX = "/api/v10"
DISCORD_MAX_BODY = 8_000_000


class DiscordTransportError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class DiscordRequest:
    operation: str
    path: str
    query: tuple[tuple[str, str], ...]
    major_id: str

    def __post_init__(self) -> None:
        parsed = urllib.parse.urlsplit(self.path)
        if parsed.scheme or parsed.netloc or not self.path.startswith("/"):
            raise DiscordTransportError("Discord requests must use a relative API path")
        if ".." in self.path.split("/"):
            raise DiscordTransportError("Discord request path traversal is prohibited")


@dataclass(frozen=True, slots=True)
class DiscordResponse:
    status: int
    headers: tuple[tuple[str, str], ...]
    body: bytes
    truncated: bool = False


class DiscordTransport(Protocol):
    def send(self, request: DiscordRequest) -> DiscordResponse: ...


def _snowflake(value: str) -> str:
    if not value.isdigit() or value.startswith("0") or int(value) >= 2 ** 64:
        raise DiscordTransportError("route identifier must be a Discord snowflake")
    return value


def guild_channels_request(guild_id: str) -> DiscordRequest:
    guild_id = _snowflake(guild_id)
    return DiscordRequest("guild-channels",f"/guilds/{guild_id}/channels",(),guild_id)


def guild_search_request(guild_id: str, *, content: str, channel_ids: tuple[str, ...], limit: int, offset: int, min_id: str | None, max_id: str | None) -> DiscordRequest:
    guild_id = _snowflake(guild_id)
    if not 1 <= limit <= 25:
        raise DiscordTransportError("search limit must be between 1 and 25")
    if not 0 <= offset <= 9975:
        raise DiscordTransportError("search offset must be between 0 and 9975")
    query: list[tuple[str,str]] = [("content",content),("limit",str(limit)),("offset",str(offset))]
    query.extend(("channel_id",_snowflake(channel_id)) for channel_id in channel_ids)
    if min_id is not None:
        query.append(("min_id",_snowflake(min_id)))
    if max_id is not None:
        query.append(("max_id",_snowflake(max_id)))
    return DiscordRequest("guild-search",f"/guilds/{guild_id}/messages/search",tuple(query),guild_id)
~~~

- [ ] **Step 4: Add a no-redirect production transport**

Append to `src/gather/discord_transport.py`:

~~~python
class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        raise DiscordTransportError("Discord API redirects are refused")


class DiscordHTTPTransport:
    __slots__ = ("_authorization","_timeout","_max_body")

    def __init__(self, authorization: str, *, timeout: float = 20.0, max_body: int = DISCORD_MAX_BODY) -> None:
        if not authorization.startswith("Bot ") or "\r" in authorization or "\n" in authorization:
            raise DiscordTransportError("Discord authorization must be a single-line Bot header")
        self._authorization = authorization
        self._timeout = timeout
        self._max_body = max_body

    def __repr__(self) -> str:
        return "DiscordHTTPTransport(authorization=<redacted>)"

    def send(self, request: DiscordRequest) -> DiscordResponse:
        encoded = urllib.parse.urlencode(request.query, doseq=True)
        url = f"{DISCORD_API_ORIGIN}{DISCORD_API_PREFIX}{request.path}"
        if encoded:
            url = f"{url}?{encoded}"
        req = urllib.request.Request(url,headers={"Authorization":self._authorization,"User-Agent":DEFAULT_UA,"Accept":"application/json"})
        opener = urllib.request.build_opener(_NoRedirect)
        try:
            with opener.open(req, timeout=self._timeout) as response:
                raw = response.read(self._max_body + 1)
                return DiscordResponse(int(response.status),tuple(response.headers.items()),raw[:self._max_body],len(raw) > self._max_body)
        except DiscordTransportError:
            raise
        except urllib.error.HTTPError as exc:
            if 300 <= exc.code < 400:
                raise DiscordTransportError("Discord API redirects are refused") from exc
            raw = exc.read(self._max_body + 1) if exc.fp else b""
            return DiscordResponse(exc.code,tuple((exc.headers or {}).items()),raw[:self._max_body],len(raw) > self._max_body)
        except (urllib.error.URLError,socket.timeout,TimeoutError) as exc:
            raise DiscordTransportError(f"Discord transport failed: {type(exc).__name__}") from exc
~~~

- [ ] **Step 5: Run transport tests and static checks**

Run:

~~~powershell
python -m pytest tests/test_discord_transport.py -q
python -m ruff check src/gather/discord_transport.py tests/test_discord_transport.py
python -m mypy src/gather/discord_transport.py
~~~

Expected: all commands pass without network access.

- [ ] **Step 6: Commit the official-origin edge**

Run:

~~~powershell
git add src/gather/discord_transport.py tests/test_discord_transport.py
git commit -m "feat(discord): pin official bot transport"
~~~

Expected: one commit containing only the transport module and its tests.

### Task 3: Deterministic Rate, Retry, and Search-Indexing State

**Files:**
- Modify: `src/gather/discord_transport.py`
- Modify: `tests/test_discord_transport.py`

**Interfaces:**
- Consumes: `DiscordTransport.send(request) -> DiscordResponse`.
- Produces: `RetryPolicy`, `RetryEvent`, `DiscordExchange`, and `DiscordClient.execute(request, *, indexing=False)`.

- [ ] **Step 1: Write failing 202 and 429 timing tests**

Append to `tests/test_discord_transport.py`:

~~~python
from gather.discord_transport import DiscordClient, DiscordResponse, RetryPolicy


class ScriptedTransport:
    def __init__(self, *responses: DiscordResponse) -> None:
        self.responses = list(responses)
        self.calls: list[DiscordRequest] = []

    def send(self, request: DiscordRequest) -> DiscordResponse:
        self.calls.append(request)
        return self.responses.pop(0)


def _response(status: int, body: dict, **headers: str) -> DiscordResponse:
    return DiscordResponse(status,tuple(headers.items()),json.dumps(body).encode("utf-8"))


def test_client_honors_202_retry_after_without_real_sleep() -> None:
    sleeps: list[float] = []
    transport = ScriptedTransport(_response(202,{"retry_after":0}),_response(200,{"messages":[],"total_results":0}))
    client = DiscordClient(transport,policy=RetryPolicy(1,1,1),clock=lambda:10.0,sleep=sleeps.append,jitter=lambda _:0.0)
    exchange = client.execute(guild_channels_request("1080142797870485606"),indexing=True)
    assert exchange.response.status == 200
    assert sleeps == [0.25]
    assert exchange.events[0].kind == "indexing"


def test_client_honors_global_429_body_and_header() -> None:
    sleeps: list[float] = []
    transport = ScriptedTransport(_response(429,{"retry_after":2.5,"global":True},**{"Retry-After":"2.0","X-RateLimit-Scope":"global"}),_response(200,{}))
    client = DiscordClient(transport,policy=RetryPolicy(1,1,1),clock=lambda:10.0,sleep=sleeps.append,jitter=lambda _:0.0)
    exchange = client.execute(guild_channels_request("1080142797870485606"))
    assert sleeps == [2.5]
    assert exchange.events[0].scope == "global"
~~~

- [ ] **Step 2: Run the retry tests and observe the red state**

Run:

~~~powershell
python -m pytest tests/test_discord_transport.py -k "retry_after or global_429" -q
~~~

Expected: FAIL because `DiscordClient` and its receipt types do not exist.

- [ ] **Step 3: Add retry result types and bounded policy**

Append to `src/gather/discord_transport.py`:

~~~python
@dataclass(frozen=True, slots=True)
class RetryPolicy:
    rate_retries: int
    indexing_retries: int
    server_retries: int
    zero_retry_delay: float = 0.25
    server_backoff: float = 0.5
    max_wait: float = 120.0


@dataclass(frozen=True, slots=True)
class RetryEvent:
    kind: str
    status: int
    wait_seconds: float
    scope: str
    attempt: int


@dataclass(frozen=True, slots=True)
class DiscordExchange:
    response: DiscordResponse
    events: tuple[RetryEvent, ...]
    attempts: int


def _header(response: DiscordResponse, name: str) -> str:
    target = name.casefold()
    return next((value for key,value in response.headers if key.casefold() == target),"")


def _body_object(response: DiscordResponse) -> dict[str, object]:
    if response.truncated:
        raise DiscordTransportError("Discord response body was truncated")
    try:
        parsed = json.loads(response.body)
    except (UnicodeDecodeError,json.JSONDecodeError) as exc:
        raise DiscordTransportError("Discord response was not complete JSON") from exc
    if not isinstance(parsed, dict):
        raise DiscordTransportError("Discord response must be a JSON object")
    return parsed


def _retry_seconds(response: DiscordResponse, *, zero_delay: float) -> float:
    body = _body_object(response)
    values: list[float] = []
    for candidate in (_header(response,"Retry-After"),body.get("retry_after")):
        try:
            values.append(float(candidate))
        except (TypeError,ValueError):
            pass
    seconds = max(values, default=0.0)
    return seconds if seconds > 0 else zero_delay
~~~

- [ ] **Step 4: Add the retry state machine**

Append to `src/gather/discord_transport.py`:

~~~python
class DiscordClient:
    def __init__(self, transport: DiscordTransport, *, policy: RetryPolicy, clock: Callable[[],float] = time.monotonic, sleep: Callable[[float],None] = time.sleep, jitter: Callable[[int],float] = lambda _:0.0) -> None:
        self._transport = transport
        self._policy = policy
        self._clock = clock
        self._sleep = sleep
        self._jitter = jitter
        self._global_until = 0.0
        self._route_buckets: dict[tuple[str,str],str] = {}
        self._bucket_until: dict[tuple[str,str],float] = {}

    def _wait(self, seconds: float) -> None:
        if seconds < 0 or seconds > self._policy.max_wait:
            raise DiscordTransportError("Discord retry wait exceeded the sealed policy")
        self._sleep(seconds)

    def execute(self, request: DiscordRequest, *, indexing: bool = False) -> DiscordExchange:
        events: list[RetryEvent] = []
        rate_attempts = indexing_attempts = server_attempts = attempts = 0
        while True:
            global_wait = max(0.0,self._global_until - self._clock())
            if global_wait:
                self._wait(global_wait)
            route_key = (request.operation,request.major_id)
            bucket = self._route_buckets.get(route_key)
            if bucket:
                bucket_wait = max(0.0,self._bucket_until.get((bucket,request.major_id),0.0) - self._clock())
                if bucket_wait:
                    self._wait(bucket_wait)
            attempts += 1
            response = self._transport.send(request)
            if response.status == 202 and indexing:
                if indexing_attempts >= self._policy.indexing_retries:
                    return DiscordExchange(response,tuple(events),attempts)
                indexing_attempts += 1
                wait = _retry_seconds(response,zero_delay=self._policy.zero_retry_delay)
                events.append(RetryEvent("indexing",202,wait,"search",indexing_attempts))
                self._wait(wait)
                continue
            if response.status == 429:
                if rate_attempts >= self._policy.rate_retries:
                    return DiscordExchange(response,tuple(events),attempts)
                rate_attempts += 1
                wait = _retry_seconds(response,zero_delay=self._policy.zero_retry_delay)
                scope = _header(response,"X-RateLimit-Scope") or "user"
                if scope == "global":
                    self._global_until = max(self._global_until,self._clock() + wait)
                else:
                    self._wait(wait)
                events.append(RetryEvent("rate-limit",429,wait,scope,rate_attempts))
                continue
            if 500 <= response.status < 600:
                if server_attempts >= self._policy.server_retries:
                    return DiscordExchange(response,tuple(events),attempts)
                server_attempts += 1
                wait = self._policy.server_backoff * (2 ** (server_attempts - 1)) + self._jitter(server_attempts)
                events.append(RetryEvent("server",response.status,wait,"route",server_attempts))
                self._wait(wait)
                continue
            bucket = _header(response,"X-RateLimit-Bucket")
            remaining = _header(response,"X-RateLimit-Remaining")
            reset_after = _header(response,"X-RateLimit-Reset-After")
            if bucket:
                self._route_buckets[route_key] = bucket
            if bucket and remaining == "0" and reset_after:
                wait = float(reset_after)
                if wait < 0 or wait > self._policy.max_wait:
                    raise DiscordTransportError("Discord bucket reset exceeded the sealed policy")
                self._bucket_until[(bucket,request.major_id)] = self._clock() + wait
                events.append(RetryEvent("proactive",response.status,wait,"bucket",attempts))
            return DiscordExchange(response,tuple(events),attempts)
~~~

- [ ] **Step 5: Add terminal and malformed response tests**

Append to `tests/test_discord_transport.py`:

~~~python
@pytest.mark.parametrize("status",[401,403,404])
def test_client_does_not_retry_terminal_statuses(status: int) -> None:
    transport = ScriptedTransport(_response(status,{"message":"fixture failure"}))
    client = DiscordClient(transport,policy=RetryPolicy(3,3,3),sleep=lambda _:pytest.fail("terminal response must not sleep"))
    result = client.execute(guild_channels_request("1080142797870485606"))
    assert result.response.status == status
    assert result.attempts == 1


def test_truncated_index_response_fails_closed() -> None:
    transport = ScriptedTransport(DiscordResponse(202,(),b'{"retry_after":1',True))
    client = DiscordClient(transport,policy=RetryPolicy(1,1,1),sleep=lambda _:None)
    with pytest.raises(DiscordTransportError,match="truncated"):
        client.execute(guild_channels_request("1080142797870485606"),indexing=True)
~~~

- [ ] **Step 6: Run retry tests and existing network regressions**

Run:

~~~powershell
python -m pytest tests/test_discord_transport.py tests/test_fetch.py tests/test_net.py -q
python -m ruff check src/gather/discord_transport.py tests/test_discord_transport.py
python -m mypy src/gather/discord_transport.py
~~~

Expected: all commands pass; no test sleeps in real time.

- [ ] **Step 7: Commit the state machine**

Run:

~~~powershell
git add src/gather/discord_transport.py tests/test_discord_transport.py
git commit -m "feat(discord): honor rate and indexing state"
~~~

Expected: one focused transport-state commit.

### Task 4: Deterministic Redaction and Attachment Descriptors

**Files:**
- Create: `src/gather/discord_redaction.py`
- Create: `tests/test_discord_redaction.py`
- Create: `tests/fixtures/discord/message-sensitive.json`

**Interfaces:**
- Consumes: one transient Discord message mapping, guild/channel IDs, plan digest, and exact response-body hash.
- Produces: `AttachmentDescriptor`, `RedactedMessage`, `redact_message(...)`, `response_body_sha256(body)`, and `assert_durable_private_data_free(value)`.

- [ ] **Step 1: Add a secret-free sensitive-message fixture**

Write `tests/fixtures/discord/message-sensitive.json`:

~~~json
{"id":"1456789012345678901","channel_id":"1081121447960915989","guild_id":"1080142797870485606","content":"Operator <@123456789012345678> measured PQ_M2 = 78.84375; see https://example.com/paper?q=pq and <#1081121447960915989>.","timestamp":"2026-07-09T00:00:00.000000+00:00","edited_timestamp":null,"author":{"id":"123456789012345678","username":"operator","global_name":"Operator","avatar":"fixture-avatar"},"member":{"nick":"Display Person","roles":["234567890123456789"]},"mentions":[{"id":"123456789012345678","username":"operator","global_name":"Operator"}],"mention_roles":["234567890123456789"],"attachments":[{"id":"345678901234567890","filename":"../Operator-results.csv","content_type":"text/csv","size":128,"width":null,"height":null,"url":"https://cdn.discordapp.com/attachments/1/2/Operator-results.csv?ex=fixture&is=fixture&hm=fixture","proxy_url":"https://media.discordapp.net/attachments/1/2/Operator-results.csv?token=fixture"}],"embeds":[{"title":"External paper","url":"https://example.com/paper?q=pq","description":"Technical evidence"}],"message_reference":{"message_id":"1456789012345678800","channel_id":"1081121447960915989","guild_id":"1080142797870485606"}}
~~~

- [ ] **Step 2: Write the failing golden redaction test**

Create `tests/test_discord_redaction.py`:

~~~python
import json
from pathlib import Path

from gather.discord_redaction import assert_durable_private_data_free, redact_message, response_body_sha256

FIXTURE = Path(__file__).parent / "fixtures" / "discord" / "message-sensitive.json"


def test_redaction_removes_identity_and_signed_urls_but_preserves_technical_text() -> None:
    raw = FIXTURE.read_bytes()
    redacted = redact_message(json.loads(raw),guild_id="1080142797870485606",channel_id="1081121447960915989",thread_id=None,plan_digest="a" * 64,response_body_sha256=response_body_sha256(raw))
    durable = redacted.as_dict()
    encoded = json.dumps(durable,sort_keys=True,ensure_ascii=False)
    assert "PQ_M2 = 78.84375" in encoded
    assert "[user]" in encoded and "[channel]" in encoded
    assert "Operator" not in encoded
    assert "123456789012345678" not in encoded
    assert "fixture-avatar" not in encoded
    assert "raw_json" not in encoded
    assert "cdn.discordapp.com" not in encoded
    assert durable["attachments"][0]["filename"] == "[user]-results.csv"
    assert len(durable["attachments"][0]["descriptor_sha256"]) == 64
    assert_durable_private_data_free(durable)
~~~

- [ ] **Step 3: Run the golden test and observe the red state**

Run:

~~~powershell
python -m pytest tests/test_discord_redaction.py::test_redaction_removes_identity_and_signed_urls_but_preserves_technical_text -q
~~~

Expected: FAIL during collection because `gather.discord_redaction` does not exist.

- [ ] **Step 4: Add immutable redaction types and hashes**

Create `src/gather/discord_redaction.py` with:

~~~python
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
import urllib.parse
from dataclasses import asdict, dataclass
from pathlib import PurePath
from typing import Any, Mapping

MENTION_USER = re.compile(r"<@!?\d+>")
MENTION_ROLE = re.compile(r"<@&\d+>")
MENTION_CHANNEL = re.compile(r"<#\d+>")
SIGNED_DISCORD_HOSTS = frozenset({"cdn.discordapp.com","media.discordapp.net","cdn.discord.com"})
FORBIDDEN_KEYS = frozenset({"author","author_id","username","global_name","display_name","avatar","member","members","roles","raw_json","authorization","token","proxy_url","url"})


class RedactionError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class AttachmentDescriptor:
    attachment_id: str
    filename: str
    mime: str
    size: int
    width: int | None
    height: int | None
    descriptor_sha256: str


@dataclass(frozen=True, slots=True)
class RedactedMessage:
    schema: str
    classification: str
    guild_id: str
    channel_id: str
    thread_id: str | None
    message_id: str
    timestamp: str
    edited_timestamp: str | None
    content: str
    canonical_url: str
    reply_to: dict[str,str] | None
    attachments: tuple[AttachmentDescriptor,...]
    public_links: tuple[str,...]
    source_message_sha256: str
    response_body_sha256: str
    redaction_policy: str
    plan_digest: str

    def as_dict(self) -> dict[str,Any]:
        value = asdict(self)
        value["attachments"] = [asdict(item) for item in self.attachments]
        value["public_links"] = list(self.public_links)
        return value


def response_body_sha256(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _canonical_hash(value: object) -> str:
    encoded = json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
~~~

- [ ] **Step 5: Add identity, URL, attachment, and privacy functions**

Append to `src/gather/discord_redaction.py`:

~~~python
def _identity_lexicon(message: Mapping[str,Any]) -> tuple[str,...]:
    values: set[str] = set()
    records: list[object] = [message.get("author"),message.get("member"),*(message.get("mentions") or [])]
    for record in records:
        if isinstance(record, Mapping):
            for key in ("username","global_name","display_name","nick"):
                value = record.get(key)
                if isinstance(value,str) and value.strip():
                    values.add(value.strip())
    return tuple(sorted(values,key=lambda value:(-len(value),value.casefold())))


def _redact_text(text: str, identities: tuple[str,...]) -> str:
    value = unicodedata.normalize("NFC",text)
    value = MENTION_USER.sub("[user]",value)
    value = MENTION_ROLE.sub("[role]",value)
    value = MENTION_CHANNEL.sub("[channel]",value)
    value = value.replace("@everyone","[everyone]").replace("@here","[here]")
    for identity in identities:
        value = re.sub(re.escape(identity),"[user]",value,flags=re.IGNORECASE)
    return value


def _public_url(value: object) -> str | None:
    if not isinstance(value,str):
        return None
    parsed = urllib.parse.urlsplit(value.strip())
    if parsed.scheme not in {"http","https"} or not parsed.hostname or parsed.hostname.casefold() in SIGNED_DISCORD_HOSTS:
        return None
    safe_query = urllib.parse.urlencode([(key,item) for key,item in urllib.parse.parse_qsl(parsed.query,keep_blank_values=True) if key.casefold() not in {"token","signature","sig","auth","key","ex","is","hm"}])
    return urllib.parse.urlunsplit((parsed.scheme,parsed.netloc,parsed.path,safe_query,""))


def _attachment(value: Mapping[str,Any], identities: tuple[str,...]) -> AttachmentDescriptor:
    attachment_id = str(value.get("id",""))
    if not attachment_id.isdigit():
        raise RedactionError("attachment id must be a Discord snowflake")
    raw_name = PurePath(str(value.get("filename") or "attachment")).name
    filename = _redact_text(raw_name,identities)
    filename = "".join(ch for ch in filename if ch >= " " and ch not in "\\/:*?\"<>|")[:180] or "attachment"
    core = {"attachment_id":attachment_id,"filename":filename,"mime":str(value.get("content_type") or "application/octet-stream"),"size":int(value.get("size") or 0),"width":value.get("width") if isinstance(value.get("width"),int) else None,"height":value.get("height") if isinstance(value.get("height"),int) else None}
    return AttachmentDescriptor(**core,descriptor_sha256=_canonical_hash(core))


def assert_durable_private_data_free(value: object) -> None:
    if isinstance(value,Mapping):
        for key,item in value.items():
            if str(key).casefold() in FORBIDDEN_KEYS:
                raise RedactionError(f"durable payload contains forbidden key: {key}")
            assert_durable_private_data_free(item)
    elif isinstance(value,(list,tuple)):
        for item in value:
            assert_durable_private_data_free(item)
    elif isinstance(value,str):
        lowered = value.casefold()
        if "authorization:" in lowered or "bot fixture-secret" in lowered:
            raise RedactionError("durable payload contains credential-shaped text")
        parsed = urllib.parse.urlsplit(value)
        if parsed.hostname and parsed.hostname.casefold() in SIGNED_DISCORD_HOSTS and parsed.query:
            raise RedactionError("durable payload contains a signed Discord URL")
~~~

- [ ] **Step 6: Add the redaction entry point**

Append to `src/gather/discord_redaction.py`:

~~~python
def redact_message(message: Mapping[str,Any], *, guild_id: str, channel_id: str, thread_id: str | None, plan_digest: str, response_body_sha256: str) -> RedactedMessage:
    message_id = str(message.get("id",""))
    payload_channel = str(message.get("channel_id",channel_id))
    payload_guild = str(message.get("guild_id",guild_id))
    for label,value in (("message_id",message_id),("channel_id",channel_id),("guild_id",guild_id),("payload channel_id",payload_channel),("payload guild_id",payload_guild)):
        if not value.isdigit() or value.startswith("0"):
            raise RedactionError(f"{label} must be a Discord snowflake")
    if payload_channel != channel_id or payload_guild != guild_id:
        raise RedactionError("message locator does not match the approved scope")
    if thread_id is not None and thread_id != channel_id:
        raise RedactionError("thread locator does not match the approved lane")
    identities = _identity_lexicon(message)
    reference = message.get("message_reference")
    reply_to = None
    if isinstance(reference,Mapping) and reference.get("message_id"):
        reply_to = {"guild_id":str(reference.get("guild_id") or guild_id),"channel_id":str(reference.get("channel_id") or channel_id),"message_id":str(reference["message_id"])}
    attachments = tuple(_attachment(value,identities) for value in (message.get("attachments") or []) if isinstance(value,Mapping))
    links: set[str] = set()
    for candidate in re.findall(r"https?://[^\s<>]+",str(message.get("content") or "")):
        if safe := _public_url(candidate):
            links.add(safe)
    for embed in message.get("embeds") or []:
        if isinstance(embed,Mapping) and (safe := _public_url(embed.get("url"))):
            links.add(safe)
    redacted = RedactedMessage("gather.discord-message/v1","community_claim",guild_id,channel_id,thread_id,message_id,str(message.get("timestamp") or ""),str(message["edited_timestamp"]) if message.get("edited_timestamp") is not None else None,_redact_text(str(message.get("content") or ""),identities),f"https://discord.com/channels/{guild_id}/{channel_id}/{message_id}",reply_to,attachments,tuple(sorted(links)),_canonical_hash(message),response_body_sha256,"discord-technical-v1",plan_digest)
    assert_durable_private_data_free(redacted.as_dict())
    return redacted
~~~

- [ ] **Step 7: Run redaction tests and static checks**

Run:

~~~powershell
python -m pytest tests/test_discord_redaction.py -q
python -m ruff check src/gather/discord_redaction.py tests/test_discord_redaction.py
python -m mypy src/gather/discord_redaction.py
~~~

Expected: all commands pass; fixture identity and signed attachment values are absent from every durable value.

- [ ] **Step 8: Commit deterministic redaction**

Run:

~~~powershell
git add src/gather/discord_redaction.py tests/test_discord_redaction.py tests/fixtures/discord/message-sensitive.json
git commit -m "feat(discord): redact identities and attachments"
~~~

Expected: one commit containing the redactor, fixture, and tests.

### Task 5: Canonical Message and Discovery-Edge Receipts

**Files:**
- Create: `src/gather/discord_receipts.py`
- Create: `tests/test_discord_receipts.py`
- Modify: `src/gather/method.py:13-22`
- Test: `tests/test_method.py`
- Test: `tests/test_store.py`

**Interfaces:**
- Consumes: `RedactedMessage` and Gather's `make_item(...) -> Item`.
- Produces: `DiscoveryEdge`, `message_item(message, *, fetched_at)`, and `discovery_edge_item(edge, *, fetched_at)`.

- [ ] **Step 1: Write failing message/edge separation tests**

Create `tests/test_discord_receipts.py`:

~~~python
import json
from pathlib import Path

from gather.discord_receipts import DiscoveryEdge, discovery_edge_item, message_item
from gather.discord_redaction import redact_message, response_body_sha256
from gather.store import Corpus

FIXTURE = Path(__file__).parent / "fixtures" / "discord" / "message-sensitive.json"


def _redacted():
    raw = FIXTURE.read_bytes()
    return redact_message(
        json.loads(raw),
        guild_id="1080142797870485606",
        channel_id="1081121447960915989",
        thread_id=None,
        plan_digest="a" * 64,
        response_body_sha256=response_body_sha256(raw),
    )


def test_message_receipt_is_neutral_across_discovery_queries() -> None:
    message = message_item(_redacted(),fetched_at=1.0)
    first = discovery_edge_item(DiscoveryEdge(
        plan_digest="a" * 64,
        query_hash="b" * 64,
        guild_id="1080142797870485606",
        channel_id="1081121447960915989",
        thread_id=None,
        message_id="1456789012345678901",
        message_receipt_sha256=message.provenance.sha256,
        discovery_method="discord-api-search-edge",
        min_id=None,
        max_id=None,
        offset=0,
        rank=0,
        response_body_sha256="c" * 64,
    ),fetched_at=1.0)
    second = discovery_edge_item(DiscoveryEdge(
        plan_digest="a" * 64,
        query_hash="d" * 64,
        guild_id="1080142797870485606",
        channel_id="1081121447960915989",
        message_id="1456789012345678901",
        message_receipt_sha256=message.provenance.sha256,
        discovery_method="discord-api-search-edge",
        min_id=None,
        max_id=None,
        offset=25,
        rank=0,
        response_body_sha256="e" * 64,
    ),fetched_at=2.0)
    assert message.provenance.method == "discord-api-message"
    assert first.provenance.sha256 != second.provenance.sha256
    assert first.provenance.method == second.provenance.method == "discord-api-search-edge"


def test_message_and_edges_round_trip_without_mutable_meta(tmp_path) -> None:
    message = message_item(_redacted(),fetched_at=1.0)
    edge = discovery_edge_item(DiscoveryEdge("a" * 64,"b" * 64,"1080142797870485606","1081121447960915989","1456789012345678901",message.provenance.sha256,"discord-api-search-edge",None,None,0,0,"c" * 64),fetched_at=1.0)
    corpus = Corpus(str(tmp_path),fsync=False)
    corpus.add([message,edge,message])
    rows = list(corpus.rows())
    assert len(rows) == 2
    assert all(row["meta"] == {} for row in rows)
    assert all(corpus.load_item(row).verify() for row in rows)
~~~

- [ ] **Step 2: Run receipt tests and observe the red state**

Run:

~~~powershell
python -m pytest tests/test_discord_receipts.py -q
~~~

Expected: FAIL during collection because `gather.discord_receipts` does not exist.

- [ ] **Step 3: Register direct Discord receipt methods**

Modify `src/gather/method.py` so `DIRECT_METHODS` contains:

~~~python
    "discord-api-message",
    "discord-api-search-edge",
    "discord-api-history-edge",
~~~

Add to `tests/test_method.py`:

~~~python
def test_discord_messages_and_discovery_edges_are_direct_api_evidence() -> None:
    for method in (
        "discord-api-message",
        "discord-api-search-edge",
        "discord-api-history-edge",
    ):
        assert directness(method) == DIRECT
        assert consistent(method,False) is True
        assert consistent(method,True) is False
~~~

- [ ] **Step 4: Add canonical receipt builders**

Create `src/gather/discord_receipts.py`:

~~~python
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass

from gather.item import Item, make_item
from gather.discord_redaction import (
    RedactedMessage,
    assert_durable_private_data_free,
)

DISCOVERY_METHODS = frozenset({
    "discord-api-search-edge",
    "discord-api-history-edge",
})


@dataclass(frozen=True, slots=True)
class DiscoveryEdge:
    plan_digest: str
    query_hash: str
    guild_id: str
    channel_id: str
    message_id: str
    message_receipt_sha256: str
    discovery_method: str
    min_id: str | None
    max_id: str | None
    offset: int
    rank: int
    response_body_sha256: str


def _canonical(value: object) -> str:
    return json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False)


def message_item(message: RedactedMessage, *, fetched_at: float) -> Item:
    payload = message.as_dict()
    assert_durable_private_data_free(payload)
    return make_item(
        kind="community_claim",
        id=f"{message.guild_id}:{message.channel_id}:{message.message_id}",
        title=f"Discord technical message {message.message_id}",
        text=_canonical(payload),
        source="discord",
        ref=f"discord://message/{message.guild_id}/{message.channel_id}/{message.message_id}/{message.plan_digest}",
        method="discord-api-message",
        fetched_at=fetched_at,
        meta={},
    )


def discovery_edge_item(edge: DiscoveryEdge, *, fetched_at: float) -> Item:
    if edge.discovery_method not in DISCOVERY_METHODS:
        raise ValueError(f"unknown Discord discovery method: {edge.discovery_method}")
    payload = {
        "schema":"gather.discord-discovery-edge/v1",
        **asdict(edge),
    }
    assert_durable_private_data_free(payload)
    text = _canonical(payload)
    edge_id = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return make_item(
        kind="discovery_edge",
        id=edge_id,
        title=f"Discord discovery edge {edge_id[:16]}",
        text=text,
        source="discord",
        ref=f"discord://discovery/{edge.plan_digest}/{edge.query_hash}/{edge.message_id}",
        method=edge.discovery_method,
        fetched_at=fetched_at,
        meta={},
    )
~~~

- [ ] **Step 5: Run receipt, method, and corpus tests**

Run:

~~~powershell
python -m pytest tests/test_discord_receipts.py tests/test_method.py tests/test_store.py -q
python -m ruff check src/gather/discord_receipts.py src/gather/method.py tests/test_discord_receipts.py tests/test_method.py
python -m mypy src/gather/discord_receipts.py src/gather/method.py
~~~

Expected: all commands pass. The corpus holds one canonical message and both search edges.

- [ ] **Step 6: Commit sealed message/edge provenance**

Run:

~~~powershell
git add src/gather/discord_receipts.py src/gather/method.py tests/test_discord_receipts.py tests/test_method.py
git commit -m "feat(discord): separate messages from discovery edges"
~~~

Expected: one commit containing only the receipt contract, method registration, and tests.

### Task 6: Metadata-Only Scope and Permission Preflight

**Files:**
- Create: `src/gather/discord_preflight.py`
- Create: `tests/test_discord_preflight.py`
- Modify: `src/gather/discord_transport.py`
- Modify: `tests/test_discord_transport.py`

**Interfaces:**
- Consumes: `SealedCapturePlan` and `DiscordClient.execute(...) -> DiscordExchange`.
- Produces: typed metadata request factories, `ChannelCapability`, `GuildPreflight`, `PreflightReceipt`, `effective_channel_permissions(...)`, and `preflight_plan(plan, *, client)`.

- [ ] **Step 1: Add typed metadata request factories**

Append to `src/gather/discord_transport.py`:

~~~python
def current_user_request() -> DiscordRequest:
    return DiscordRequest("current-user","/users/@me",(),"@me")


def current_application_request() -> DiscordRequest:
    return DiscordRequest("current-application","/oauth2/applications/@me",(),"@me")


def guild_request(guild_id: str) -> DiscordRequest:
    guild_id = _snowflake(guild_id)
    return DiscordRequest("guild",f"/guilds/{guild_id}",(),guild_id)


def current_guild_member_request(guild_id: str) -> DiscordRequest:
    guild_id = _snowflake(guild_id)
    return DiscordRequest("current-guild-member",f"/users/@me/guilds/{guild_id}/member",(),guild_id)


def active_threads_request(guild_id: str) -> DiscordRequest:
    guild_id = _snowflake(guild_id)
    return DiscordRequest("active-threads",f"/guilds/{guild_id}/threads/active",(),guild_id)


def public_archived_threads_request(
    channel_id: str,
    *,
    before: str | None,
    limit: int,
) -> DiscordRequest:
    channel_id = _snowflake(channel_id)
    if not 1 <= limit <= 100:
        raise DiscordTransportError("archived-thread limit must be between 1 and 100")
    query = [("limit",str(limit))]
    if before is not None:
        query.append(("before",before))
    return DiscordRequest(
        "public-archived-threads",
        f"/channels/{channel_id}/threads/archived/public",
        tuple(query),
        channel_id,
    )
~~~

Append to `tests/test_discord_transport.py`:

~~~python
from gather.discord_transport import public_archived_threads_request


def test_only_public_archived_thread_route_is_exposed() -> None:
    request = public_archived_threads_request(
        "1081121447960915989",before=None,limit=100)
    assert request.path.endswith("/threads/archived/public")
    assert "private" not in request.path
~~~

- [ ] **Step 2: Write failing permission and private-thread tests**

Create `tests/test_discord_preflight.py`:

~~~python
import json

import pytest

from gather.discord_preflight import (
    ADMINISTRATOR,
    READ_MESSAGE_HISTORY,
    VIEW_CHANNEL,
    PreflightError,
    discover_guild_channels,
    effective_channel_permissions,
    preflight_plan,
)


def test_channel_permission_order_matches_discord_overwrite_rules() -> None:
    permissions = effective_channel_permissions(
        guild_id="1080142797870485606",
        user_id="123456789012345678",
        member_role_ids=("234567890123456789",),
        roles={
            "1080142797870485606": VIEW_CHANNEL,
            "234567890123456789": READ_MESSAGE_HISTORY,
        },
        overwrites=(
            {"id":"1080142797870485606","type":0,"allow":"0","deny":str(READ_MESSAGE_HISTORY)},
            {"id":"234567890123456789","type":0,"allow":str(READ_MESSAGE_HISTORY),"deny":"0"},
        ),
    )
    assert permissions & VIEW_CHANNEL
    assert permissions & READ_MESSAGE_HISTORY
    assert not permissions & ADMINISTRATOR


def test_private_thread_type_is_rejected() -> None:
    from gather.discord_preflight import classify_thread
    with pytest.raises(PreflightError,match="private"):
        classify_thread(
            {"id":"345678901234567890","type":12,"parent_id":"1081121447960915989"},
            approved_parents={"1081121447960915989"},
        )
~~~

- [ ] **Step 3: Run preflight tests and observe the red state**

Run:

~~~powershell
python -m pytest tests/test_discord_preflight.py -q
~~~

Expected: FAIL during collection because `gather.discord_preflight` does not exist.

- [ ] **Step 4: Implement deterministic permission evaluation**

Create `src/gather/discord_preflight.py`:

~~~python
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

from gather.discord_plan import GuildScope, SealedCapturePlan, authorized_guild_id
from gather.discord_transport import (
    DiscordClient,
    active_threads_request,
    current_application_request,
    current_guild_member_request,
    current_user_request,
    guild_channels_request,
    guild_request,
    public_archived_threads_request,
)
from gather.discord_redaction import assert_durable_private_data_free

ADMINISTRATOR = 1 << 3
VIEW_CHANNEL = 1 << 10
READ_MESSAGE_HISTORY = 1 << 16
GATEWAY_MESSAGE_CONTENT = 1 << 18
GATEWAY_MESSAGE_CONTENT_LIMITED = 1 << 19
PUBLIC_CHANNEL_TYPES = frozenset({0,5,15,16})
PUBLIC_THREAD_TYPES = frozenset({10,11})
PRIVATE_CHANNEL_TYPES = frozenset({1,3,12})


class PreflightError(RuntimeError):
    pass


def _apply(base: int, allow: int, deny: int) -> int:
    return (base & ~deny) | allow


def effective_channel_permissions(
    *,
    guild_id: str,
    user_id: str,
    member_role_ids: Sequence[str],
    roles: Mapping[str,int],
    overwrites: Sequence[Mapping[str,Any]],
) -> int:
    permissions = roles.get(guild_id,0)
    for role_id in member_role_ids:
        permissions |= roles.get(role_id,0)
    if permissions & ADMINISTRATOR:
        return (1 << 53) - 1
    everyone = next((row for row in overwrites if str(row.get("id")) == guild_id and int(row.get("type",-1)) == 0),None)
    if everyone:
        permissions = _apply(permissions,int(everyone.get("allow",0)),int(everyone.get("deny",0)))
    role_allow = role_deny = 0
    for row in overwrites:
        if int(row.get("type",-1)) == 0 and str(row.get("id")) in member_role_ids:
            role_allow |= int(row.get("allow",0))
            role_deny |= int(row.get("deny",0))
    permissions = _apply(permissions,role_allow,role_deny)
    member = next((row for row in overwrites if str(row.get("id")) == user_id and int(row.get("type",-1)) == 1),None)
    if member:
        permissions = _apply(permissions,int(member.get("allow",0)),int(member.get("deny",0)))
    return permissions


def classify_thread(value: Mapping[str,Any], *, approved_parents: set[str]) -> str:
    thread_type = int(value.get("type",-1))
    if thread_type == 12:
        raise PreflightError("private Discord threads are prohibited")
    if thread_type not in PUBLIC_THREAD_TYPES:
        raise PreflightError("thread type is not public")
    if str(value.get("parent_id","")) not in approved_parents:
        raise PreflightError("thread parent is outside the approved scope")
    return str(value["id"])
~~~

- [ ] **Step 5: Add receipt types and metadata-only preflight**

Append to `src/gather/discord_preflight.py`:

~~~python
@dataclass(frozen=True, slots=True)
class ChannelCapability:
    guild_id: str
    channel_id: str
    channel_type: int
    view_channel: bool
    read_message_history: bool
    approved: bool


@dataclass(frozen=True, slots=True)
class GuildPreflight:
    guild_id: str
    returned_guild_id: str
    member: bool
    message_content: bool
    channels: tuple[ChannelCapability,...]
    public_thread_ids: tuple[str,...]
    approved_thread_ids: tuple[str,...]


@dataclass(frozen=True, slots=True)
class PreflightReceipt:
    schema: str
    plan_digest: str
    status: str
    guilds: tuple[GuildPreflight,...]
    message_routes_requested: int

    def as_dict(self) -> dict[str,Any]:
        value = asdict(self)
        assert_durable_private_data_free(value)
        return value


@dataclass(frozen=True, slots=True)
class DiscoveryReceipt:
    schema: str
    federation_id: str
    guild_id: str
    public_channel_ids: tuple[str,...]
    status: str

    def as_dict(self) -> dict[str,Any]:
        value = asdict(self)
        assert_durable_private_data_free(value)
        return value


def _json_object(client: DiscordClient, request) -> dict[str,Any]:
    exchange = client.execute(request)
    if exchange.response.status != 200 or exchange.response.truncated:
        raise PreflightError(f"metadata preflight failed with HTTP {exchange.response.status}")
    value = json.loads(exchange.response.body)
    if not isinstance(value,dict):
        raise PreflightError("metadata preflight response must be an object")
    return value


def _json_list(client: DiscordClient, request) -> list[dict[str,Any]]:
    exchange = client.execute(request)
    if exchange.response.status != 200 or exchange.response.truncated:
        raise PreflightError(f"metadata preflight failed with HTTP {exchange.response.status}")
    value = json.loads(exchange.response.body)
    if not isinstance(value,list):
        raise PreflightError("metadata preflight response must be a list")
    return [row for row in value if isinstance(row,dict)]


def _public_threads(
    scope: GuildScope,
    *,
    client: DiscordClient,
) -> tuple[str,...]:
    if not scope.include_public_threads:
        if scope.threads:
            raise PreflightError("sealed threads require include_public_threads")
        return ()
    discovered: set[str] = set()
    active = _json_object(client,active_threads_request(scope.guild_id))
    for row in active.get("threads",[]):
        if not isinstance(row,dict):
            raise PreflightError("active thread metadata is malformed")
        if int(row.get("type",-1)) == 12:
            raise PreflightError("private Discord threads are prohibited")
        if str(row.get("parent_id","")) not in set(scope.channels):
            continue
        discovered.add(classify_thread(row,approved_parents=set(scope.channels)))
    for parent_id in scope.channels:
        before: str | None = None
        while True:
            page = _json_object(
                client,
                public_archived_threads_request(parent_id,before=before,limit=100),
            )
            rows = page.get("threads")
            if not isinstance(rows,list):
                raise PreflightError("archived public thread metadata is malformed")
            for row in rows:
                if not isinstance(row,dict):
                    raise PreflightError("archived public thread metadata is malformed")
                discovered.add(classify_thread(row,approved_parents={parent_id}))
            if page.get("has_more") is not True:
                break
            if not rows or not isinstance(rows[-1].get("thread_metadata"),dict):
                raise PreflightError("archived public thread cursor is missing")
            next_before = rows[-1]["thread_metadata"].get("archive_timestamp")
            if not isinstance(next_before,str) or next_before == before:
                raise PreflightError("archived public thread cursor did not advance")
            before = next_before
    return tuple(sorted(discovered))


def _capabilities(
    scope: GuildScope,
    *,
    user_id: str,
    member_roles: Sequence[str],
    roles: Mapping[str,int],
    rows: Sequence[Mapping[str,Any]],
) -> tuple[ChannelCapability,...]:
    capabilities: list[ChannelCapability] = []
    for row in rows:
        channel_id = str(row.get("id",""))
        channel_type = int(row.get("type",-1))
        if channel_type in PRIVATE_CHANNEL_TYPES:
            raise PreflightError("private channel metadata is prohibited")
        if channel_type not in PUBLIC_CHANNEL_TYPES:
            continue
        permissions = effective_channel_permissions(
            guild_id=scope.guild_id,user_id=user_id,
            member_role_ids=member_roles,roles=roles,
            overwrites=tuple(row.get("permission_overwrites") or ()),
        )
        capabilities.append(ChannelCapability(
            scope.guild_id,channel_id,channel_type,
            bool(permissions & VIEW_CHANNEL),
            bool(permissions & READ_MESSAGE_HISTORY),
            channel_id in scope.channels,
        ))
    return tuple(sorted(capabilities,key=lambda row: row.channel_id))


def preflight_plan(plan: SealedCapturePlan, *, client: DiscordClient) -> PreflightReceipt:
    current_user = _json_object(client,current_user_request())
    application = _json_object(client,current_application_request())
    user_id = str(current_user.get("id",""))
    flags = int(application.get("flags",0))
    message_content = bool(flags & (GATEWAY_MESSAGE_CONTENT | GATEWAY_MESSAGE_CONTENT_LIMITED))
    guild_receipts: list[GuildPreflight] = []
    for scope in plan.plan.guilds:
        guild = _json_object(client,guild_request(scope.guild_id))
        returned_guild_id = str(guild.get("id",""))
        if returned_guild_id != scope.guild_id:
            raise PreflightError("returned guild does not match sealed guild")
        member = _json_object(client,current_guild_member_request(scope.guild_id))
        roles = {str(row["id"]):int(row.get("permissions",0)) for row in guild.get("roles",[]) if isinstance(row,dict) and "id" in row}
        member_roles = tuple(str(role) for role in member.get("roles",[]))
        raw_channels = _json_list(client,guild_channels_request(scope.guild_id))
        capabilities = _capabilities(
            scope,user_id=user_id,member_roles=member_roles,
            roles=roles,rows=raw_channels,
        )
        approved = {row.channel_id:row for row in capabilities if row.approved}
        if not scope.channels or set(approved) != set(scope.channels):
            raise PreflightError("one or more sealed channels are missing")
        public_threads = _public_threads(scope,client=client)
        if not set(scope.threads) <= set(public_threads):
            raise PreflightError("one or more sealed public threads are missing")
        guild_receipts.append(GuildPreflight(
            scope.guild_id,returned_guild_id,True,message_content,
            capabilities,public_threads,tuple(sorted(scope.threads)),
        ))
    required = [row for guild in guild_receipts for row in guild.channels if row.approved]
    status = "MATCH" if required and message_content and all(
        row.view_channel and row.read_message_history for row in required
    ) else "UNVERIFIABLE"
    return PreflightReceipt("gather.discord-preflight/v1",plan.digest,status,tuple(guild_receipts),0)


def discover_guild_channels(
    federation_id: str,
    *,
    federation_rows: Sequence[dict[str,Any]],
    client: DiscordClient,
) -> DiscoveryReceipt:
    """Discover public IDs; this receipt is not a capture authorization."""
    guild_id = authorized_guild_id(federation_id,federation_rows)
    guild = _json_object(client,guild_request(guild_id))
    if str(guild.get("id","")) != guild_id:
        raise PreflightError("returned guild does not match authorized guild")
    rows = _json_list(client,guild_channels_request(guild_id))
    public_ids: list[str] = []
    for row in rows:
        channel_type = int(row.get("type",-1))
        if channel_type in PRIVATE_CHANNEL_TYPES:
            raise PreflightError("private channel metadata is prohibited")
        if channel_type in PUBLIC_CHANNEL_TYPES:
            public_ids.append(str(row["id"]))
    return DiscoveryReceipt(
        "gather.discord-discovery/v1",federation_id,guild_id,
        tuple(sorted(public_ids)),"METADATA_ONLY_NOT_CAPTURE_AUTHORITY",
    )
~~~

- [ ] **Step 6: Add a fixture-driven no-message-route test**

Append to `tests/test_discord_preflight.py`:

~~~python
def test_preflight_receipt_never_requests_search_or_message_history(monkeypatch) -> None:
    from gather.discord_preflight import preflight_plan
    from gather.discord_transport import DiscordClient, DiscordResponse, RetryPolicy
    from gather.discord_plan import parse_capture_plan
    from pathlib import Path

    root = Path(__file__).parent / "fixtures" / "discord"
    plan = parse_capture_plan(json.loads((root / "plan-valid.json").read_text()),federation_rows=json.loads((root / "federation-valid.json").read_text())["sources"])
    scripted = [
        {"id":"123456789012345678"},
        {"flags":1 << 18},
        {"id":"1080142797870485606","roles":[{"id":"1080142797870485606","permissions":str(VIEW_CHANNEL | READ_MESSAGE_HISTORY)}]},
        {"roles":[]},
        [{"id":"1081121447960915989","type":0,"permission_overwrites":[]}],
        {"threads":[]},
        {"threads":[],"has_more":False},
    ]

    class MetadataTransport:
        def __init__(self) -> None:
            self.requests = []
        def send(self, request):
            self.requests.append(request)
            return DiscordResponse(200,(),json.dumps(scripted.pop(0)).encode())

    transport = MetadataTransport()
    receipt = preflight_plan(plan,client=DiscordClient(transport,policy=RetryPolicy(0,0,0),sleep=lambda _:None))
    assert receipt.message_routes_requested == 0
    assert receipt.status == "MATCH"
    assert all(request.operation not in {"guild-search","channel-history"} for request in transport.requests)


@pytest.mark.parametrize(
    ("scripted","match"),
    [
        (
            [
                {"id":"123456789012345678"},{"flags":1 << 18},
                {"id":"999999999999999999","roles":[]},
            ],
            "returned guild",
        ),
        (
            [
                {"id":"123456789012345678"},{"flags":1 << 18},
                {"id":"1080142797870485606","roles":[]},{"roles":[]},[],
            ],
            "sealed channels are missing",
        ),
        (
            [
                {"id":"123456789012345678"},{"flags":1 << 18},
                {"id":"1080142797870485606","roles":[{"id":"1080142797870485606","permissions":str(VIEW_CHANNEL | READ_MESSAGE_HISTORY)}]},
                {"roles":[]},
                [{"id":"1081121447960915989","type":0,"permission_overwrites":[]}],
                {"threads":[{"id":"345678901234567890","type":12,"parent_id":"1081121447960915989"}]},
            ],
            "private",
        ),
    ],
)
def test_preflight_fails_closed_on_guild_missing_channel_or_private_thread(
    scripted,match,
) -> None:
    plan = _sealed_fixture_plan("plan-valid.json")
    client,transport = _scripted_client(scripted)
    with pytest.raises(PreflightError,match=match):
        preflight_plan(plan,client=client)
    assert all(
        request.operation not in {"guild-search","channel-history"}
        for request in transport.requests
    )


def test_public_thread_pagination_is_controlled_by_plan_flag() -> None:
    enabled = _sealed_fixture_plan("plan-public-thread.json")
    client,transport = _scripted_client([
        {"id":"123456789012345678"},{"flags":1 << 18},
        {"id":"1080142797870485606","roles":[{"id":"1080142797870485606","permissions":str(VIEW_CHANNEL | READ_MESSAGE_HISTORY)}]},
        {"roles":[]},
        [{"id":"1081121447960915989","type":0,"permission_overwrites":[]}],
        {"threads":[]},
        {"threads":[{"id":"345678901234567890","type":11,"parent_id":"1081121447960915989","thread_metadata":{"archive_timestamp":"2026-01-02T00:00:00Z"}}],"has_more":True},
        {"threads":[],"has_more":False},
    ])
    receipt = preflight_plan(enabled,client=client)
    assert receipt.status == "MATCH"
    archived = [request for request in transport.requests if request.operation == "public-archived-threads"]
    assert len(archived) == 2
    assert dict(archived[1].query)["before"] == "2026-01-02T00:00:00Z"

    disabled = _sealed_fixture_plan("plan-no-public-threads.json")
    client,transport = _scripted_client([
        {"id":"123456789012345678"},{"flags":1 << 18},
        {"id":"1080142797870485606","roles":[{"id":"1080142797870485606","permissions":str(VIEW_CHANNEL | READ_MESSAGE_HISTORY)}]},
        {"roles":[]},
        [{"id":"1081121447960915989","type":0,"permission_overwrites":[]}],
    ])
    assert preflight_plan(disabled,client=client).status == "MATCH"
    assert all("thread" not in request.operation for request in transport.requests)


def test_metadata_discovery_returns_only_public_ids_and_does_not_authorize_capture() -> None:
    client,_transport = _scripted_client([
        {"id":"1080142797870485606","name":"must not persist"},
        [{"id":"1081121447960915989","type":0,"name":"must not persist"}],
    ])
    receipt = discover_guild_channels(
        "community-shaders-discord",federation_rows=_federation_rows(),client=client,
    )
    encoded = json.dumps(receipt.as_dict(),sort_keys=True)
    assert receipt.status == "METADATA_ONLY_NOT_CAPTURE_AUTHORITY"
    assert receipt.public_channel_ids == ("1081121447960915989",)
    assert "must not persist" not in encoded
    with pytest.raises(PlanError,match="non-empty"):
        parse_capture_plan(_plan_with_channels([]),federation_rows=_federation_rows())
~~~

Add `_scripted_client`, `_sealed_fixture_plan`, `_federation_rows`, and `_plan_with_channels` as deterministic fixture helpers in the same test file. Add `plan-public-thread.json` with the archived public thread explicitly in `threads`, and `plan-no-public-threads.json` with `include_public_threads=false` and an empty `threads` list. The discovery test deliberately proves that enumeration is not authority: the operator must copy selected public IDs into a new nonempty plan and seal it before capture.

- [ ] **Step 7: Run preflight and transport tests**

Run:

~~~powershell
python -m pytest tests/test_discord_preflight.py tests/test_discord_transport.py -q
python -m ruff check src/gather/discord_preflight.py src/gather/discord_transport.py tests/test_discord_preflight.py
python -m mypy src/gather/discord_preflight.py src/gather/discord_transport.py
~~~

Expected: all commands pass; preflight makes only metadata requests.

- [ ] **Step 8: Commit metadata-only preflight**

Run:

~~~powershell
git add src/gather/discord_preflight.py src/gather/discord_transport.py tests/test_discord_preflight.py tests/test_discord_transport.py
git commit -m "feat(discord): preflight approved public scopes"
~~~

Expected: one commit for metadata routes, permission logic, and preflight receipts.

### Task 7: Query-First Search, Deep Windows, and Explicit History Fallback

**Files:**
- Create: `src/gather/discord_search.py`
- Create: `tests/test_discord_search.py`
- Create: `tests/fixtures/discord/search-page.json`
- Modify: `src/gather/discord_transport.py`
- Modify: `tests/test_discord_transport.py`

**Interfaces:**
- Consumes: `SealedCapturePlan`, `DiscordClient`, `redact_message(...)`, and receipt builders.
- Produces: stable `LaneKey`, `CaptureLane`, moving `PageCursor`, `SearchPage`, `PageObservation`, `query_hash(query)`, `build_capture_lanes(plan)`, `initial_cursor(lane)`, `validate_message_scope(message, lane)`, `parse_search_page(response)`, `parse_history_page(response)`, `advance_search_cursor(cursor, page)`, and `iter_lane_pages(lane, *, start_cursor, client, page_budget, message_budget)`.

- [ ] **Step 1: Add a nested search fixture**

Write `tests/fixtures/discord/search-page.json`:

~~~json
{"doing_deep_historical_index":false,"total_results":10020,"messages":[[{"id":"1456789012345678901","channel_id":"1081121447960915989","guild_id":"1080142797870485606","content":"PQ evidence","timestamp":"2026-07-09T00:00:00Z","edited_timestamp":null,"author":{"id":"123456789012345678","username":"fixture-user"},"attachments":[],"embeds":[]}],[{"id":"1456789012345678800","channel_id":"1081121447960915989","guild_id":"1080142797870485606","content":"paper white evidence","timestamp":"2026-07-08T00:00:00Z","edited_timestamp":null,"author":{"id":"234567890123456789","username":"fixture-user-two"},"attachments":[],"embeds":[]}]],"threads":[],"members":[]}
~~~

- [ ] **Step 2: Write failing nested-page and deep-window tests**

Create `tests/test_discord_search.py`:

~~~python
from pathlib import Path

import pytest

from gather.discord_plan import GuildScope
from gather.discord_search import (
    PageCursor,
    ResponseScopeError,
    advance_search_cursor,
    build_capture_lanes,
    history_discovery_edges,
    initial_cursor,
    iter_lane_pages,
    parse_search_page,
    timestamp_snowflake_bound,
    validate_message_scope,
)
from gather.discord_transport import DiscordResponse

FIXTURE = Path(__file__).parent / "fixtures" / "discord" / "search-page.json"


def test_nested_search_messages_flatten_and_discard_member_payloads() -> None:
    page = parse_search_page(DiscordResponse(200,(),FIXTURE.read_bytes()))
    assert [str(message["id"]) for message in page.messages] == [
        "1456789012345678901",
        "1456789012345678800",
    ]
    assert page.total_results == 10020
    assert page.short_page_proves_complete is False
    assert not hasattr(page,"members")


def test_offset_ceiling_rolls_to_an_exclusive_snowflake_window() -> None:
    cursor = PageCursor(
        offset=9975,
        max_id=None,
        window_index=0,
        before=None,
        done=False,
    )
    page = parse_search_page(DiscordResponse(200,(),FIXTURE.read_bytes()))
    next_cursor = advance_search_cursor(cursor,page)
    assert next_cursor.offset == 0
    assert next_cursor.max_id == "1456789012345678800"
    assert next_cursor.window_index == 1


def test_plan_time_bounds_compile_to_ordered_snowflakes() -> None:
    lower = timestamp_snowflake_bound("2023-01-01T00:00:00Z",upper=False)
    upper = timestamp_snowflake_bound("2026-07-10T00:00:00Z",upper=True)
    assert int(lower) < int(upper)


@pytest.mark.parametrize(
    "message",
    [
        {"id":"1","guild_id":"999999999999999999","channel_id":"1081121447960915989"},
        {"id":"1","guild_id":"1080142797870485606","channel_id":"999999999999999999"},
        {"id":"1","guild_id":"1080142797870485606","channel_id":"345678901234567890"},
    ],
)
def test_malicious_response_locator_is_rejected_before_redaction_or_items(message) -> None:
    lane = _search_lane(channels=("1081121447960915989",),threads=())
    with pytest.raises(ResponseScopeError):
        validate_message_scope(message,lane)
    assert _redaction_spy.calls == []
    assert _item_spy.calls == []
~~~

- [ ] **Step 3: Run search tests and observe the red state**

Run:

~~~powershell
python -m pytest tests/test_discord_search.py -q
~~~

Expected: FAIL during collection because `gather.discord_search` does not exist.

- [ ] **Step 4: Add search page and cursor contracts**

Create `src/gather/discord_search.py`:

~~~python
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Iterator, Mapping

from gather.discord_plan import SealedCapturePlan
from gather.discord_transport import (
    DiscordClient,
    DiscordResponse,
    channel_history_request,
    guild_search_request,
)

SEARCH_LIMIT = 25
MAX_OFFSET = 9975
DISCORD_EPOCH_MS = 1_420_070_400_000


class SearchError(RuntimeError):
    pass


class ResponseScopeError(SearchError):
    pass


@dataclass(frozen=True, slots=True)
class LaneKey:
    plan_digest: str
    redaction_digest: str
    guild_id: str
    method: str
    query_hash: str | None
    channel_ids: tuple[str,...]
    min_id: str
    max_id: str

    def digest(self) -> str:
        return hashlib.sha256(json.dumps(
            asdict(self),sort_keys=True,separators=(",",":"),
        ).encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class CaptureLane:
    key: LaneKey
    guild_id: str
    channel_ids: tuple[str,...]
    thread_ids: tuple[str,...]
    method: str
    query: str | None


@dataclass(frozen=True, slots=True)
class PageCursor:
    offset: int
    max_id: str | None
    window_index: int
    before: str | None
    done: bool


@dataclass(frozen=True, slots=True)
class SearchPage:
    messages: tuple[Mapping[str,Any],...]
    total_results: int
    doing_deep_historical_index: bool
    response_body_sha256: str
    short_page_proves_complete: bool = False


@dataclass(frozen=True, slots=True)
class PageObservation:
    lane_key: LaneKey
    cursor_before: PageCursor
    cursor_after: PageCursor | None
    page: SearchPage
    retries: tuple[dict[str,Any],...]
    completeness: str

    @property
    def may_advance(self) -> bool:
        return self.cursor_after is not None


def query_hash(query: str) -> str:
    return hashlib.sha256(query.encode("utf-8")).hexdigest()


def timestamp_snowflake_bound(timestamp: str, *, upper: bool) -> str:
    instant = datetime.fromisoformat(timestamp.replace("Z","+00:00"))
    milliseconds = int(instant.timestamp() * 1000)
    base = max(0,milliseconds - DISCORD_EPOCH_MS) << 22
    return str(base | ((1 << 22) - 1 if upper else 0))


def parse_search_page(response: DiscordResponse) -> SearchPage:
    if response.status != 200:
        raise SearchError(f"search page returned HTTP {response.status}")
    if response.truncated:
        raise SearchError("search page was truncated")
    try:
        payload = json.loads(response.body)
    except (UnicodeDecodeError,json.JSONDecodeError) as exc:
        raise SearchError("search page was not complete JSON") from exc
    if not isinstance(payload,dict) or not isinstance(payload.get("messages"),list):
        raise SearchError("search page must contain nested messages")
    messages: list[Mapping[str,Any]] = []
    seen: set[str] = set()
    for group in payload["messages"]:
        if not isinstance(group,list):
            raise SearchError("search message group must be a list")
        for message in group:
            if not isinstance(message,Mapping):
                continue
            message_id = str(message.get("id",""))
            if not message_id.isdigit():
                raise SearchError("search message is missing a snowflake id")
            if message_id not in seen:
                seen.add(message_id)
                messages.append(message)
    return SearchPage(tuple(messages),int(payload.get("total_results",0)),bool(payload.get("doing_deep_historical_index",False)),hashlib.sha256(response.body).hexdigest())


def parse_history_page(response: DiscordResponse) -> SearchPage:
    if response.status != 200 or response.truncated:
        raise SearchError("history page is not an accepted complete response")
    try:
        payload = json.loads(response.body)
    except (UnicodeDecodeError,json.JSONDecodeError) as exc:
        raise SearchError("history page was not complete JSON") from exc
    if not isinstance(payload,list) or any(not isinstance(row,dict) for row in payload):
        raise SearchError("history page must be a message list")
    return SearchPage(
        tuple(payload),len(payload),False,
        hashlib.sha256(response.body).hexdigest(),False,
    )


def advance_search_cursor(cursor: PageCursor, page: SearchPage) -> PageCursor:
    next_offset = cursor.offset + SEARCH_LIMIT
    if next_offset <= MAX_OFFSET:
        return PageCursor(next_offset,cursor.max_id,cursor.window_index,None,False)
    if not page.messages:
        raise SearchError("offset ceiling reached without a snowflake for the next window")
    oldest = min(str(message["id"]) for message in page.messages)
    if cursor.max_id is not None and int(oldest) >= int(cursor.max_id):
        raise SearchError("search window did not move backward")
    return PageCursor(0,oldest,cursor.window_index + 1,None,False)


def validate_message_scope(
    message: Mapping[str,Any],
    lane: CaptureLane,
) -> tuple[str,str,str | None]:
    """Return trusted locator values sourced from the sealed lane."""
    guild_id = str(message.get("guild_id",""))
    channel_id = str(message.get("channel_id",""))
    message_id = str(message.get("id",""))
    if guild_id != lane.guild_id:
        raise ResponseScopeError("response guild does not match sealed lane")
    if channel_id not in lane.channel_ids:
        raise ResponseScopeError("response channel/thread does not match sealed lane")
    if not message_id.isdigit() or message_id.startswith("0"):
        raise ResponseScopeError("response message ID is not a snowflake")
    if not int(lane.key.min_id) < int(message_id) < int(lane.key.max_id):
        raise ResponseScopeError("response message is outside sealed snowflake bounds")
    thread_id = channel_id if channel_id in lane.thread_ids else None
    return lane.guild_id,channel_id,thread_id


def build_capture_lanes(plan: SealedCapturePlan) -> tuple[CaptureLane,...]:
    lanes: list[CaptureLane] = []
    for scope in plan.plan.guilds:
        searchable = tuple(sorted(set(scope.channels) | set(scope.threads)))
        min_id = timestamp_snowflake_bound(plan.plan.after,upper=False)
        max_id = timestamp_snowflake_bound(plan.plan.before,upper=True)
        for query in plan.plan.queries:
            key = LaneKey(
                plan.digest,plan.redaction_digest,scope.guild_id,"search",
                query_hash(query),searchable,min_id,max_id,
            )
            lanes.append(CaptureLane(
                key,scope.guild_id,searchable,scope.threads,"search",query,
            ))
        for channel_id in scope.history_channels:
            key = LaneKey(
                plan.digest,plan.redaction_digest,scope.guild_id,"history",
                None,(channel_id,),min_id,max_id,
            )
            lanes.append(CaptureLane(
                key,scope.guild_id,(channel_id,),(),"history",None,
            ))
    return tuple(sorted(lanes,key=lambda lane: lane.key.digest()))


def initial_cursor(lane: CaptureLane) -> PageCursor:
    return PageCursor(
        offset=0,max_id=None,window_index=0,
        before=lane.key.max_id if lane.method == "history" else None,
        done=False,
    )
~~~

- [ ] **Step 5: Add bounded query iteration and truthful completeness**

Append to `src/gather/discord_search.py`:

~~~python
def iter_lane_pages(
    lane: CaptureLane,
    *,
    start_cursor: PageCursor,
    client: DiscordClient,
    page_budget: int,
    message_budget: int,
) -> Iterator[PageObservation]:
    cursor = start_cursor
    if lane.method == "history" and not cursor.done:
        if cursor.before is None:
            raise SearchError("history cursor must start at the sealed max_id")
        if not int(lane.key.min_id) < int(cursor.before) <= int(lane.key.max_id):
            raise SearchError("history cursor is outside sealed lane bounds")
    pages_used = messages_seen = 0
    previous_total: int | None = None
    while not cursor.done and pages_used < page_budget and messages_seen < message_budget:
        remaining = message_budget - messages_seen
        if lane.method == "search":
            request = guild_search_request(
                lane.guild_id,content=lane.query or "",
                channel_ids=lane.channel_ids,limit=min(SEARCH_LIMIT,remaining),
                offset=cursor.offset,min_id=lane.key.min_id,
                max_id=cursor.max_id or lane.key.max_id,
            )
            indexing = True
        elif lane.method == "history":
            request = channel_history_request(
                lane.channel_ids[0],before=cursor.before,
                limit=min(100,remaining),
            )
            indexing = False
        else:
            raise SearchError("unknown capture lane method")
        exchange = client.execute(request,indexing=indexing)
        events = tuple(
            {"kind":event.kind,"status":event.status,
             "wait_seconds":event.wait_seconds,"scope":event.scope,
             "attempt":event.attempt}
            for event in exchange.events
        )
        if exchange.response.status != 200:
            empty = SearchPage(
                (),0,exchange.response.status == 202,
                hashlib.sha256(exchange.response.body).hexdigest(),False,
            )
            yield PageObservation(
                lane.key,cursor,None,empty,events,
                "indexing_incomplete" if exchange.response.status == 202
                else "transport_incomplete",
            )
            return
        try:
            page = parse_search_page(exchange.response) if lane.method == "search" else parse_history_page(exchange.response)
        except SearchError:
            empty = SearchPage(
                (),0,False,hashlib.sha256(exchange.response.body).hexdigest(),False,
            )
            yield PageObservation(lane.key,cursor,None,empty,events,"malformed")
            return
        if page.doing_deep_historical_index:
            yield PageObservation(
                lane.key,cursor,None,page,events,"indexing_incomplete",
            )
            return
        for message in page.messages:
            validate_message_scope(message,lane)
        pages_used += 1
        messages_seen += len(page.messages)
        if not page.messages and lane.method == "history":
            next_cursor = PageCursor(0,None,0,lane.key.min_id,True)
        elif not page.messages:
            next_cursor = PageCursor(
                cursor.offset,cursor.max_id,cursor.window_index,
                cursor.before,True,
            )
        elif lane.method == "search":
            next_cursor = advance_search_cursor(cursor,page)
        else:
            oldest = min(str(message["id"]) for message in page.messages)
            if cursor.before is not None and int(oldest) >= int(cursor.before):
                raise SearchError("history cursor did not move backward")
            next_cursor = (
                PageCursor(0,None,0,lane.key.min_id,True)
                if int(oldest) == int(lane.key.min_id) + 1
                else PageCursor(0,None,0,oldest,False)
            )
        completeness = "bounded_observed"
        if previous_total is not None and previous_total != page.total_results:
            completeness = "changing_total"
        if pages_used >= page_budget or messages_seen >= message_budget:
            completeness = "budget_exhausted"
        yield PageObservation(
            lane.key,cursor,next_cursor,page,events,completeness,
        )
        previous_total = page.total_results
        cursor = next_cursor
~~~

The caller must commit each yielded observation before requesting the next generator element. It may persist `cursor_after` only when non-`None`. A `202`, malformed body, `doing_deep_historical_index=true`, or any terminal status records an event but leaves the prior cursor unchanged.

- [ ] **Step 6: Add the explicit channel-history fallback, route/edge tests, and resume-input test**

Append to `src/gather/discord_transport.py`:

~~~python
def channel_history_request(
    channel_id: str,
    *,
    before: str | None,
    limit: int,
) -> DiscordRequest:
    channel_id = _snowflake(channel_id)
    if not 1 <= limit <= 100:
        raise DiscordTransportError("history limit must be between 1 and 100")
    query = [("limit",str(limit))]
    if before is not None:
        query.append(("before",_snowflake(before)))
    return DiscordRequest(
        "channel-history",
        f"/channels/{channel_id}/messages",
        tuple(query),
        channel_id,
    )
~~~

Append to `tests/test_discord_search.py`:

~~~python
def test_history_fallback_scope_is_explicit_in_the_plan() -> None:
    scope = GuildScope("community-shaders-discord","1080142797870485606",("1081121447960915989",),(),(),False,False)
    plan = _sealed_plan_with_scope(scope)
    assert all(lane.method == "search" for lane in build_capture_lanes(plan))


def test_only_allowlisted_history_channel_gets_history_lane_and_edge() -> None:
    scope = GuildScope(
        "community-shaders-discord","1080142797870485606",
        ("1081121447960915989","2081121447960915989"),(),
        ("1081121447960915989",),False,False,
    )
    lanes = build_capture_lanes(_sealed_plan_with_scope(scope))
    history = [lane for lane in lanes if lane.method == "history"]
    assert [lane.channel_ids for lane in history] == [("1081121447960915989",)]
    client,transport = _history_client([
        [{"id":"1456789012345678901","guild_id":"1080142797870485606","channel_id":"1081121447960915989","content":"PQ"}],
        [],
    ])
    observations = list(iter_lane_pages(
        history[0],start_cursor=initial_cursor(history[0]),client=client,
        page_budget=2,message_budget=10,
    ))
    assert [request.operation for request in transport.requests] == [
        "channel-history","channel-history",
    ]
    assert dict(transport.requests[0].query)["before"] == history[0].key.max_id
    assert dict(transport.requests[1].query)["before"] == "1456789012345678901"
    assert observations[-1].cursor_after == PageCursor(
        0,None,0,history[0].key.min_id,True,
    )
    edges = history_discovery_edges(observations[0])
    assert edges and all(edge.method == "discord-api-history-edge" for edge in edges)


def test_resume_cursor_is_used_for_the_first_request() -> None:
    lane = _search_lane(channels=("1081121447960915989",),threads=())
    client,transport = _search_client([{"messages":[],"total_results":0,"doing_deep_historical_index":False}])
    list(iter_lane_pages(
        lane,start_cursor=PageCursor(75,None,0,None,False),client=client,
        page_budget=1,message_budget=25,
    ))
    assert dict(transport.requests[0].query)["offset"] == "75"


@pytest.mark.parametrize("status",[202,403,500])
def test_terminal_or_indexing_response_never_exposes_next_cursor(status) -> None:
    lane = _search_lane(channels=("1081121447960915989",),threads=())
    observation = next(iter_lane_pages(
        lane,start_cursor=PageCursor(25,None,0,None,False),
        client=_status_client(status),page_budget=1,message_budget=25,
    ))
    assert observation.cursor_before.offset == 25
    assert observation.cursor_after is None
    assert observation.may_advance is False


@pytest.mark.parametrize(("method","message_id"),[
    ("history","100"),("history","200"),
    ("search","99"),("search","201"),
])
def test_message_at_or_outside_either_sealed_bound_is_rejected(method,message_id) -> None:
    lane = _lane_with_bounds(method=method,min_id="100",max_id="200")
    message = {
        "id":message_id,"guild_id":lane.guild_id,
        "channel_id":lane.channel_ids[0],"content":"out of bounds",
    }
    client = _lane_client(method,[message])
    with pytest.raises(ResponseScopeError,match="outside sealed"):
        list(iter_lane_pages(
            lane,start_cursor=initial_cursor(lane),client=client,
            page_budget=1,message_budget=25,
        ))


def test_search_context_messages_receive_the_same_locator_and_bound_checks() -> None:
    lane = _lane_with_bounds(method="search",min_id="100",max_id="200")
    client = _nested_search_client([[
        {"id":"150","guild_id":lane.guild_id,"channel_id":lane.channel_ids[0]},
        {"id":"201","guild_id":lane.guild_id,"channel_id":lane.channel_ids[0]},
    ]])
    with pytest.raises(ResponseScopeError,match="outside sealed"):
        list(iter_lane_pages(
            lane,start_cursor=initial_cursor(lane),client=client,
            page_budget=1,message_budget=25,
        ))
~~~

Add the closed fixture helpers used above and `history_discovery_edges(observation)` beside the existing search-edge builder. It must create one `DiscoveryEdge(method="discord-api-history-edge", ...)` per accepted history message. `_lane_with_bounds` uses exactly the supplied decimal bounds; `_lane_client` returns the correct search-object or history-list shape. Search hits, nested search context messages, and history messages all pass through the same `validate_message_scope` check before any observation with a next cursor can be yielded. An out-of-bound message raises before edge or Item construction.

- [ ] **Step 7: Run search, transport, and redaction tests**

Run:

~~~powershell
python -m pytest tests/test_discord_search.py tests/test_discord_transport.py tests/test_discord_redaction.py tests/test_discord_receipts.py -q
python -m ruff check src/gather/discord_search.py src/gather/discord_transport.py tests/test_discord_search.py
python -m mypy src/gather/discord_search.py src/gather/discord_transport.py
~~~

Expected: all commands pass. No test relies on short-page length or `total_results` stability to report complete coverage.

- [ ] **Step 8: Commit query-first search**

Run:

~~~powershell
git add src/gather/discord_search.py src/gather/discord_transport.py tests/test_discord_search.py tests/test_discord_transport.py tests/fixtures/discord/search-page.json
git commit -m "feat(discord): add bounded query-first search"
~~~

Expected: one commit containing search/window behavior and its typed routes.

### Task 8: Crash-Safe Corpus Batches, Manifests, and Checkpoints

**Files:**
- Create: `src/gather/discord_store.py`
- Create: `tests/test_discord_store.py`
- Test: `tests/test_store.py`

**Interfaces:**
- Consumes: `Corpus.add(items) -> dict[str,int]` and privacy-safe Items/manifest/checkpoint values.
- Produces: stable search `LaneKey`, `CaptureCheckpoint`, truthful `CaptureManifest`, `BatchCommitReceipt`, `aggregate_completeness(...)`, `manifest_identity(...)`, and single-writer `DiscordCaptureStore.commit_batch(...)`.

- [ ] **Step 1: Write failing ordered-commit and replay tests**

Create `tests/test_discord_store.py`:

~~~python
import json
from dataclasses import asdict

import pytest

from gather.discord_store import (
    CaptureCheckpoint,
    CaptureManifest,
    CaptureStateError,
    DiscordCaptureStore,
    manifest_identity,
)
from gather.discord_search import LaneKey, PageCursor
from gather.item import make_item
from gather.store import Corpus


def _item():
    return make_item(kind="community_claim",id="g:c:m",title="Discord technical message m",text='{"plan_digest":"' + "a" * 64 + '"}',source="discord",ref="discord://message/g/c/m/" + "a" * 64,method="discord-api-message",fetched_at=1.0,meta={})


def _state():
    key = LaneKey("a" * 64,"b" * 64,"1080142797870485606","search","c" * 64,("1081121447960915989",),"1","9")
    cursor_before = PageCursor(0,None,0,None,False)
    cursor_after = PageCursor(25,None,0,None,False)
    before = CaptureCheckpoint(key,cursor_before,0,0,0,"bounded_observed",())
    after = CaptureCheckpoint(key,cursor_after,1,1,1,"bounded_observed",())
    identity = manifest_identity("a" * 64,key.digest(),1,cursor_before)
    manifest = CaptureManifest(
        "gather.discord-capture-manifest/v1",identity,"hdr-plan","a" * 64,
        "discord-technical-v1","b" * 64,key.digest(),"c" * 64,"search",
        ("2023-01-01T00:00:00Z","2026-07-10T00:00:00Z"),("1","9"),
        {"page_budget":2,"message_budget":10,"batch_size":5,"retry_budget":1,"indexing_retry_budget":1},
        1,1,(),(),(),("d" * 64,),"f" * 64,("e" * 64,),
        cursor_before,cursor_after,before,after,"bounded_observed",
    )
    return before,after,manifest


def test_checkpoint_is_written_after_corpus_and_manifest(tmp_path) -> None:
    events: list[str] = []
    before,after,manifest = _state()
    store = DiscordCaptureStore(Corpus(str(tmp_path / "corpus"),fsync=False),state_root=tmp_path / "state",fsync=False,failpoint=events.append)
    receipt = store.commit_batch(items=[_item()],manifest=manifest,checkpoint=after)
    assert events == ["before-corpus","after-corpus","after-manifest","after-checkpoint"]
    assert receipt.checkpoint_digest
    assert store.load_checkpoint(after.key) == after


def test_crash_after_manifest_replays_without_duplicate_receipt(tmp_path) -> None:
    before,after,manifest = _state()
    def crash(stage: str) -> None:
        if stage == "after-manifest":
            raise RuntimeError("fixture crash")
    corpus = Corpus(str(tmp_path / "corpus"),fsync=False)
    broken = DiscordCaptureStore(corpus,state_root=tmp_path / "state",fsync=False,failpoint=crash)
    with pytest.raises(RuntimeError,match="fixture crash"):
        broken.commit_batch(items=[_item()],manifest=manifest,checkpoint=after)
    healthy = DiscordCaptureStore(corpus,state_root=tmp_path / "state",fsync=False)
    receipt = healthy.commit_batch(items=[_item()],manifest=manifest,checkpoint=after)
    assert receipt.stored == {"added":0,"deduped":1,"total":1}
    assert len(list(corpus.rows())) == 1
~~~

- [ ] **Step 2: Run checkpoint tests and observe the red state**

Run:

~~~powershell
python -m pytest tests/test_discord_store.py -q
~~~

Expected: FAIL during collection because `gather.discord_store` does not exist.

- [ ] **Step 3: Add immutable state and manifest contracts**

Create `src/gather/discord_store.py`:

~~~python
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Sequence

from gather.discord_redaction import assert_durable_private_data_free
from gather.discord_search import LaneKey, PageCursor
from gather.item import Item
from gather.store import Corpus


class CaptureStateError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class CaptureCheckpoint:
    key: LaneKey
    next_cursor: PageCursor
    pages_requested: int
    pages_accepted: int
    messages_committed: int
    completeness: str
    warnings: tuple[str,...]


@dataclass(frozen=True, slots=True)
class CaptureManifest:
    schema: str
    manifest_id: str
    plan_id: str
    plan_digest: str
    redaction_policy: str
    redaction_digest: str
    lane_digest: str
    query_hash: str | None
    method: str
    time_bounds: tuple[str,str]
    snowflake_bounds: tuple[str,str]
    sealed_budgets: dict[str,int]
    requested_pages: int
    accepted_pages: int
    retry_events: tuple[dict[str,Any],...]
    indexing_events: tuple[dict[str,Any],...]
    skipped_regions: tuple[dict[str,Any],...]
    transient_response_hashes: tuple[str,...]
    transient_response_aggregate: str
    durable_item_hashes: tuple[str,...]
    cursor_before: PageCursor
    cursor_after: PageCursor
    checkpoint_before: CaptureCheckpoint
    checkpoint_after: CaptureCheckpoint
    completeness: str


@dataclass(frozen=True, slots=True)
class BatchCommitReceipt:
    stored: dict[str,int]
    manifest_digest: str
    checkpoint_digest: str


def _json(value: object) -> str:
    return json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False)


COMPLETENESS_SEVERITY = {
    "complete":0,"bounded_observed":1,"changing_total":2,
    "budget_exhausted":3,"indexing_incomplete":4,"malformed":5,
    "transport_incomplete":6,
}


def aggregate_completeness(values: Sequence[str]) -> str:
    if not values:
        return "bounded_observed"
    unknown = set(values) - set(COMPLETENESS_SEVERITY)
    if unknown:
        raise CaptureStateError(f"unknown completeness state: {sorted(unknown)}")
    return max(values,key=COMPLETENESS_SEVERITY.__getitem__)


def manifest_identity(
    plan_digest: str,
    lane_digest: str,
    batch_sequence: int,
    cursor_before: PageCursor,
) -> str:
    return hashlib.sha256(_json({
        "plan_digest":plan_digest,"lane_digest":lane_digest,
        "batch_sequence":batch_sequence,"cursor_before":asdict(cursor_before),
    }).encode()).hexdigest()
~~~

- [ ] **Step 4: Add atomic JSON replacement and ordered commit**

Append to `src/gather/discord_store.py`:

~~~python
class DiscordCaptureStore:
    def __init__(self, corpus: Corpus, *, state_root: Path, fsync: bool = True, failpoint: Callable[[str],None] = lambda _:None) -> None:
        self._corpus = corpus
        self._state_root = state_root
        self._fsync = fsync
        self._failpoint = failpoint
        self._writer_depth = 0

    def _path(self, kind: str, digest: str) -> Path:
        if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
            raise CaptureStateError("state digest must be 64 lowercase hexadecimal characters")
        return self._state_root / kind / f"{digest}.json"

    def _encoded(self, value: object) -> tuple[bytes,str]:
        assert_durable_private_data_free(value)
        encoded = (_json(value) + "\n").encode("utf-8")
        return encoded,hashlib.sha256(encoded).hexdigest()

    def _replace_json(self, path: Path, value: object) -> str:
        encoded,digest = self._encoded(value)
        path.parent.mkdir(parents=True,exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        with temporary.open("wb") as stream:
            stream.write(encoded)
            stream.flush()
            if self._fsync:
                os.fsync(stream.fileno())
        os.replace(temporary,path)
        self._fsync_directory(path.parent)
        return digest

    def _write_json_once(self, path: Path, value: object) -> str:
        encoded,digest = self._encoded(value)
        path.parent.mkdir(parents=True,exist_ok=True)
        prefix = f".{path.name}."
        for stale in path.parent.glob(f"{prefix}*.tmp"):
            stale.unlink(missing_ok=True)
        if path.exists():
            if path.read_bytes() != encoded:
                raise CaptureStateError(
                    "manifest identity already exists with different bytes"
                )
            return digest
        descriptor,name = tempfile.mkstemp(
            dir=path.parent,prefix=prefix,suffix=".tmp",
        )
        temporary = Path(name)
        try:
            with os.fdopen(descriptor,"wb") as stream:
                midpoint = len(encoded) // 2
                stream.write(encoded[:midpoint])
                stream.flush()
                if self._fsync:
                    os.fsync(stream.fileno())
                self._failpoint("after-manifest-partial")
                stream.write(encoded[midpoint:])
                stream.flush()
                if self._fsync:
                    os.fsync(stream.fileno())
            self._failpoint("after-manifest-temp")
        except Exception:
            # A simulated/process crash may leave only a non-authoritative temp.
            # The final immutable path has never been exposed.
            raise
        try:
            os.link(temporary,path)
        except FileExistsError:
            if path.read_bytes() != encoded:
                raise CaptureStateError(
                    "manifest identity already exists with different bytes"
                )
        else:
            self._fsync_directory(path.parent)
        finally:
            temporary.unlink(missing_ok=True)
        return digest

    def _fsync_directory(self, directory: Path) -> None:
        if not self._fsync:
            return
        flags = os.O_RDONLY | getattr(os,"O_DIRECTORY",0)
        try:
            descriptor = os.open(directory,flags)
        except OSError:
            return  # Windows/filesystems without directory handles.
        try:
            os.fsync(descriptor)
        except OSError:
            pass
        finally:
            os.close(descriptor)

    @contextmanager
    def capture_session(self):
        if self._writer_depth:
            self._writer_depth += 1
            try:
                yield
            finally:
                self._writer_depth -= 1
            return
        lock = self._state_root / "capture.lock"
        lock.parent.mkdir(parents=True,exist_ok=True)
        try:
            descriptor = os.open(lock,os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            raise CaptureStateError("capture store already has an active writer") from exc
        try:
            os.write(descriptor,str(os.getpid()).encode("ascii"))
            os.close(descriptor)
            self._writer_depth = 1
            yield
        finally:
            self._writer_depth = 0
            if lock.exists():
                lock.unlink()

    def commit_batch(self, *, items: list[Item], manifest: CaptureManifest, checkpoint: CaptureCheckpoint) -> BatchCommitReceipt:
        if manifest.checkpoint_after != checkpoint:
            raise CaptureStateError("manifest and checkpoint commit targets differ")
        expected_id = manifest_identity(
            manifest.plan_digest,manifest.lane_digest,
            checkpoint.pages_requested,manifest.cursor_before,
        )
        if manifest.manifest_id != expected_id:
            raise CaptureStateError("manifest identity is not deterministic")
        if manifest.cursor_after != checkpoint.next_cursor:
            raise CaptureStateError("manifest cursor and checkpoint cursor differ")
        assert_durable_private_data_free(asdict(manifest))
        assert_durable_private_data_free(asdict(checkpoint))
        for item in items:
            assert_durable_private_data_free(json.loads(item.text))
        with self.capture_session():
            self._failpoint("before-corpus")
            stored = self._corpus.add(items)
            self._failpoint("after-corpus")
            manifest_digest = self._write_json_once(
                self._path("manifests",manifest.manifest_id),asdict(manifest),
            )
            self._failpoint("after-manifest")
            checkpoint_digest = self._replace_json(
                self._path("checkpoints",checkpoint.key.digest()),asdict(checkpoint),
            )
            self._failpoint("after-checkpoint")
        return BatchCommitReceipt(stored,manifest_digest,checkpoint_digest)

    def load_checkpoint(self, key: LaneKey) -> CaptureCheckpoint | None:
        path = self._path("checkpoints",key.digest())
        if not path.exists():
            return None
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            raw_key = dict(value["key"])
            raw_key["channel_ids"] = tuple(raw_key["channel_ids"])
            loaded_key = LaneKey(**raw_key)
            raw_cursor = dict(value["next_cursor"])
            return CaptureCheckpoint(
                loaded_key,PageCursor(**raw_cursor),
                int(value["pages_requested"]),int(value["pages_accepted"]),
                int(value["messages_committed"]),str(value["completeness"]),
                tuple(str(row) for row in value.get("warnings",[])),
            )
        except (KeyError,TypeError,ValueError,json.JSONDecodeError) as exc:
            raise CaptureStateError("checkpoint is corrupt") from exc
~~~

- [ ] **Step 5: Add incompatible-key and corrupt-state tests**

Append to `tests/test_discord_store.py`:

~~~python
def test_changed_plan_or_redaction_digest_forks_checkpoint_key() -> None:
    before,after,_ = _state()
    changed = LaneKey("f" * 64,after.key.redaction_digest,after.key.guild_id,after.key.method,after.key.query_hash,after.key.channel_ids,after.key.min_id,after.key.max_id)
    assert changed.digest() != after.key.digest()


def test_corrupt_checkpoint_fails_closed(tmp_path) -> None:
    _,after,_ = _state()
    store = DiscordCaptureStore(Corpus(str(tmp_path / "corpus"),fsync=False),state_root=tmp_path / "state",fsync=False)
    path = store._path("checkpoints",after.key.digest())
    path.parent.mkdir(parents=True)
    path.write_text("{broken",encoding="utf-8")
    with pytest.raises(Exception,match="corrupt"):
        store.load_checkpoint(after.key)


def test_same_manifest_bytes_are_idempotent_but_conflict_never_overwrites(tmp_path) -> None:
    from dataclasses import replace
    _,after,manifest = _state()
    store = DiscordCaptureStore(
        Corpus(str(tmp_path / "corpus"),fsync=False),
        state_root=tmp_path / "state",fsync=False,
    )
    first = store.commit_batch(items=[_item()],manifest=manifest,checkpoint=after)
    second = store.commit_batch(items=[_item()],manifest=manifest,checkpoint=after)
    assert first.manifest_digest == second.manifest_digest
    path = store._path("manifests",manifest.manifest_id)
    original = path.read_bytes()
    conflicting = replace(manifest,completeness="transport_incomplete")
    with pytest.raises(CaptureStateError,match="different bytes"):
        store.commit_batch(items=[_item()],manifest=conflicting,checkpoint=after)
    assert path.read_bytes() == original


def test_partial_manifest_temp_is_never_published_and_retry_recovers(tmp_path) -> None:
    _,after,manifest = _state()
    corpus = Corpus(str(tmp_path / "corpus"),fsync=False)
    def crash(stage: str) -> None:
        if stage == "after-manifest-partial":
            raise RuntimeError("simulated partial manifest crash")
    broken = DiscordCaptureStore(
        corpus,state_root=tmp_path / "state",fsync=False,failpoint=crash,
    )
    final = broken._path("manifests",manifest.manifest_id)
    with pytest.raises(RuntimeError,match="partial manifest crash"):
        broken.commit_batch(items=[_item()],manifest=manifest,checkpoint=after)
    assert not final.exists()
    assert list(final.parent.glob(f".{final.name}.*.tmp"))
    assert broken.load_checkpoint(after.key) is None

    healthy = DiscordCaptureStore(
        corpus,state_root=tmp_path / "state",fsync=False,
    )
    receipt = healthy.commit_batch(
        items=[_item()],manifest=manifest,checkpoint=after,
    )
    assert receipt.stored == {"added":0,"deduped":1,"total":1}
    assert final.read_bytes() == healthy._encoded(asdict(manifest))[0]
    assert list(final.parent.glob(f".{final.name}.*.tmp")) == []
    assert healthy.load_checkpoint(after.key) == after


def test_second_writer_fails_closed(tmp_path) -> None:
    first = DiscordCaptureStore(
        Corpus(str(tmp_path / "corpus"),fsync=False),
        state_root=tmp_path / "state",fsync=False,
    )
    second = DiscordCaptureStore(
        Corpus(str(tmp_path / "corpus"),fsync=False),
        state_root=tmp_path / "state",fsync=False,
    )
    with first.capture_session():
        with pytest.raises(CaptureStateError,match="active writer"):
            with second.capture_session():
                raise AssertionError("second writer entered")


def test_aggregate_completeness_never_hides_earlier_warning() -> None:
    assert aggregate_completeness(
        ["changing_total","bounded_observed","complete"]
    ) == "changing_total"
    assert aggregate_completeness(
        ["indexing_incomplete","bounded_observed"]
    ) == "indexing_incomplete"
~~~

Document the store as single-writer. A stale `capture.lock` is a fail-closed operational condition: status/doctor reports it, and an operator may remove it only after proving that no capture process is active. Never auto-break or overwrite the lock.

- [ ] **Step 6: Run crash recovery and corpus regressions**

Run:

~~~powershell
python -m pytest tests/test_discord_store.py tests/test_store.py tests/test_discord_receipts.py -q
python -m ruff check src/gather/discord_store.py tests/test_discord_store.py
python -m mypy src/gather/discord_store.py
~~~

Expected: all commands pass. A crash before checkpoint replacement repeats safely; a completed checkpoint always has a durable manifest and corpus batch.

- [ ] **Step 7: Commit crash-safe capture state**

Run:

~~~powershell
git add src/gather/discord_store.py tests/test_discord_store.py
git commit -m "feat(discord): commit manifests before checkpoints"
~~~

Expected: one state-store commit with deterministic crash tests.

### Task 9: Shared Validation, Capture, Status, and Credential-Order Engine

**Files:**
- Create: `src/gather/discord.py`
- Create: `tests/test_discord_engine.py`
- Modify: `src/gather/credentials.py`
- Modify: `tests/test_credentials.py`
- Modify: `src/gather/__init__.py`
- Modify: `tests/test_package.py`

**Interfaces:**
- Consumes: sealed plans, `DiscordClient`, preflight/search/redaction/receipt functions, and `DiscordCaptureStore`.
- Produces: `PlanValidationReceipt`, `CaptureReceipt`, `CaptureStatusReceipt`, `DiscordDoctorReceipt`, `verify_sealed_plan(plan, *, federation_rows)`, trusted `validate_plan(plan, *, federation_rows)`, `preflight_plan(plan, *, client)`, `capture_plan(plan, *, federation_rows, client, store)`, `status_plan(plan, *, store)`, and `official_client_after_validation(plan, *, federation_rows, secret_reader)`.

- [ ] **Step 1: Write the failing credential-order and receipt-only engine tests**

Create `tests/test_discord_engine.py`:

~~~python
import json
from dataclasses import replace
from pathlib import Path

import pytest

from gather.discord import (
    CapturePreflightError,
    capture_plan,
    official_client_after_validation,
    validate_plan,
)
from gather.discord_plan import PlanError, parse_capture_plan
from gather.discord_preflight import PreflightError
from gather.discord_search import (
    ResponseScopeError, build_capture_lanes, initial_cursor,
)

FIXTURES = Path(__file__).parent / "fixtures" / "discord"


def _rows():
    return json.loads((FIXTURES / "federation-valid.json").read_text())["sources"]


def _plan():
    return parse_capture_plan(
        json.loads((FIXTURES / "plan-valid.json").read_text()),
        federation_rows=_rows(),
    )


def test_plan_validation_receipt_contains_hashes_not_scope_bodies() -> None:
    payload = validate_plan(_plan(),federation_rows=_rows()).as_dict()
    assert payload["schema"] == "gather.discord-plan-validation/v1"
    assert payload["status"] == "MATCH"
    assert len(payload["plan_digest"]) == 64
    assert "queries" not in payload
    assert "guilds" not in payload


def test_invalid_plan_never_reaches_the_credential_reader() -> None:
    calls = 0
    def forbidden_reader(_: str) -> str:
        nonlocal calls
        calls += 1
        raise AssertionError("credential reader must not run")
    with pytest.raises(PlanError):
        parse_capture_plan({"schema_version":1},federation_rows=_rows())
    assert calls == 0


def test_official_client_reads_only_the_fixed_bot_variable_after_validation() -> None:
    names: list[str] = []
    def reader(name: str) -> str:
        names.append(name)
        return "fixture-secret"
    client = official_client_after_validation(_plan(),federation_rows=_rows(),secret_reader=reader)
    assert names == ["GATHER_DISCORD_BOT_TOKEN"]
    assert "fixture-secret" not in repr(client)


@pytest.mark.parametrize(
    "forged",
    [
        lambda plan: replace(plan,digest="f" * 64),
        lambda plan: replace(plan,canonical_json=plan.canonical_json + " "),
        lambda plan: replace(plan,authorization_digest="f" * 64),
    ],
)
def test_tampered_seal_is_rejected_before_any_secret_read(forged) -> None:
    names: list[str] = []
    with pytest.raises(PlanError,match="sealed plan"):
        official_client_after_validation(
            forged(_plan()),federation_rows=_rows(),
            secret_reader=lambda name: names.append(name) or "fixture-secret",
        )
    assert names == []


def test_public_validate_plan_reseals_against_trusted_federation_rows() -> None:
    forged = replace(_plan(),canonical_json=_plan().canonical_json + " ")
    with pytest.raises(PlanError,match="sealed plan"):
        validate_plan(forged,federation_rows=_rows())
~~~

- [ ] **Step 2: Run engine tests and observe the red state**

Run:

~~~powershell
python -m pytest tests/test_discord_engine.py -q
~~~

Expected: FAIL during collection because the high-level `gather.discord` facade does not exist.

- [ ] **Step 3: Add non-revealing credential state**

Append to `src/gather/credentials.py`:

~~~python
def secret_state(name: str) -> str:
    try:
        require_secret(name)
    except MissingCredential:
        return "invalid" if os.environ.get(name) else "missing"
    return "present"
~~~

Append to `tests/test_credentials.py`:

~~~python
def test_secret_state_reports_presence_without_value(monkeypatch) -> None:
    from gather.credentials import secret_state
    monkeypatch.setenv("FIXTURE_SECRET","fixture-value")
    assert secret_state("FIXTURE_SECRET") == "present"
    monkeypatch.setenv("FIXTURE_SECRET","bad\nvalue")
    assert secret_state("FIXTURE_SECRET") == "invalid"
    monkeypatch.delenv("FIXTURE_SECRET")
    assert secret_state("FIXTURE_SECRET") == "missing"
~~~

- [ ] **Step 4: Add receipt-only facade result types and client construction**

Create `src/gather/discord.py`:

~~~python
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any, Callable, Sequence

from gather.credentials import require_secret, secret_state
from gather.discord_plan import (
    PlanError, SealedCapturePlan, authorized_guild_id, parse_capture_plan,
)
from gather.discord_preflight import PreflightReceipt, preflight_plan
from gather.discord_redaction import assert_durable_private_data_free
from gather.discord_store import DiscordCaptureStore
from gather.discord_transport import (
    DiscordClient,
    DiscordHTTPTransport,
    RetryPolicy,
)

DISCORD_TOKEN_ENV = "GATHER_DISCORD_BOT_TOKEN"


class CapturePreflightError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class PlanValidationReceipt:
    schema: str
    status: str
    plan_id: str
    plan_digest: str
    authorization_digest: str
    redaction_digest: str

    def as_dict(self) -> dict[str,Any]:
        value = asdict(self)
        assert_durable_private_data_free(value)
        return value


@dataclass(frozen=True, slots=True)
class CaptureReceipt:
    schema: str
    status: str
    plan_id: str
    plan_digest: str
    messages: int
    discovery_edges: int
    requested_pages: int
    accepted_pages: int
    manifests: tuple[str,...]
    checkpoint_refs: tuple[str,...]
    warnings: tuple[str,...]
    completeness: str

    def as_dict(self) -> dict[str,Any]:
        value = asdict(self)
        assert_durable_private_data_free(value)
        return value


@dataclass(frozen=True, slots=True)
class CaptureStatusReceipt:
    schema: str
    status: str
    plan_id: str
    plan_digest: str
    checkpoint_count: int
    manifest_count: int
    completeness: tuple[str,...]

    def as_dict(self) -> dict[str,Any]:
        value = asdict(self)
        assert_durable_private_data_free(value)
        return value


@dataclass(frozen=True, slots=True)
class DiscordDoctorReceipt:
    schema: str
    status: str
    token_state: str
    plan_root_configured: bool
    corpus_root_configured: bool

    def as_dict(self) -> dict[str,Any]:
        value = asdict(self)
        assert_durable_private_data_free(value)
        return value


def _validation_receipt(plan: SealedCapturePlan) -> PlanValidationReceipt:
    return PlanValidationReceipt("gather.discord-plan-validation/v1","MATCH",plan.plan.plan_id,plan.digest,plan.authorization_digest,plan.redaction_digest)


def verify_sealed_plan(
    plan: SealedCapturePlan,
    *,
    federation_rows: Sequence[dict[str,Any]],
) -> PlanValidationReceipt:
    """Reparse trusted canonical bytes and compare every seal before secrets."""
    try:
        reparsed = parse_capture_plan(
            json.loads(plan.canonical_json),federation_rows=federation_rows,
        )
    except (json.JSONDecodeError,PlanError) as exc:
        raise PlanError("sealed plan failed invariant verification") from exc
    if reparsed != plan:
        raise PlanError("sealed plan digest or authorization is forged")
    return _validation_receipt(reparsed)


def validate_plan(
    plan: SealedCapturePlan,
    *,
    federation_rows: Sequence[dict[str,Any]],
) -> PlanValidationReceipt:
    return verify_sealed_plan(plan,federation_rows=federation_rows)


def official_client_after_validation(
    plan: SealedCapturePlan,
    *,
    federation_rows: Sequence[dict[str,Any]],
    secret_reader: Callable[[str],str] = require_secret,
) -> DiscordClient:
    verify_sealed_plan(plan,federation_rows=federation_rows)
    token = secret_reader(DISCORD_TOKEN_ENV)
    return DiscordClient(
        DiscordHTTPTransport(f"Bot {token}"),
        policy=RetryPolicy(
            rate_retries=plan.plan.retry_budget,
            indexing_retries=plan.plan.indexing_retry_budget,
            server_retries=plan.plan.retry_budget,
        ),
    )


def official_discovery_client_after_authorization(
    federation_id: str,
    *,
    federation_rows: Sequence[dict[str,Any]],
    secret_reader: Callable[[str],str] = require_secret,
) -> DiscordClient:
    authorized_guild_id(federation_id,federation_rows)  # raises before secret read
    token = secret_reader(DISCORD_TOKEN_ENV)
    return DiscordClient(
        DiscordHTTPTransport(f"Bot {token}"),
        policy=RetryPolicy(rate_retries=2,indexing_retries=0,server_retries=2),
    )


def discord_doctor(*, plan_root_configured: bool, corpus_root_configured: bool) -> DiscordDoctorReceipt:
    token = secret_state(DISCORD_TOKEN_ENV)
    status = "MATCH" if token == "present" and plan_root_configured and corpus_root_configured else "UNVERIFIABLE"
    return DiscordDoctorReceipt("gather.discord-doctor/v1",status,token,plan_root_configured,corpus_root_configured)
~~~

- [ ] **Step 5: Add capture orchestration using transient page objects**

Append to `src/gather/discord.py`:

~~~python
import time

from gather.discord_receipts import (
    DiscoveryEdge,
    discovery_edge_item,
    message_item,
)
from gather.discord_redaction import redact_message
from gather.item import Item
from gather.discord_search import (
    build_capture_lanes,
    initial_cursor,
    iter_lane_pages,
    validate_message_scope,
)
from gather.discord_store import (
    CaptureCheckpoint,
    CaptureManifest,
    aggregate_completeness,
    manifest_identity,
)


def capture_plan(
    plan: SealedCapturePlan,
    *,
    federation_rows: Sequence[dict[str,Any]],
    client: DiscordClient,
    store: DiscordCaptureStore,
) -> CaptureReceipt:
    verify_sealed_plan(plan,federation_rows=federation_rows)
    preflight = preflight_plan(plan,client=client)
    if preflight.status != "MATCH":
        raise CapturePreflightError("capture requires an exact preflight MATCH")
    message_count = edge_count = requested_pages = accepted_pages = 0
    manifest_refs: list[str] = []
    checkpoint_refs: list[str] = []
    warnings: list[str] = []
    states: list[str] = []
    for lane in build_capture_lanes(plan):
        initial = initial_cursor(lane)
        before = store.load_checkpoint(lane.key) or CaptureCheckpoint(
            lane.key,initial,0,0,0,"bounded_observed",(),
        )
        # The checkpoint is loaded before the generator can make a request.
        observations = iter_lane_pages(
            lane,start_cursor=before.next_cursor,client=client,
            page_budget=max(0,plan.plan.page_budget-requested_pages),
            message_budget=max(0,plan.plan.message_budget-message_count),
        )
        for observation in observations:
            requested_pages += 1
            items: list[Item] = []
            accepted_messages = 0
            if observation.cursor_after is not None:
                for rank,raw_message in enumerate(observation.page.messages):
                    guild_id,channel_id,thread_id = validate_message_scope(raw_message,lane)
                    redacted = redact_message(
                        raw_message,guild_id=guild_id,channel_id=channel_id,
                        thread_id=thread_id,plan_digest=plan.digest,
                        response_body_sha256=observation.page.response_body_sha256,
                    )
                    message = message_item(redacted,fetched_at=time.time())
                    edge_method = (
                        "discord-api-search-edge" if lane.method == "search"
                        else "discord-api-history-edge"
                    )
                    edge = discovery_edge_item(
                        DiscoveryEdge.from_lane(
                            plan_digest=plan.digest,lane=lane,message=redacted,
                            message_ref=message.provenance.sha256,
                            method=edge_method,cursor=observation.cursor_before,
                            rank=rank,response_body_sha256=observation.page.response_body_sha256,
                        ),
                        fetched_at=time.time(),
                    )
                    items.extend((message,edge))
                    accepted_messages += 1
                accepted_pages += 1
            next_cursor = observation.cursor_after or before.next_cursor
            page_states = [before.completeness,observation.completeness]
            after = CaptureCheckpoint(
                lane.key,next_cursor,before.pages_requested + 1,
                before.pages_accepted + (observation.cursor_after is not None),
                before.messages_committed + accepted_messages,
                aggregate_completeness(page_states),
                tuple(sorted(set(before.warnings + (
                    () if observation.completeness == "bounded_observed"
                    else (observation.completeness,)
                )))),
            )
            manifest = _manifest_for_observation(
                plan=plan,lane=lane,observation=observation,
                items=items,before=before,after=after,
            )
            committed = store.commit_batch(
                items=items,manifest=manifest,checkpoint=after,
            )
            # Only now may the generator request the following page.
            before = after
            message_count += accepted_messages
            edge_count += accepted_messages
            manifest_refs.append(committed.manifest_digest)
            checkpoint_refs.append(committed.checkpoint_digest)
            states.append(observation.completeness)
            if observation.completeness != "bounded_observed":
                warnings.append(observation.completeness)
    overall = aggregate_completeness(states)
    return CaptureReceipt(
        "gather.discord-capture/v1",
        "MATCH" if not warnings else "MATCH_WITH_WARNINGS",
        plan.plan.plan_id,plan.digest,message_count,edge_count,
        requested_pages,accepted_pages,tuple(manifest_refs),
        tuple(checkpoint_refs),tuple(sorted(set(warnings))),overall,
    )
~~~

Implement `_manifest_for_observation` as a pure constructor of the Task 8 `CaptureManifest`. It must populate every declared field from the sealed plan, lane, observation, and before/after checkpoints; split retry versus indexing events; record a skipped-region entry when `cursor_after is None`; compute the ordered transient aggregate as `sha256(canonical_json(response_hashes))`; use `manifest_identity(plan.digest,lane.key.digest(),after.pages_requested,observation.cursor_before)`; and set completeness with `aggregate_completeness((before.completeness, observation.completeness))`. No raw response or message mapping may enter the manifest.

After seal verification and exact preflight `MATCH`, execute the entire lane/checkpoint/request/commit loop—not merely each batch—inside `with store.capture_session():`. Factor the displayed loop into `_capture_plan_locked(...)` if needed to keep indentation readable. This makes checkpoint load through final commit one single-writer session; the reentrant `commit_batch` call uses the already-held lock.

Append mandatory gate/resumption tests to `tests/test_discord_engine.py`:

~~~python
@pytest.mark.parametrize("failure",["missing-channel","permission-mismatch","guild-mismatch"])
def test_capture_preflight_failure_makes_zero_message_requests(tmp_path,failure) -> None:
    client,transport = _metadata_failure_client(failure)
    with pytest.raises((PreflightError,CapturePreflightError)):
        capture_plan(
            _plan(),federation_rows=_rows(),client=client,
            store=_store(tmp_path),
        )
    assert all(
        request.operation not in {"guild-search","channel-history"}
        for request in transport.requests
    )
    assert list((tmp_path / "state").rglob("*.json")) == []


def test_restart_uses_committed_next_cursor_without_replaying_accepted_page(tmp_path) -> None:
    store = _store(tmp_path)
    first_client,first_transport = _preflight_then_search_client([
        _search_page([_message("1456789012345678901")]),
    ])
    first = capture_plan(
        _one_page_plan(),federation_rows=_rows(),client=first_client,store=store,
    )
    assert first.accepted_pages == 1
    assert dict(_message_requests(first_transport)[0].query)["offset"] == "0"

    restarted_client,restarted_transport = _preflight_then_search_client([
        _search_page([]),
    ])
    capture_plan(
        _one_page_plan(),federation_rows=_rows(),
        client=restarted_client,store=store,
    )
    requests = _message_requests(restarted_transport)
    assert len(requests) == 1
    assert dict(requests[0].query)["offset"] == "25"


@pytest.mark.parametrize("failure",["202","malformed","deep-indexing","terminal"])
def test_unaccepted_page_does_not_advance_restart_cursor(tmp_path,failure) -> None:
    store = _store(tmp_path)
    client,_ = _preflight_then_failure_client(failure)
    capture_plan(_one_page_plan(),federation_rows=_rows(),client=client,store=store)
    restarted,transport = _preflight_then_search_client([_search_page([])])
    capture_plan(_one_page_plan(),federation_rows=_rows(),client=restarted,store=store)
    assert dict(_message_requests(transport)[0].query)["offset"] == "0"


def test_deep_indexing_page_with_messages_commits_zero_message_or_edge_counts(tmp_path) -> None:
    store = _store(tmp_path)
    plan = _one_page_plan()
    lane = build_capture_lanes(plan)[0]
    client,_transport = _preflight_then_search_client([
        _search_page(
            [_message(str(int(lane.key.min_id) + 1))],
            deep_indexing=True,
        ),
    ])
    receipt = capture_plan(
        plan,federation_rows=_rows(),client=client,store=store,
    )
    checkpoint = store.load_checkpoint(lane.key)
    assert receipt.messages == 0
    assert receipt.discovery_edges == 0
    assert receipt.accepted_pages == 0
    assert _corpus_rows(tmp_path) == []
    assert checkpoint is not None
    assert checkpoint.messages_committed == 0
    assert checkpoint.next_cursor == initial_cursor(lane)


@pytest.mark.parametrize(("method","bound"),[
    ("search","min"),("search","max"),
    ("history","min"),("history","max"),
])
def test_out_of_bound_lane_message_writes_no_item_manifest_or_checkpoint(
    tmp_path,method,bound,
) -> None:
    plan = _single_lane_plan(method)
    lane = build_capture_lanes(plan)[0]
    message_id = lane.key.min_id if bound == "min" else lane.key.max_id
    client,_transport = _preflight_then_lane_client(
        method,[_message(message_id)],
    )
    with pytest.raises(ResponseScopeError,match="outside sealed"):
        capture_plan(
            plan,federation_rows=_rows(),client=client,store=_store(tmp_path),
        )
    assert _corpus_rows(tmp_path) == []
    assert _read_manifests(tmp_path) == []
    assert _read_checkpoints(tmp_path) == []


@pytest.mark.parametrize("field",["guild_id","channel_id"])
def test_malicious_response_scope_mismatch_writes_no_items_or_state(tmp_path,field) -> None:
    message = _message("1456789012345678901")
    message[field] = "999999999999999999"
    client,_ = _preflight_then_search_client([_search_page([message])])
    with pytest.raises(ResponseScopeError):
        capture_plan(
            _one_page_plan(),federation_rows=_rows(),client=client,
            store=_store(tmp_path),
        )
    assert _corpus_rows(tmp_path) == []
    assert _read_manifests(tmp_path) == []


def test_manifest_and_receipt_keep_earlier_warning_after_later_page(tmp_path) -> None:
    client,_ = _preflight_then_search_client([
        _search_page([_message("1456789012345678901")],total=2),
        _search_page([],total=1),
    ])
    receipt = capture_plan(
        _two_page_plan(),federation_rows=_rows(),client=client,store=_store(tmp_path),
    )
    assert "changing_total" in receipt.warnings
    assert receipt.completeness == "changing_total"
    manifests = _read_manifests(tmp_path)
    assert manifests[-1]["completeness"] == "changing_total"
    assert manifests[-1]["requested_pages"] >= manifests[-1]["accepted_pages"]
    for field in (
        "plan_id","plan_digest","redaction_policy","redaction_digest",
        "query_hash","time_bounds","snowflake_bounds","sealed_budgets",
        "retry_events","indexing_events","skipped_regions",
        "transient_response_aggregate","durable_item_hashes",
        "cursor_before","cursor_after",
    ):
        assert field in manifests[-1]
~~~

The test helpers are fixture-only and script all metadata routes before message routes. They assert exact request order, not merely final counts. In CLI/MCP tests in Task 10, reuse the same failing engine spy so `capture` on any non-`MATCH` preflight also proves zero search/history calls.

- [ ] **Step 6: Add read-only status and stable exports**

Append this public method to `DiscordCaptureStore`:

~~~python
    def status_counts(
        self,
        plan_digest: str,
    ) -> tuple[int,int,tuple[str,...]]:
        checkpoint_count = manifest_count = 0
        states: set[str] = set()
        for kind in ("manifests","checkpoints"):
            directory = self._state_root / kind
            if not directory.exists():
                continue
            for path in sorted(directory.glob("*.json")):
                try:
                    value = json.loads(path.read_text(encoding="utf-8"))
                except json.JSONDecodeError as exc:
                    raise CaptureStateError(f"{kind} state is corrupt") from exc
                assert_durable_private_data_free(value)
                state_plan = (
                    value.get("plan_digest")
                    if kind == "manifests"
                    else (value.get("key") or {}).get("plan_digest")
                )
                if state_plan != plan_digest:
                    continue
                states.add(str(value.get("completeness","unknown")))
                if kind == "manifests":
                    manifest_count += 1
                else:
                    checkpoint_count += 1
        return checkpoint_count,manifest_count,tuple(sorted(states))
~~~

Append to `src/gather/discord.py`:

~~~python
def status_plan(
    plan: SealedCapturePlan,
    *,
    store: DiscordCaptureStore,
) -> CaptureStatusReceipt:
    checkpoints,manifests,states = store.status_counts(plan.digest)
    return CaptureStatusReceipt("gather.discord-status/v1","MATCH",plan.plan.plan_id,plan.digest,checkpoints,manifests,states)
~~~

Modify `src/gather/__init__.py` to import and add these exact names to `__all__`:

~~~python
from gather.discord import (
    CaptureReceipt,
    CaptureStatusReceipt,
    PlanValidationReceipt,
    capture_plan,
    status_plan,
    validate_plan,
)
~~~

- [ ] **Step 7: Run engine, credentials, package, and core regressions**

Run:

~~~powershell
python -m pytest tests/test_discord_engine.py tests/test_credentials.py tests/test_package.py tests/test_run.py tests/test_store.py -q
python -m ruff check src/gather/discord.py src/gather/credentials.py src/gather/__init__.py tests/test_discord_engine.py
python -m mypy src/gather/discord.py src/gather/credentials.py
~~~

Expected: all commands pass. Invalid plan tests prove the credential reader remains untouched.

- [ ] **Step 8: Commit the shared Python engine**

Run:

~~~powershell
git add src/gather/discord.py src/gather/discord_store.py src/gather/credentials.py src/gather/__init__.py tests/test_discord_engine.py tests/test_discord_store.py tests/test_credentials.py tests/test_package.py
git commit -m "feat(discord): orchestrate redacted capture receipts"
~~~

Expected: one commit for the shared engine, read-only status, credential-state diagnostic, and public API.

### Task 10: CLI, MCP, Status, and Doctor Parity

**Files:**
- Create: `src/gather/discord_cmd.py`
- Create: `tests/test_discord_cli.py`
- Create: `tests/test_discord_mcp.py`
- Modify: `src/gather/cli.py:1-212`
- Modify: `src/gather/mcp.py:42-236`
- Modify: `src/gather/flagship.py:9-77`
- Test: `tests/test_cli.py`
- Test: `tests/test_mcp.py`

**Interfaces:**
- Consumes: high-level receipt types and functions from `gather.discord`.
- Produces: nested `gather discord` commands and six closed MCP tools that emit the same receipt dictionaries; discovery accepts only a federation ID and never authorizes capture.

- [ ] **Step 1: Write failing CLI shape and dry validation tests**

Create `tests/test_discord_cli.py`:

~~~python
import json
from pathlib import Path

from gather.cli import main

FIXTURES = Path(__file__).parent / "fixtures" / "discord"


def test_discord_plan_validate_is_pure_and_receipt_only(capsys) -> None:
    rc = main([
        "discord","plan","validate",
        str(FIXTURES / "plan-valid.json"),
        "--registry",str(FIXTURES / "federation-valid.json"),
        "--json",
    ])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["schema"] == "gather.discord-plan-validation/v1"
    assert "queries" not in payload
    assert "guilds" not in payload
~~~

- [ ] **Step 2: Write failing MCP closed-schema tests**

Create `tests/test_discord_mcp.py`:

~~~python
import json

from gather.mcp import handle_request


def _call(name: str, arguments: dict):
    return handle_request({"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":name,"arguments":arguments}})


def test_discord_tools_are_advertised_with_closed_plan_id_inputs() -> None:
    response = handle_request({"jsonrpc":"2.0","id":1,"method":"tools/list"})
    tools = {tool["name"]:tool for tool in response["result"]["tools"]}
    expected = {
        "gather.discord.validate",
        "gather.discord.discover",
        "gather.discord.preflight",
        "gather.discord.capture",
        "gather.discord.status",
        "gather.discord.doctor",
    }
    assert expected <= set(tools)
    for name in expected - {"gather.discord.doctor","gather.discord.discover"}:
        schema = tools[name]["inputSchema"]
        assert schema["required"] == ["plan_id"]
        assert schema["additionalProperties"] is False
    assert tools["gather.discord.discover"]["inputSchema"]["required"] == ["federation_id"]
    assert tools["gather.discord.discover"]["inputSchema"]["additionalProperties"] is False


def test_mcp_rejects_inline_scope_and_paths() -> None:
    response = _call("gather.discord.capture",{"plan_id":"hdr-rendering-research-v1","guild_id":"1080142797870485606"})
    assert response["result"]["isError"] is True
    assert "unknown argument" in response["result"]["content"][0]["text"]
~~~

- [ ] **Step 3: Run host tests and observe the red state**

Run:

~~~powershell
python -m pytest tests/test_discord_cli.py tests/test_discord_mcp.py -q
~~~

Expected: FAIL because the CLI tree and MCP tool catalog do not contain Discord surfaces.

- [ ] **Step 4: Add shared CLI handlers**

Create `src/gather/discord_cmd.py`:

~~~python
from __future__ import annotations

import json
import sys
from pathlib import Path

from gather.discord import (
    capture_plan,
    discord_doctor,
    official_discovery_client_after_authorization,
    official_client_after_validation,
    preflight_plan,
    status_plan,
    validate_plan,
)
from gather.discord_preflight import discover_guild_channels
from gather.discord_plan import load_approved_plan, parse_capture_plan
from gather.discord_store import DiscordCaptureStore
from gather.store import Corpus


def _rows(path: str) -> list[dict]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = value.get("sources") if isinstance(value,dict) else value
    if not isinstance(rows,list):
        raise ValueError("Discord federation registry must contain sources")
    return rows


def _plan(path: str, registry: str):
    return parse_capture_plan(json.loads(Path(path).read_text(encoding="utf-8")),federation_rows=_rows(registry))


def _emit(value: dict, as_json: bool) -> int:
    if as_json:
        print(json.dumps(value,indent=2,sort_keys=True))
    else:
        print(f"status={value['status']} schema={value['schema']}")
    return 0


def cmd_discord_plan_validate(args) -> int:
    try:
        rows = _rows(args.registry)
        plan = parse_capture_plan(
            json.loads(Path(args.plan).read_text(encoding="utf-8")),
            federation_rows=rows,
        )
        receipt = validate_plan(plan,federation_rows=rows)
    except Exception as exc:
        print(f"discord plan validate failed: {exc}",file=sys.stderr)
        return 1
    return _emit(receipt.as_dict(),args.json)


def cmd_discord_doctor(args) -> int:
    return _emit(discord_doctor(plan_root_configured=bool(args.plan_root),corpus_root_configured=bool(args.corpus_root)).as_dict(),args.json)


def cmd_discord_discover(args) -> int:
    try:
        rows = _rows(args.registry)
        client = official_discovery_client_after_authorization(
            args.federation_id,federation_rows=rows,
        )
        receipt = discover_guild_channels(
            args.federation_id,federation_rows=rows,client=client,
        )
    except Exception as exc:
        print(f"discord discover failed: {exc}",file=sys.stderr)
        return 1
    return _emit(receipt.as_dict(),args.json)
~~~

Append the remaining handlers to the same file:

~~~python
def cmd_discord_preflight(args) -> int:
    try:
        rows = _rows(args.registry)
        plan = parse_capture_plan(json.loads(Path(args.plan).read_text(encoding="utf-8")),federation_rows=rows)
        client = official_client_after_validation(plan,federation_rows=rows)
        receipt = preflight_plan(plan,client=client)
    except Exception as exc:
        print(f"discord preflight failed: {exc}",file=sys.stderr)
        return 1
    return _emit(receipt.as_dict(),args.json)


def _capture_store(path: str) -> DiscordCaptureStore:
    root = Path(path)
    return DiscordCaptureStore(
        Corpus(str(root)),
        state_root=root / "discord-state",
    )


def cmd_discord_capture(args) -> int:
    try:
        rows = _rows(args.registry)
        plan = parse_capture_plan(json.loads(Path(args.plan).read_text(encoding="utf-8")),federation_rows=rows)
        client = official_client_after_validation(plan,federation_rows=rows)
        receipt = capture_plan(
            plan,
            federation_rows=rows,
            client=client,
            store=_capture_store(args.store),
        )
    except Exception as exc:
        print(f"discord capture failed: {exc}",file=sys.stderr)
        return 1
    return _emit(receipt.as_dict(),args.json)


def cmd_discord_status(args) -> int:
    try:
        plan = _plan(args.plan,args.registry)
        receipt = status_plan(plan,store=_capture_store(args.store))
    except Exception as exc:
        print(f"discord status failed: {exc}",file=sys.stderr)
        return 1
    return _emit(receipt.as_dict(),args.json)
~~~

- [ ] **Step 5: Add the nested CLI parser**

Add `_add_discord_parser(sub)` to `src/gather/cli.py`:

~~~python
def _add_discord_parser(sub) -> None:
    from gather.discord_cmd import (
        cmd_discord_capture,
        cmd_discord_discover,
        cmd_discord_doctor,
        cmd_discord_plan_validate,
        cmd_discord_preflight,
        cmd_discord_status,
    )
    discord = sub.add_parser("discord",help="redacted research intake through an official Discord bot")
    actions = discord.add_subparsers(dest="discord_action",required=True)
    plan = actions.add_parser("plan",help="validate a sealed Discord capture plan")
    plan_actions = plan.add_subparsers(dest="discord_plan_action",required=True)
    validate = plan_actions.add_parser("validate")
    validate.add_argument("plan")
    validate.add_argument("--registry",required=True)
    validate.add_argument("--json",action="store_true")
    validate.set_defaults(func=cmd_discord_plan_validate)
    discover = actions.add_parser("discover",help="enumerate public IDs without capture authority")
    discover.add_argument("federation_id")
    discover.add_argument("--registry",required=True)
    discover.add_argument("--json",action="store_true")
    discover.set_defaults(func=cmd_discord_discover)
    for name,handler in (("preflight",cmd_discord_preflight),("capture",cmd_discord_capture),("status",cmd_discord_status)):
        parser = actions.add_parser(name)
        parser.add_argument("plan")
        parser.add_argument("--registry",required=True)
        if name in {"capture","status"}:
            parser.add_argument("--store",required=True)
        parser.add_argument("--json",action="store_true")
        parser.set_defaults(func=handler)
    doctor = actions.add_parser("doctor")
    doctor.add_argument("--plan-root",default=None)
    doctor.add_argument("--corpus-root",default=None)
    doctor.add_argument("--json",action="store_true")
    doctor.set_defaults(func=cmd_discord_doctor)
~~~

Call `_add_discord_parser(sub)` immediately after `_add_flagship_commands(sub)`.

- [ ] **Step 6: Add closed MCP tool definitions and manual argument rejection**

Add these tool definitions to `_tool_defs()` in `src/gather/mcp.py`:

~~~python
def _discord_schema(kind: str) -> dict:
    properties = {}
    required = []
    if kind == "plan":
        properties = {"plan_id":{"type":"string","pattern":"^[a-z0-9]+(?:-[a-z0-9]+)*$"}}
        required = ["plan_id"]
    elif kind == "discovery":
        properties = {"federation_id":{"type":"string","pattern":"^[a-z0-9]+(?:-[a-z0-9]+)*$"}}
        required = ["federation_id"]
    return {"type":"object","properties":properties,"required":required,"additionalProperties":False}
~~~

Each definition uses one of the six names above. Use `_discord_schema("none")` for doctor, `_discord_schema("discovery")` for discover, and `_discord_schema("plan")` for the other four.

Add:

~~~python
def _closed_args(args: dict, *, allowed: set[str], required: set[str]) -> None:
    unknown = sorted(set(args) - allowed)
    missing = sorted(required - set(args))
    if unknown:
        raise ValueError(f"unknown argument(s): {unknown}")
    if missing:
        raise ValueError(f"missing argument(s): {missing}")
~~~

For MCP runtime roots, read only these environment variables:

~~~text
GATHER_DISCORD_PLAN_ROOT
GATHER_DISCORD_FEDERATION_REGISTRY
GATHER_DISCORD_CORPUS_ROOT
~~~

Import `os` and `Path`, then add this dispatcher:

~~~python
def _discord_runtime() -> tuple[Path,Path,Path,list[dict]]:
    plan_value = os.environ.get("GATHER_DISCORD_PLAN_ROOT","")
    registry_value = os.environ.get("GATHER_DISCORD_FEDERATION_REGISTRY","")
    corpus_value = os.environ.get("GATHER_DISCORD_CORPUS_ROOT","")
    if not plan_value or not registry_value or not corpus_value:
        raise ValueError("Discord MCP roots are not fully configured")
    plan_root = Path(plan_value)
    registry_path = Path(registry_value)
    corpus_root = Path(corpus_value)
    parsed = json.loads(registry_path.read_text(encoding="utf-8"))
    rows = parsed.get("sources") if isinstance(parsed,dict) else parsed
    if not isinstance(rows,list):
        raise ValueError("Discord federation registry must contain sources")
    return plan_root,registry_path,corpus_root,rows


def _discord_tool(name: str, args: dict) -> str:
    from gather.discord import (
        capture_plan,
        discord_doctor,
        official_discovery_client_after_authorization,
        official_client_after_validation,
        preflight_plan,
        status_plan,
        validate_plan,
    )
    from gather.discord_preflight import discover_guild_channels
    from gather.discord_plan import load_approved_plan
    from gather.discord_store import DiscordCaptureStore
    from gather.store import Corpus

    if name == "gather.discord.doctor":
        _closed_args(args,allowed=set(),required=set())
        receipt = discord_doctor(
            plan_root_configured=bool(os.environ.get("GATHER_DISCORD_PLAN_ROOT")),
            corpus_root_configured=bool(os.environ.get("GATHER_DISCORD_CORPUS_ROOT")),
        )
        return json.dumps(receipt.as_dict(),indent=2,sort_keys=True)
    if name == "gather.discord.discover":
        _closed_args(args,allowed={"federation_id"},required={"federation_id"})
        federation_id = args["federation_id"]
        if not isinstance(federation_id,str):
            raise ValueError("federation_id must be a string")
        _plan_root,_registry_path,_corpus_root,rows = _discord_runtime()
        client = official_discovery_client_after_authorization(
            federation_id,federation_rows=rows,
        )
        receipt = discover_guild_channels(
            federation_id,federation_rows=rows,client=client,
        )
        return json.dumps(receipt.as_dict(),indent=2,sort_keys=True)
    _closed_args(args,allowed={"plan_id"},required={"plan_id"})
    plan_id = args["plan_id"]
    if not isinstance(plan_id,str):
        raise ValueError("plan_id must be a string")
    plan_root,_registry_path,corpus_root,rows = _discord_runtime()
    plan = load_approved_plan(plan_id,plan_root=plan_root,federation_rows=rows)
    store = DiscordCaptureStore(
        Corpus(str(corpus_root / plan_id)),
        state_root=corpus_root / plan_id / "discord-state",
    )
    if name == "gather.discord.validate":
        receipt = validate_plan(plan,federation_rows=rows)
    elif name == "gather.discord.preflight":
        receipt = preflight_plan(
            plan,
            client=official_client_after_validation(plan,federation_rows=rows),
        )
    elif name == "gather.discord.capture":
        receipt = capture_plan(
            plan,
            federation_rows=rows,
            client=official_client_after_validation(plan,federation_rows=rows),
            store=store,
        )
    elif name == "gather.discord.status":
        receipt = status_plan(plan,store=store)
    else:
        raise ValueError(f"unknown Discord tool: {name}")
    return json.dumps(receipt.as_dict(),indent=2,sort_keys=True)
~~~

In `call_tool`, dispatch names beginning with `gather.discord.` to `_discord_tool(name,args)` before the final unknown-tool error. The dispatcher accepts only `plan_id`, resolves `plan_root / (plan_id + ".json")` through `load_approved_plan`, derives the corpus directory as `corpus_root / plan_id`, and never returns configured paths.

- [ ] **Step 7: Align status and doctor advertising**

Modify `PRIMARY_COMMANDS` and `status_payload()["native"]["mcp_tools"]` in `src/gather/flagship.py` to advertise `discord` and the six Discord MCP names.

Add one privacy-safe check to `doctor_payload()`:

~~~python
{"name":"discord_official_bot_token","status":secret_state("GATHER_DISCORD_BOT_TOKEN").upper()}
~~~

Do not place environment values, paths, guild IDs, or channel IDs in the flagship envelope.

- [ ] **Step 8: Run CLI/MCP/doctor parity tests**

Run:

~~~powershell
python -m pytest tests/test_discord_cli.py tests/test_discord_mcp.py tests/test_cli.py tests/test_mcp.py tests/test_credentials.py -q
python -m ruff check src/gather/discord_cmd.py src/gather/cli.py src/gather/mcp.py src/gather/flagship.py tests/test_discord_cli.py tests/test_discord_mcp.py
python -m mypy src/gather
~~~

Expected: all commands pass; CLI and MCP validation payloads compare equal after excluding host-only formatting.

- [ ] **Step 9: Prove direct run-config Discord targets remain unavailable**

Add to `tests/test_discord_cli.py`:

~~~python
def test_general_run_config_rejects_direct_discord_targets() -> None:
    from gather.run_config import build_source
    import pytest
    with pytest.raises(ValueError,match="unknown source"):
        build_source("discord",{"target":"1081121447960915989"})
    with pytest.raises(ValueError,match="unknown source"):
        build_source("discord_guild",{"target":"1080142797870485606"})
~~~

Run:

~~~powershell
python -m pytest tests/test_discord_cli.py::test_general_run_config_rejects_direct_discord_targets -q
~~~

Expected: PASS. General `gather run` cannot bypass sealed-plan capture.

- [ ] **Step 10: Commit host parity**

Run:

~~~powershell
git add src/gather/discord_cmd.py src/gather/cli.py src/gather/mcp.py src/gather/flagship.py tests/test_discord_cli.py tests/test_discord_mcp.py tests/test_cli.py tests/test_mcp.py
git commit -m "feat(discord): expose receipt-only host surfaces"
~~~

Verify without relying on prior shell state:

~~~powershell
$planTip = (git -C C:\dev\public\gather config --get gather.discordPlanTip).Trim()
if (-not $planTip) { throw "reviewed plan tip is not recorded" }
git diff --exit-code $planTip -- src/gather/run_config.py
~~~

Expected: one host-surface commit; `src/gather/run_config.py` remains unchanged from the freshly resolved recorded plan tip.

### Task 11: Token-Efficient Local Evidence Packets and Claim Gate

**Files:**
- Create: `src/gather/discord_synthesis.py`
- Create: `tests/test_discord_synthesis.py`

**Interfaces:**
- Consumes: stored `discord-api-message` Items only.
- Produces: `TechnicalEvidence`, `EvidenceGroup`, `PublicLinkLead`, `EvidencePacket`, `ClaimRecord`, `LocalClaimModel`, `group_thread_replies(...)`, `technical_score(...)`, `extract_public_link_leads(...)`, `split_evidence_group(...)`, `build_evidence_packets(items, *, max_chars)`, and `extract_claims(model, packets)`.

- [ ] **Step 1: Write failing bounded-packet and evidence-reference tests**

Create `tests/test_discord_synthesis.py`:

~~~python
import json

import pytest

from gather.discord_synthesis import (
    ClaimError,
    build_evidence_packets,
    extract_claims,
)
from gather.item import make_item


def _message(message_id: str, content: str, *, channel_id="10", thread_id=None, reply_to=None, public_links=()):
    text = json.dumps({"schema":"gather.discord-message/v1","classification":"community_claim","message_id":message_id,"guild_id":"9","channel_id":channel_id,"thread_id":thread_id,"reply_to":reply_to,"content":content,"public_links":list(public_links),"plan_digest":"a" * 64},sort_keys=True)
    return make_item(kind="community_claim",id=message_id,title=f"Discord technical message {message_id}",text=text,source="discord",ref=f"discord://message/{message_id}",method="discord-api-message",fetched_at=1.0,meta={})


def test_packets_deduplicate_and_remain_bounded() -> None:
    items = [_message("1","PQ paper white evidence"),_message("2","PQ paper white evidence"),_message("3","different tone mapping evidence")]
    packets = build_evidence_packets(items,max_chars=180)
    assert all(len(packet.text) <= 180 for packet in packets)
    assert sum(len(packet.evidence_refs) for packet in packets) == 2
    assert all("author" not in packet.text.casefold() for packet in packets)


def test_model_claim_with_unknown_evidence_ref_is_rejected() -> None:
    class LocalModel:
        def extract(self, packet):
            return [{"claim":"PQ claim","evidence_refs":["f" * 64],"confidence":0.9,"status":"community_claim","followup_leads":[]}]
    packets = build_evidence_packets([
        _message(
            "1","PQ evidence",public_links=("https://example.com/paper",),
        ),
    ],max_chars=180)
    with pytest.raises(ClaimError,match="unknown evidence"):
        extract_claims(LocalModel(),packets)


def test_model_followup_leads_are_limited_to_deterministic_packet_leads() -> None:
    class InventingModel:
        def extract(self, packet):
            return [{"claim":"PQ claim","evidence_refs":list(packet.evidence_refs),"confidence":0.9,"status":"community_claim","followup_leads":["https://evil.example/invented"]}]
    packets = build_evidence_packets([
        _message("1","PQ paper",public_links=("https://example.com/paper",)),
    ],max_chars=180)
    with pytest.raises(ClaimError,match="followup lead absent"):
        extract_claims(InventingModel(),packets)


def test_thread_and_reply_grouping_precedes_relevance_ranking_and_packets() -> None:
    parent = _message("1","PQ EOTF maps paper white at 203 nits",thread_id="20")
    reply = _message(
        "2","BT.2390 changes the shoulder transform",thread_id="20",
        reply_to={"guild_id":"9","channel_id":"20","message_id":"1"},
    )
    low = _message("3","looks nice today")
    packets = build_evidence_packets([low,reply,parent],max_chars=240)
    assert packets[0].evidence_refs == (
        parent.provenance.sha256,reply.provenance.sha256,
    )
    assert packets[0].technical_score > packets[-1].technical_score
    assert "PQ EOTF" in packets[0].text and "BT.2390" in packets[0].text


def test_public_link_leads_are_deterministic_and_evidence_bound() -> None:
    item = _message(
        "1","See the tone-mapping paper",public_links=(
            "https://doi.org/10.1000/example","https://example.com/paper",
        ),
    )
    packet = build_evidence_packets([item],max_chars=240)[0]
    assert [lead.url for lead in packet.public_link_leads] == [
        "https://doi.org/10.1000/example","https://example.com/paper",
    ]
    assert all(lead.evidence_refs == (item.provenance.sha256,) for lead in packet.public_link_leads)


def test_large_group_splits_without_dangling_or_ambiguously_cut_refs() -> None:
    items = [
        _message("1","PQ paper white at 203 nits",thread_id="20"),
        _message("2","BT.2390 shoulder transform evidence",thread_id="20"),
        _message("3","scRGB linear-light comparison evidence",thread_id="20"),
    ]
    packets = build_evidence_packets(items,max_chars=55)
    id_by_ref = {item.provenance.sha256:json.loads(item.text)["message_id"] for item in items}
    assert len(packets) >= 2
    assert all(len(packet.text) <= 55 for packet in packets)
    assert {ref for packet in packets for ref in packet.evidence_refs} == set(id_by_ref)
    for packet in packets:
        for ref in packet.evidence_refs:
            assert f"[{id_by_ref[ref]}] " in packet.text
        for message_id in set(id_by_ref.values()) - {id_by_ref[ref] for ref in packet.evidence_refs}:
            assert f"[{message_id}] " not in packet.text


def test_single_long_segment_keeps_whole_tag_and_explicit_truncation_marker() -> None:
    item = _message("123","PQ " + "evidence " * 100)
    packet = build_evidence_packets([item],max_chars=64)[0]
    assert packet.text.startswith("[123] ")
    assert packet.text.endswith(" …[truncated]")
    assert packet.evidence_refs == (item.provenance.sha256,)
~~~

- [ ] **Step 2: Run synthesis tests and observe the red state**

Run:

~~~powershell
python -m pytest tests/test_discord_synthesis.py -q
~~~

Expected: FAIL during collection because `gather.discord_synthesis` does not exist.

- [ ] **Step 3: Add deterministic packet types and exact/near dedupe**

Create `src/gather/discord_synthesis.py`:

~~~python
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from typing import Any, Protocol, Sequence

from gather.item import Item


class ClaimError(ValueError):
    pass


def _canonical(value: object) -> str:
    return json.dumps(
        value,sort_keys=True,separators=(",",":"),ensure_ascii=False,
    )


@dataclass(frozen=True, slots=True)
class TechnicalEvidence:
    evidence_ref: str
    message_id: str
    channel_id: str
    thread_id: str | None
    reply_to_id: str | None
    content: str
    public_links: tuple[str,...]


@dataclass(frozen=True, slots=True)
class PublicLinkLead:
    url: str
    evidence_refs: tuple[str,...]


@dataclass(frozen=True, slots=True)
class EvidenceGroup:
    group_id: str
    evidence: tuple[TechnicalEvidence,...]
    score: int
    leads: tuple[PublicLinkLead,...]


@dataclass(frozen=True, slots=True)
class EvidencePacket:
    packet_id: str
    evidence_refs: tuple[str,...]
    technical_score: int
    public_link_leads: tuple[PublicLinkLead,...]
    text: str


@dataclass(frozen=True, slots=True)
class ClaimRecord:
    claim: str
    evidence_refs: tuple[str,...]
    confidence: float
    status: str
    followup_leads: tuple[str,...]


class LocalClaimModel(Protocol):
    def extract(self, packet: EvidencePacket) -> list[dict[str,Any]]: ...


def _tokens(text: str) -> frozenset[str]:
    return frozenset(re.findall(r"[a-z0-9]+",text.casefold()))


def _near_duplicate(left: str, right: str) -> bool:
    a,b = _tokens(left),_tokens(right)
    union = a | b
    return bool(union) and len(a & b) / len(union) >= 0.9


TECHNICAL_TERMS = frozenset({
    "pq","hlg","scrgb","eotf","oetf","gamut","matrix","lut","icc",
    "nits","luminance","chromaticity","tone","mapping","bt","2390",
    "rec2020","display","calibration","paper","white","shader","hdr",
})


def technical_score(evidence: Sequence[TechnicalEvidence]) -> int:
    tokens = _tokens(" ".join(row.content for row in evidence))
    term_score = 3 * len(tokens & TECHNICAL_TERMS)
    numeric_score = min(5,sum(ch.isdigit() for row in evidence for ch in row.content))
    source_score = 2 * len({url for row in evidence for url in row.public_links})
    reply_score = sum(row.reply_to_id is not None for row in evidence)
    return term_score + numeric_score + source_score + reply_score


def extract_public_link_leads(
    evidence: Sequence[TechnicalEvidence],
) -> tuple[PublicLinkLead,...]:
    refs_by_url: dict[str,set[str]] = {}
    for row in evidence:
        for url in row.public_links:
            refs_by_url.setdefault(url,set()).add(row.evidence_ref)
    return tuple(
        PublicLinkLead(url,tuple(sorted(refs)))
        for url,refs in sorted(refs_by_url.items())
    )


def group_thread_replies(
    evidence: Sequence[TechnicalEvidence],
) -> tuple[EvidenceGroup,...]:
    by_id = {row.message_id:row for row in evidence}
    def root(row: TechnicalEvidence) -> str:
        if row.thread_id:
            return f"thread:{row.thread_id}"
        seen = {row.message_id}
        parent = row.reply_to_id
        while parent and parent in by_id and parent not in seen:
            seen.add(parent)
            row = by_id[parent]
            parent = row.reply_to_id
        return f"reply:{row.message_id}" if len(seen) > 1 else f"message:{row.message_id}"
    grouped: dict[str,list[TechnicalEvidence]] = {}
    for row in evidence:
        grouped.setdefault(root(row),[]).append(row)
    result: list[EvidenceGroup] = []
    for group_id,rows in grouped.items():
        ordered = tuple(sorted(rows,key=lambda row: int(row.message_id)))
        result.append(EvidenceGroup(
            group_id,ordered,technical_score(ordered),
            extract_public_link_leads(ordered),
        ))
    return tuple(sorted(result,key=lambda group: (-group.score,group.group_id)))


TRUNCATION_MARKER = " …[truncated]"


def _bounded_segment(row: TechnicalEvidence, *, max_chars: int) -> str:
    tag = f"[{row.message_id}] "
    if len(tag) + len(TRUNCATION_MARKER) + 1 > max_chars:
        raise ClaimError("max_chars is too small for an evidence segment")
    segment = tag + row.content
    if len(segment) <= max_chars:
        return segment
    body_budget = max_chars - len(tag) - len(TRUNCATION_MARKER)
    return tag + row.content[:body_budget].rstrip() + TRUNCATION_MARKER


def split_evidence_group(
    group: EvidenceGroup,
    *,
    max_chars: int,
) -> tuple[EvidencePacket,...]:
    packets: list[EvidencePacket] = []
    rows: list[TechnicalEvidence] = []
    segments: list[str] = []

    def flush() -> None:
        if not rows:
            return
        refs = tuple(row.evidence_ref for row in rows)
        ref_set = set(refs)
        leads = tuple(
            PublicLinkLead(
                lead.url,tuple(ref for ref in lead.evidence_refs if ref in ref_set),
            )
            for lead in group.leads
            if ref_set.intersection(lead.evidence_refs)
        )
        text = "\n".join(segments)
        score = technical_score(rows)
        packet_id = hashlib.sha256(_canonical({
            "refs":refs,"score":score,
            "leads":[asdict(lead) for lead in leads],"text":text,
        }).encode()).hexdigest()
        packets.append(EvidencePacket(packet_id,refs,score,leads,text))
        rows.clear()
        segments.clear()

    for row in group.evidence:
        segment = _bounded_segment(row,max_chars=max_chars)
        candidate = segment if not segments else "\n".join((*segments,segment))
        if segments and len(candidate) > max_chars:
            flush()
        rows.append(row)
        segments.append(segment)
    flush()
    return tuple(packets)


def build_evidence_packets(items: Sequence[Item], *, max_chars: int) -> tuple[EvidencePacket,...]:
    if max_chars <= 0:
        raise ClaimError("max_chars must be positive")
    admitted: list[TechnicalEvidence] = []
    for item in items:
        if item.provenance.method != "discord-api-message" or not item.verify():
            continue
        payload = json.loads(item.text)
        if payload.get("classification") != "community_claim":
            continue
        content = str(payload.get("content",""))
        if any(_near_duplicate(content,prior.content) for prior in admitted):
            continue
        reply = payload.get("reply_to")
        admitted.append(TechnicalEvidence(
            item.provenance.sha256,str(payload["message_id"]),
            str(payload["channel_id"]),
            str(payload["thread_id"]) if payload.get("thread_id") else None,
            str(reply["message_id"]) if isinstance(reply,dict) and reply.get("message_id") else None,
            content,tuple(sorted(str(url) for url in payload.get("public_links",[]))),
        ))
    packets: list[EvidencePacket] = []
    for group in group_thread_replies(admitted):
        packets.extend(split_evidence_group(group,max_chars=max_chars))
    return tuple(packets)
~~~

Define `_canonical(value)` as sorted compact JSON. The stage order is fixed and tested: verify/redacted parse → exact/near dedupe → reply/thread grouping → technical scoring → public-link lead extraction → complete tagged-segment packing → local model. A packet contains a reference only when that reference's complete tag and either complete content or explicitly marked truncated content are present. The final packet text is never sliced. The model cannot reorder or invent those deterministic stages.

- [ ] **Step 4: Add the closed claim/evidence-reference gate**

Append to `src/gather/discord_synthesis.py`:

~~~python
def extract_claims(
    model: LocalClaimModel,
    packets: Sequence[EvidencePacket],
) -> tuple[ClaimRecord,...]:
    known = {ref for packet in packets for ref in packet.evidence_refs}
    claims: list[ClaimRecord] = []
    for packet in packets:
        for raw in model.extract(packet):
            if set(raw) != {"claim","evidence_refs","confidence","status","followup_leads"}:
                raise ClaimError("claim shape is not closed")
            refs = tuple(str(ref) for ref in raw["evidence_refs"])
            if not refs or not set(refs) <= known or not set(refs) <= set(packet.evidence_refs):
                raise ClaimError("claim contains an unknown evidence reference")
            confidence = float(raw["confidence"])
            if not 0.0 <= confidence <= 1.0:
                raise ClaimError("claim confidence must be between zero and one")
            if raw["status"] != "community_claim":
                raise ClaimError("Discord synthesis status must remain community_claim")
            followup_leads = tuple(str(value) for value in raw["followup_leads"])
            allowed_leads = {lead.url for lead in packet.public_link_leads}
            if not set(followup_leads) <= allowed_leads:
                raise ClaimError("claim contains a followup lead absent from its packet")
            claims.append(ClaimRecord(
                str(raw["claim"]),refs,confidence,"community_claim",followup_leads,
            ))
    return tuple(claims)
~~~

- [ ] **Step 5: Add a spy proving only redacted packets reach the model**

Append to `tests/test_discord_synthesis.py`:

~~~python
def test_local_model_receives_only_bounded_redacted_packet() -> None:
    seen = []
    class Spy:
        def extract(self, packet):
            seen.append(packet)
            return [{"claim":"bounded claim","evidence_refs":list(packet.evidence_refs),"confidence":0.5,"status":"community_claim","followup_leads":["https://example.com/paper"]}]
    packets = build_evidence_packets([
        _message(
            "1","PQ evidence",public_links=("https://example.com/paper",),
        ),
    ],max_chars=180)
    claims = extract_claims(Spy(),packets)
    assert len(claims) == 1
    assert seen == list(packets)
    assert all(len(packet.text) <= 180 for packet in seen)
~~~

- [ ] **Step 6: Run synthesis and receipt tests**

Run:

~~~powershell
python -m pytest tests/test_discord_synthesis.py tests/test_discord_receipts.py tests/test_derive.py -q
python -m ruff check src/gather/discord_synthesis.py tests/test_discord_synthesis.py
python -m mypy src/gather/discord_synthesis.py
~~~

Expected: all commands pass. No remote model, embedding, training, or redistribution interface exists.

- [ ] **Step 7: Commit the local evidence gate**

Run:

~~~powershell
git add src/gather/discord_synthesis.py tests/test_discord_synthesis.py
git commit -m "feat(discord): build bounded local evidence packets"
~~~

Expected: one synthesis-boundary commit.

### Task 12: Documentation, Three-Guild Fixture Acceptance, and Release Gates

**Files:**
- Create: `examples/discord/federation.example.json`
- Create: `examples/discord/plan.example.json`
- Create: `tests/fixtures/discord/plan-three-guilds.json`
- Create: `tests/fixtures/discord/federation-three-guilds.json`
- Create: `tests/test_discord_acceptance.py`
- Modify: `README.md`
- Modify: `USAGE.md`
- Modify: `CHANGELOG.md`
- Modify: `ARCHITECTURE.md`
- Modify: `docs/ENTERPRISE-READINESS.md`
- Modify: `tests/test_docs.py`

**Interfaces:**
- Consumes: complete fixture-tested collector and host surfaces.
- Produces: truthful installation/use/security documentation and a secret-free three-guild acceptance receipt.

- [ ] **Step 1: Write the failing documentation contract**

Append to `tests/test_docs.py`:

~~~python
def test_discord_docs_pin_the_safe_workflow_and_prohibitions() -> None:
    root = Path(__file__).resolve().parents[1]
    combined = "\n".join((root / name).read_text(encoding="utf-8") for name in (
        "README.md","USAGE.md","ARCHITECTURE.md","docs/ENTERPRISE-READINESS.md"))
    for phrase in (
        "GATHER_DISCORD_BOT_TOKEN",
        "official Discord bot",
        "durable redacted evidence",
        "transient raw",
        "metadata-only",
        "query-first",
        "private threads",
        "not training data",
    ):
        assert phrase.casefold() in combined.casefold()
    assert '"source": "discord_guild"' not in combined
    assert "user token" in combined.casefold()
    assert "self-bot" in combined.casefold()
~~~

- [ ] **Step 2: Run the docs contract and observe the red state**

Run:

~~~powershell
python -m pytest tests/test_docs.py::test_discord_docs_pin_the_safe_workflow_and_prohibitions -q
~~~

Expected: FAIL because the clean README and supporting documents do not yet describe the collector.

- [ ] **Step 3: Document only the sealed-plan workflow**

Add these exact command examples to `README.md` and `USAGE.md`:

~~~powershell
gather discord plan validate plan.json --registry federation.json --json
gather discord preflight plan.json --registry federation.json --json
gather discord capture plan.json --registry federation.json --store .\research-corpus --json
gather discord status plan.json --registry federation.json --store .\research-corpus --json
gather discord doctor --json
~~~

State immediately beside the examples:

~~~text
Discord intake uses an official Discord bot and GATHER_DISCORD_BOT_TOKEN only.
Raw API responses are transient; durable output is deterministic redacted evidence.
Search is query-first, attachment handling is metadata-only, private threads are rejected,
and community messages are research evidence rather than training data.
~~~

Do not document direct `gather run` Discord targets.

- [ ] **Step 4: Document architecture, limitations, and release posture**

Add an `Official Discord research boundary` section to `ARCHITECTURE.md` covering typed routes, pinned origin, redaction before storage, separate discovery edges, manifest-before-checkpoint ordering, and receipt-only host outputs.

Add an `Unreleased` changelog entry listing the new modules, command/MCP surfaces, privacy posture, and fixture-only acceptance.

Add an enterprise-readiness section stating that operator bot invitation and live smoke remain external gates and that user-token/self-bot/browser-session paths are unsupported.

- [ ] **Step 5: Add a three-guild fixture plan**

Create `tests/fixtures/discord/plan-three-guilds.json` using only these approved guild IDs and one fake allowlisted channel snowflake per guild:

~~~json
{"schema_version":1,"plan_id":"hdr-three-guild-fixture-v1","guilds":[{"federation_id":"hdr-den-discord","guild_id":"1161035767917850784","channels":["2161035767917850784"],"threads":[],"history_channels":[],"include_public_threads":true,"include_private_threads":false},{"federation_id":"renodx-discord","guild_id":"1408098019194310818","channels":["2408098019194310818"],"threads":[],"history_channels":[],"include_public_threads":true,"include_private_threads":false},{"federation_id":"community-shaders-discord","guild_id":"1080142797870485606","channels":["2080142797870485606"],"threads":[],"history_channels":[],"include_public_threads":true,"include_private_threads":false}],"queries":["pq","scRGB","paper white","tone mapping"],"after":"2023-01-01T00:00:00Z","before":"2026-07-10T00:00:00Z","page_budget":12,"message_budget":120,"batch_size":25,"retry_budget":2,"indexing_retry_budget":2,"redaction_policy":"discord-technical-v1","attachment_policy":"metadata-only","raw_retention":"transient"}
~~~

Create `tests/fixtures/discord/federation-three-guilds.json`:

~~~json
{"sources":[{"id":"hdr-den-discord","system":"Discord","family":"HDR Den","domain":"display","access":"account_required","adapter":"discord","url":"discord://guild/1161035767917850784","scope":"authorized technical channels only","priority":"high"},{"id":"renodx-discord","system":"Discord","family":"RenoDX","domain":"rendering","access":"account_required","adapter":"discord","url":"discord://guild/1408098019194310818","scope":"authorized technical channels only","priority":"high"},{"id":"community-shaders-discord","system":"Discord","family":"Community Shaders","domain":"rendering","access":"account_required","adapter":"discord","url":"discord://guild/1080142797870485606","scope":"authorized technical channels only","priority":"high"}]}
~~~

These fixtures authorize tests only and do not perform network requests.

- [ ] **Step 6: Add recursive durable-output acceptance**

Create `tests/test_discord_acceptance.py`:

~~~python
import hashlib
import json
from pathlib import Path

from gather.discord_receipts import (
    DiscoveryEdge,
    discovery_edge_item,
    message_item,
)
from gather.discord_redaction import (
    assert_durable_private_data_free,
    redact_message,
    response_body_sha256,
)
from gather.discord_store import (
    CaptureCheckpoint,
    CaptureManifest,
    DiscordCaptureStore,
    manifest_identity,
)
from gather.discord_search import LaneKey, PageCursor
from gather.discord_plan import parse_capture_plan
from gather.store import Corpus


def test_fixture_corpus_and_state_have_no_private_values(tmp_path) -> None:
    fixture = Path(__file__).parent / "fixtures" / "discord" / "message-sensitive.json"
    raw = fixture.read_bytes()
    redacted = redact_message(
        json.loads(raw),
        guild_id="1080142797870485606",
        channel_id="1081121447960915989",
        thread_id=None,
        plan_digest="a" * 64,
        response_body_sha256=response_body_sha256(raw),
    )
    message = message_item(redacted,fetched_at=1.0)
    edge = discovery_edge_item(DiscoveryEdge(
        "a" * 64,
        "b" * 64,
        redacted.guild_id,
        redacted.channel_id,
        redacted.message_id,
        message.provenance.sha256,
        "discord-api-search-edge",
        None,
        None,
        0,
        0,
        redacted.response_body_sha256,
    ),fetched_at=1.0)
    corpus = Corpus(str(tmp_path / "corpus"),fsync=False)
    key = LaneKey("a" * 64,"c" * 64,redacted.guild_id,"search","b" * 64,(redacted.channel_id,),"1","9")
    cursor_before = PageCursor(0,None,0,None,False)
    cursor_after = PageCursor(25,None,0,None,False)
    before = CaptureCheckpoint(key,cursor_before,0,0,0,"bounded_observed",())
    after = CaptureCheckpoint(key,cursor_after,1,1,1,"bounded_observed",())
    manifest = _acceptance_manifest(
        manifest_id=manifest_identity("a" * 64,key.digest(),1,cursor_before),
        key=key,cursor_before=cursor_before,cursor_after=cursor_after,
        before=before,after=after,response_hash=redacted.response_body_sha256,
        item_hashes=(message.provenance.sha256,edge.provenance.sha256),
    )
    store = DiscordCaptureStore(
        corpus,
        state_root=tmp_path / "state",
        fsync=False,
    )
    store.commit_batch(
        items=[message,edge],
        manifest=manifest,
        checkpoint=after,
    )
    forbidden = (
        "fixture-secret",
        "authorization",
        "fixture-avatar",
        "raw_json",
        "proxy_url",
        "operator",
        "123456789012345678",
        "?ex=",
        "?token=",
    )
    for path in tmp_path.rglob("*"):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        lowered = text.casefold()
        assert not any(value in lowered for value in forbidden)
        if path.suffix == ".json":
            assert_durable_private_data_free(json.loads(text))
        elif path.name.endswith(".jsonl"):
            for line in text.splitlines():
                if line.strip():
                    assert_durable_private_data_free(json.loads(line))


def test_three_guild_fixture_plan_is_sealed_without_network() -> None:
    fixture_root = Path(__file__).parent / "fixtures" / "discord"
    plan = json.loads((fixture_root / "plan-three-guilds.json").read_text(encoding="utf-8"))
    rows = json.loads((fixture_root / "federation-three-guilds.json").read_text(encoding="utf-8"))["sources"]
    sealed = parse_capture_plan(plan,federation_rows=rows)
    assert len(sealed.plan.guilds) == 3
    assert len(sealed.digest) == 64
~~~

Define `_acceptance_manifest` in the acceptance test as a closed helper that supplies every Task 8 manifest field with deterministic fixture values. Assert its stored JSON includes the plan/redaction identities, lane/query/method, time and snowflake bounds, sealed budgets, requested/accepted counts, event/skipped-region lists, transient hash aggregate, durable hashes, both cursors, both checkpoints, and aggregate completeness.

- [ ] **Step 7: Run all deterministic release gates**

Run:

~~~powershell
python -m pytest -q --cov=src/gather --cov-report=term-missing --cov-fail-under=78
python -m ruff check src tests examples
python -m mypy src/gather
python -m gather status --json
python -m gather doctor --json
python -m gather discord doctor --json
git diff --check
~~~

Expected: every command exits zero except `discord doctor` may return an `UNVERIFIABLE` JSON status when no local token/root configuration exists; it must still exit zero and reveal no values.

- [ ] **Step 8: Run the tracked-file secret and privacy scan**

Run:

~~~powershell
git grep -n -I -E "(Bot [A-Za-z0-9._-]{20,}|Authorization:[[:space:]]*Bot|discord(app)?\\.com/api/webhooks/[0-9]+/[A-Za-z0-9._-]+)" -- . ":(exclude)tests/fixtures/**"
~~~

Expected: no matches.

Then run the repository's public-surface gate from the configured checkout:

~~~powershell
python -m public_surface_sweeper C:\dev\worktrees\gather-discord-redacted --workspace --json
~~~

Expected: a successful JSON result with no secret/private-source finding.

- [ ] **Step 9: Commit docs and fixture acceptance**

Run:

~~~powershell
git add README.md USAGE.md CHANGELOG.md ARCHITECTURE.md docs/ENTERPRISE-READINESS.md examples/discord tests/fixtures/discord/plan-three-guilds.json tests/fixtures/discord/federation-three-guilds.json tests/test_discord_acceptance.py tests/test_docs.py
git commit -m "docs(discord): ship redacted bot workflow"
~~~

Expected: one documentation/acceptance commit.

- [ ] **Step 10: Review final branch scope**

Run:

~~~powershell
git status --short
$repo = "C:\dev\public\gather"
$planPath = "docs/superpowers/plans/2026-07-10-redacted-official-discord-bot.md"
$planTip = (git -C $repo config --get gather.discordPlanTip).Trim()
if (-not $planTip) { throw "reviewed plan tip is not recorded" }
git merge-base --is-ancestor $planTip HEAD
if ($LASTEXITCODE -ne 0) { throw "implementation branch does not descend from recorded tip" }
git -C $repo merge-base --is-ancestor e84f423 $planTip
if ($LASTEXITCODE -ne 0) { throw "recorded tip does not descend from approved design" }
git -C $repo cat-file -e "$($planTip):$planPath"
if ($LASTEXITCODE -ne 0) { throw "recorded tip does not contain the reviewed plan" }
$forbidden = @("README.md","src/gather/method.py","src/gather/run_config.py","src/gather/discord.py","tests/test_discord.py")
$prototypeDiff = @(git -C $repo diff --name-only e84f423..$planTip | Where-Object { $forbidden -contains $_ })
if ($prototypeDiff.Count -ne 0) { throw "recorded tip contains prototype files" }
git log --oneline "$planTip..HEAD"
git diff --stat "$planTip..HEAD"
git diff --name-only "$planTip..HEAD"
~~~

Expected: the worktree is clean; commits follow Tasks 1–12; no credential file, `.env`, raw payload, or direct run-config Discord adapter appears.

## External Live-Smoke Gate

Fixture acceptance completes implementation but does not authorize a live request. After every Task 12 gate passes:

1. The operator creates or selects an official Discord application and bot.
2. The operator invites it only to approved guilds with the minimum metadata/search permissions.
3. The operator stores the token locally as `GATHER_DISCORD_BOT_TOKEN` without placing it in chat, a command argument, a file committed to Git, or a plan.
4. Run `gather discord preflight` first. Review IDs and capabilities in its receipt.
5. Seal explicit channel/thread allowlists.
6. Obtain explicit operator confirmation for one bounded test-channel capture.
7. Run a plan with one query, one channel, `page_budget=1`, `message_budget=25`, and `batch_size=25`.
8. Re-run corpus verification, the recursive privacy scan, status, and checkpoint resume.
9. Expand to the three approved guilds only after the bounded smoke produces no private-data, permission, completeness, or resume-integrity failure.

## Plan Self-Review Record

- **D1:** Task 1 seals scope, queries, bounds, budgets, policies, authorization, and redaction digests.
- **D2:** Tasks 1, 6, and 9 reject unknown/private/mismatched guild, channel, and thread scope before message routes.
- **D3:** Tasks 2 and 9 pin the credential origin and revalidate the sealed plan against trusted federation rows before reading a secret.
- **D4:** Task 7 makes guild search the only default discovery path.
- **D5:** Task 4 performs deterministic identity, mention, URL, and attachment redaction before Item creation.
- **D6:** Task 5 stores canonical messages and discovery edges separately.
- **D7:** Task 3 covers proactive buckets, 202, 429, global/shared scope, and bounded 5xx retries with injected clocks/sleepers.
- **D8:** Tasks 8–9 use stable lane keys, load a sealed next cursor before requests, atomically install immutable manifests without overwrite, order corpus/manifest/checkpoint durability, enforce one writer, recover from partial temp writes, and prove restart begins at the committed cursor without replaying an accepted page.
- **D9:** Tasks 7–9 cap offset at 9975, roll exclusive snowflake windows, initialize history at sealed `max_id`, reject all hit/context/history messages outside strict bounds, stop history at `min_id`, and resume from a stable sealed lane cursor.
- **D10:** Tasks 7–9 preserve budgets, page counts, drift, retry/indexing events, skipped regions, and worst-case warnings across the run; a later page cannot hide an earlier warning.
- **D11:** Task 4 supports metadata-only attachments and stores no CDN URL.
- **D12:** Tasks 9–10 make Python, CLI, and MCP share trusted federation resealing plus one mandatory-preflight capture engine; capture MCP accepts only approved plan IDs.
- **D13:** Tasks 9–10 emit privacy-safe discovery/preflight/capture/status/doctor receipts without credentials, identities, names, or raw payloads.
- **D14:** Task 11 deterministically deduplicates, groups threads/replies, scores technical relevance, extracts evidence-bound public-link leads, packs complete tagged segments with reference integrity, and bounds packets before local inference; unknown refs and model-invented leads are rejected.
- **D15:** Task 11 exposes no training/upload surface; Task 12 documents the separate approval requirement.
- **Type consistency:** The stable interface names at the top match the producing task and all later consumers.
- **Dirty-state protection:** Task 0 records the reviewed tip in repository-local Git config, freshly revalidates it at every later gate without process-environment dependence, proves its committed diff excludes all five prototype files, and creates `C:\dev\worktrees\gather-discord-redacted` from that tip; no execution step modifies the protected dirty files in `C:\dev\public\gather`.
- **Live boundary:** All implementation and CI tests are fixture-only; the external gate requires a new operator confirmation before the first capture.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-10-redacted-official-discord-bot.md`. Two execution options:

1. **Subagent-Driven (recommended)** — dispatch a fresh subagent per task and perform specification and code-quality review between commits.
2. **Inline Execution** — use `superpowers:executing-plans` in the isolated worktree and execute in reviewed batches.

The recorded preference for parallel agents makes Subagent-Driven the default once implementation begins.
