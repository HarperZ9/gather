# Gather SaaS Master Design

**Status:** Architecture approved; written specification pending operator review
**Date:** 2026-07-30
**Owner:** Zentropy Labs
**Product:** Gather

## 1. Decision

Gather will become a complete multi-tenant research-operations SaaS while
retaining its existing CLI, MCP, and Python engine.

The SaaS turns difficult mixed sources into continuously monitored,
operator-controlled, portable, verifiable research corpora. It supports broad
research work across venture and market diligence, technical and scientific
research, media intelligence, engineering operations, and regulated review.

The product is not local-only. It supports:

- Zentropy-managed hosted operation;
- customer-controlled cloud or on-premises deployment;
- workstation and offline execution;
- remotely shared redacted reports;
- full evidence export and independent offline verification.

Billing is implemented as a complete integration but remains disabled by
default until the operator approves pricing and activation.

Gather remains a retained Zentropy Labs capability. Pilot, subscription,
services, partnership, advisory, and co-build arrangements do not imply a sale,
assignment, acquisition option, exclusivity, source transfer, or ownership of
general product improvements.

## 2. Product Outcome

A customer can create an organization, invite collaborators, create research
workspaces, define controlled source policies, gather mixed material, monitor
changes, inspect provenance, search the corpus, review grounded findings,
publish revocable reports, and export evidence that verifies without access to
the SaaS.

The product must answer:

> What did we gather, how did each item arrive, what changed, what can be
> independently re-checked, what could not be verified, and which findings
> remain grounded in captured evidence?

The product does not claim that a captured source is true. It proves what was
captured, how it was handled, how derived material relates to its inputs, and
whether the resulting evidence artifacts remain intact.

## 3. Approaches Considered

### 3.1 Managed frontend and backend platform

A Next.js or managed database platform could produce a hosted interface
quickly. It would divide the Python evidence engine from its control plane and
make custody, background execution, and independent deployment depend heavily
on one provider.

### 3.2 Modular SaaS

The selected architecture uses a React web application, FastAPI control plane,
PostgreSQL, S3-compatible object storage, and isolated Python workers that
compose the existing Gather engine.

This is one deployable system with strong internal module boundaries. It avoids
early microservices while preserving seams that can split later when measured
load justifies it.

### 3.3 Independent microservices

Separate services for identity, intake, monitoring, reports, billing, and
search would increase operational surface before customer evidence establishes
the need. It is not selected for the first SaaS release.

## 4. System Architecture

```text
Browser
  |
  v
React web application
  |
  v
FastAPI control plane
  |-- OIDC token validation
  |-- organization and workspace authorization
  |-- manifest and source policy validation
  |-- report and share-link delivery
  |-- billing and administration
  |
  +--> PostgreSQL
  |      organizations, users, memberships, workspaces, sources,
  |      schedules, jobs, runs, outcomes, reports, shares,
  |      subscriptions, audit events
  |
  +--> S3-compatible object storage
  |      content-addressed source objects, corpus artifacts,
  |      reports, bundles, private uploads
  |
  +--> PostgreSQL job queue
          |
          v
       Gather workers
          |-- existing Gather adapters and evidence engine
          |-- source allowlists and network policy
          |-- secret decryption only for the active job
          |-- report, monitoring, and receipt generation
```

The scheduler is a separate process using the same application package and
database. It enqueues due monitoring runs. The API never executes a network
source adapter in the request process.

## 5. Repository Structure

Gather remains one repository:

```text
src/
  gather/                    existing zero-dependency engine
  gather_saas/
    api/                     FastAPI routes and request contracts
    auth/                    OIDC identity and authorization
    tenancy/                 organization and workspace isolation
    db/                      SQLAlchemy models, sessions, and RLS context
    jobs/                    queue, leasing, scheduler, and worker entrypoints
    storage/                 S3-compatible evidence storage
    secrets/                 encrypted source-credential vault
    pilots/                  SaaS adapter for the pilot evidence engine
    reports/                 report access, sharing, and export
    billing/                 feature-flagged Stripe integration
    audit/                   append-only administrative audit records
web/
  src/
    app/                     routing and authenticated application shell
    auth/                    OIDC PKCE client
    organizations/           organization and membership screens
    workspaces/              source policy and workspace screens
    runs/                    live and historical run views
    corpus/                  search and evidence inspection
    changes/                 monitoring comparison
    reports/                 report builder and shared report view
    settings/                security, retention, billing, and API access
deploy/
  compose/                   reproducible local and customer-hosted stack
  containers/                API, worker, scheduler, and web images
  migrations/                Alembic migrations
  runbooks/                  deployment, backup, restore, incident response
```

The existing `gather` package retains zero required runtime dependencies. SaaS
dependencies live behind `gather-engine[saas]`, and web dependencies live under
`web/package.json`.

## 6. Technology

### 6.1 Backend

- Python 3.11 or newer;
- FastAPI and Uvicorn;
- Pydantic v2 request and response contracts;
- SQLAlchemy 2 and Alembic;
- PostgreSQL 16 or newer;
- psycopg 3;
- boto3-compatible S3 client;
- PyJWT with cryptographic extras for OIDC token validation;
- Stripe Python SDK behind a billing feature flag.

### 6.2 Frontend

- React 19;
- TypeScript 6;
- Vite 8;
- React Router;
- TanStack Query;
- native EventSource for server-sent run events;
- the Project Telos public design and voice canon.

### 6.3 Development and deployment

- Docker and Docker Compose;
- MinIO for local S3-compatible storage;
- PostgreSQL for application state and the job queue;
- provider-neutral OIDC configuration;
- production containers that can run on a customer-controlled platform or an
  approved Zentropy-managed host.

No production deployment occurs without an explicit operator instruction to
deploy.

## 7. Identity and Tenancy

### 7.1 Identity

The web application uses OIDC Authorization Code with PKCE. The browser holds
short-lived access tokens in memory. Refresh behavior uses the provider's
approved secure mechanism and never writes bearer tokens to local storage.

The API validates:

- signature against cached issuer JWKS;
- issuer;
- audience;
- expiration and not-before;
- subject.

A user identity is keyed by `(issuer, subject)`. Email is profile metadata, not
the authorization key.

### 7.2 Organizations

Every billable and security boundary is an organization. A user reaches
organization data only through an active membership.

Roles are closed:

- `owner`: billing, deletion, security, membership, and all workspace access;
- `admin`: membership and workspace administration, not ownership transfer or
  billing-account deletion;
- `operator`: source configuration, runs, reports, and corpus use;
- `viewer`: read-only workspace, corpus, and report access.

Invitations contain a random token. Only its hash is stored. Invitations have
an organization, role, creator, recipient email, expiration, single-use
timestamp, and revocation timestamp.

### 7.3 Database isolation

Every tenant-owned table includes `organization_id`.

Each authenticated transaction executes:

```sql
SET LOCAL app.user_id = '<authenticated user uuid>';
SET LOCAL app.organization_id = '<authorized organization uuid>';
```

PostgreSQL row-level security policies require
`organization_id = current_setting('app.organization_id')::uuid`.

The application also includes organization predicates in repository methods.
Application filtering is defense in depth; RLS is authoritative.

System migrations, health probes, and the scheduler use distinct database roles.
The normal API and worker roles cannot bypass RLS.

Two narrowly scoped `SECURITY DEFINER` database functions cross the tenant
index without returning tenant evidence:

- `claim_due_job(worker_id)` atomically leases one eligible job and returns
  only job ID and organization ID;
- `list_due_schedules(cutoff)` returns only schedule ID and organization ID.

After either function returns, the worker or scheduler opens an
organization-scoped transaction and sets `app.organization_id` before reading
the job, schedule, workspace, source, or evidence rows. The function owner is a
non-login migration role. Function bodies pin `search_path`, expose no dynamic
SQL, and receive dedicated privilege tests.

Organization listing uses `app.user_id` and a membership policy. All other
tenant-owned access requires both active membership and the active
`app.organization_id`.

## 8. Domain Model

All primary identifiers are UUIDs. Timestamps are UTC.

| Table | Purpose and load-bearing fields |
|---|---|
| `users` | OIDC issuer, subject, profile metadata, status |
| `organizations` | name, slug, lifecycle status, retention policy |
| `memberships` | organization, user, role, state |
| `invitations` | organization, role, token hash, expiry, use and revocation |
| `workspaces` | organization, name, purpose, visibility, state |
| `missions` | workspace, slug, title, ordered position |
| `source_policies` | workspace, allowed hosts, trusted browser hosts, adapter allowlist, version, digest |
| `sources` | workspace, mission, adapter, target reference, visibility, required flag, monitoring schedule |
| `source_credentials` | organization, source or workspace scope, encrypted payload, key metadata, rotation state |
| `jobs` | organization, workspace, kind, state, priority, lease, attempts, idempotency key |
| `runs` | workspace, manifest digest, trigger, state, timestamps, receipt digest |
| `source_outcomes` | run, source, typed status, counts, diagnostics, receipt refs |
| `corpus_items` | workspace, content digest, kind, method, source ref, object key, visibility |
| `monitor_observations` | source, run, verdict, old digest, new digest, ledger hash |
| `extraction_outcomes` | run, source, field bindings, verification verdict |
| `reports` | workspace, run, visibility, object key, semantic digest, state |
| `report_shares` | report, token hash, expiry, revocation, access count |
| `exports` | workspace, visibility, object key, receipt digest, state |
| `subscriptions` | organization, provider IDs, plan, status, period |
| `billing_events` | provider event ID, type, processing state, payload digest |
| `audit_events` | organization, actor, action, target, timestamp, request and result digests |

Plain source credential values never enter PostgreSQL outside encrypted
ciphertext.

## 9. API Contract

The versioned API root is `/api/v1`.

### 9.1 Identity and organizations

```text
GET    /me
GET    /organizations
POST   /organizations
GET    /organizations/{organization_id}
PATCH  /organizations/{organization_id}
GET    /organizations/{organization_id}/members
POST   /organizations/{organization_id}/invitations
DELETE /organizations/{organization_id}/invitations/{invitation_id}
POST   /invitations/{token}/accept
PATCH  /organizations/{organization_id}/members/{membership_id}
DELETE /organizations/{organization_id}/members/{membership_id}
```

### 9.2 Workspaces and sources

```text
GET    /organizations/{organization_id}/workspaces
POST   /organizations/{organization_id}/workspaces
GET    /workspaces/{workspace_id}
PATCH  /workspaces/{workspace_id}
DELETE /workspaces/{workspace_id}
GET    /workspaces/{workspace_id}/missions
POST   /workspaces/{workspace_id}/missions
GET    /workspaces/{workspace_id}/sources
POST   /workspaces/{workspace_id}/sources
PATCH  /sources/{source_id}
DELETE /sources/{source_id}
PUT    /workspaces/{workspace_id}/source-policy
POST   /workspaces/{workspace_id}/credentials
DELETE /credentials/{credential_id}
```

### 9.3 Runs, evidence, and reports

```text
POST   /workspaces/{workspace_id}/runs
GET    /workspaces/{workspace_id}/runs
GET    /runs/{run_id}
POST   /runs/{run_id}/cancel
GET    /runs/{run_id}/events
GET    /workspaces/{workspace_id}/corpus
GET    /corpus/items/{item_id}
GET    /workspaces/{workspace_id}/changes
POST   /workspaces/{workspace_id}/reports
GET    /reports/{report_id}
POST   /reports/{report_id}/shares
DELETE /report-shares/{share_id}
POST   /workspaces/{workspace_id}/exports
GET    /exports/{export_id}
GET    /public/reports/{share_token}
```

### 9.4 Billing and administration

```text
GET    /organizations/{organization_id}/billing
POST   /organizations/{organization_id}/billing/checkout
POST   /organizations/{organization_id}/billing/portal
POST   /billing/webhooks/stripe
GET    /organizations/{organization_id}/audit-events
```

Run creation requires an `Idempotency-Key` header. Reusing a key with the same
request returns the existing run. Reusing it with a different request returns
HTTP 409.

Collection endpoints use opaque cursor pagination. API responses never expose
storage keys, encrypted secret fields, absolute filesystem paths, or raw
billing webhook payloads.

## 10. Jobs, Workers, and Scheduling

Job states are closed:

```text
queued -> leased -> running -> succeeded
                           -> partial
                           -> failed
                           -> cancelled
```

Workers lease jobs with `SELECT ... FOR UPDATE SKIP LOCKED`. A lease has an
owner ID and expiration. Workers renew leases while running. An expired lease
returns to `queued` only when attempts remain.

Jobs carry:

- organization and workspace;
- immutable run ID;
- kind;
- priority;
- attempt and maximum attempts;
- idempotency key;
- lease owner and expiry;
- bounded error code and diagnostic;
- created, started, heartbeat, and completed timestamps.

The scheduler queries enabled sources whose next run is due and creates one
idempotent monitoring run per workspace and schedule instant.

Cancellation is cooperative. A running adapter receives a cancellation token.
Completed evidence is preserved in a partial receipt. Cancellation never
deletes evidence already written.

The worker:

1. authorizes the job against the snapshotted organization and workspace;
2. loads the immutable source policy and manifest;
3. resolves only the credential refs required by the active source;
4. executes source adapters in an isolated working directory;
5. writes content-addressed objects;
6. commits database metadata only after object hashes verify;
7. emits typed progress events;
8. writes the run and pilot receipts;
9. clears secret material and temporary files.

## 11. Source and Network Safety

The source policy contains exact allowed host names, exact trusted browser
hosts, enabled adapters, maximum response bytes, maximum source count, and
retention classification.

Static HTTP and API adapters:

- permit HTTP and HTTPS only;
- resolve and reject private, loopback, link-local, multicast, and metadata
  addresses;
- repeat validation on every redirect;
- strip authorization and cookies on cross-origin redirects;
- reject caller-supplied routing headers;
- cap redirects, response bytes, and duration.

Browser adapters:

- are disabled unless the host is in `trusted_browser_hosts`;
- run in a separate worker container;
- run as a non-root user with the browser sandbox enabled;
- deny private-network egress at the container or platform network layer;
- cap execution time, downloads, and output size;
- retain the limitation that arbitrary hostile browser content is not proven
  safe.

Uploaded files:

- receive an upload size limit and content digest;
- are stored under a quarantine prefix before processing;
- are never executed;
- are parsed by adapter-specific workers;
- retain original and derived object digests.

## 12. Credential Vault

Source credentials use envelope encryption.

Each secret receives a random AES-256-GCM data key. The ciphertext stores:

- algorithm and version;
- nonce;
- encrypted secret;
- encrypted data key;
- root-key provider and key ID;
- creation and rotation timestamps.

Root-key providers are an interface:

- `DevelopmentKeyProvider` reads a dedicated development key and refuses
  production mode;
- `AwsKmsKeyProvider` supports the first Zentropy-managed production target;
- customer-hosted deployments may supply another provider through the same
  interface.

Only workers can request decryption. The API can create, rotate, list metadata,
and delete credentials but can never read plaintext back.

Secret values are redacted from exceptions, structured logs, audit payloads,
reports, run events, and receipts.

## 13. Evidence Storage

PostgreSQL stores metadata and authorization. S3-compatible storage holds
evidence bytes.

Object keys are:

```text
organizations/{organization_id}/objects/{sha256-prefix}/{sha256}
```

The digest remains the content identity. The organization prefix prevents
cross-tenant key disclosure and permits separate lifecycle policies.

Writes use:

1. upload to a temporary organization-scoped key;
2. re-read or validate provider checksum;
3. compare SHA-256;
4. promote to the content-addressed key;
5. commit database metadata.

Downloads require an authorized API request. The API returns short-lived signed
URLs only for a specific object and disposition.

Private evidence is encrypted at rest by the deployment's object-store
controls. Gather records the configured custody and encryption mode but does not
claim the provider implemented them correctly without an independent check.

## 14. Reports, Sharing, and Export

Reports are generated from immutable run and corpus references.

Report visibility is:

- `private`: organization members with workspace permission;
- `shared`: redacted, token-addressed remote report;
- `public`: explicitly published redacted report.

A share token is random and stored only as a hash. Shares have expiry and
revocation timestamps. The public endpoint uses a restrictive content security
policy and does not load third-party analytics.

The report includes:

- mission and source outcomes;
- capability matrix;
- item, kind, method, and visibility counts;
- corpus digest and verification verdict;
- monitoring changes and ledger root;
- grounded extraction evidence;
- limitations and `does_not_prove`;
- semantic report digest.

Private source bodies, local paths, credentials, request headers, and private
source refs are excluded from shared and public reports.

Exports are deterministic ZIP bundles:

- `shared` includes redacted reports and public verification evidence;
- `full` includes corpus and private evidence and requires an owner or admin
  confirmation;
- every member has a relative path and digest in `bundle-receipt.json`;
- the completed bundle verifies offline with the Gather CLI.

## 15. Billing

Billing is guarded by:

```text
GATHER_BILLING_ENABLED=false
```

When disabled:

- no checkout or billing portal is exposed;
- webhook requests return disabled without changing organization access;
- an owner or system administrator provisions pilot organizations;
- the UI labels the workspace as a pilot, not a free subscription.

When enabled:

- organization owners can start Stripe Checkout;
- owners can open the Stripe customer portal;
- signed webhooks update subscription state;
- provider event IDs enforce idempotency;
- raw webhook payloads are not placed in application logs;
- plan entitlements are enforced server-side.

The initial entitlement model supports limits for workspaces, members, sources,
monthly runs, object bytes, and browser-worker minutes. No price or entitlement
number is published until separately approved.

## 16. Web Application

The authenticated application routes are:

```text
/app
/app/organizations/:organizationId
/app/organizations/:organizationId/members
/app/workspaces/:workspaceId
/app/workspaces/:workspaceId/sources
/app/workspaces/:workspaceId/runs
/app/workspaces/:workspaceId/runs/:runId
/app/workspaces/:workspaceId/corpus
/app/workspaces/:workspaceId/changes
/app/workspaces/:workspaceId/reports
/app/workspaces/:workspaceId/settings
/app/settings/billing
```

Public routes are:

```text
/
/product
/security
/pilot
/reports/:shareToken
```

The workspace experience centers on:

- current evidence status;
- source availability and failure state;
- new and changed material;
- exact evidence behind a finding;
- monitor schedule and next run;
- report and export actions.

The interface never presents an estimate as a captured observation. It uses
verdict color only for typed outcomes. Missing or unavailable evidence remains
visible.

The visual system derives from the Project Telos design and voice canon. It
does not copy the current portfolio page structure into the product
application.

## 17. Audit and Observability

Audit events cover:

- organization and membership changes;
- source-policy changes;
- credential creation, rotation, and deletion;
- run creation and cancellation;
- report sharing and revocation;
- export creation;
- billing state changes;
- retention and deletion actions.

Audit events contain actor, action, target, timestamp, request digest, result
digest, and outcome. They do not contain secret values or evidence bodies.

Operational telemetry includes:

- API latency and error rate;
- queued and leased jobs;
- job age, attempts, and lease recovery;
- adapter success and typed failure counts;
- bytes stored and transferred;
- monitoring freshness;
- report and export generation time;
- OIDC and billing webhook failures.

Logs are structured and carry request, organization, workspace, run, and job
correlation IDs. Public share requests omit organization names and source refs.

## 18. Retention, Deletion, Backup, and Recovery

An organization defines a retention period. The system distinguishes:

- active evidence;
- expired evidence awaiting deletion;
- legal or operator hold;
- deleted metadata tombstone.

Deletion is asynchronous and receipted. It deletes database metadata and
organization-scoped objects according to policy, then records counts and
failures. A failed object deletion remains retryable and visible.

Backup requirements:

- PostgreSQL backup;
- object-storage versioning or equivalent backup;
- configuration and migration version;
- root-key recovery procedure stored outside the application database.

The pilot must exercise restore into a separate environment and verify a
restored corpus and report.

## 19. Deployment

### 19.1 Development

Docker Compose starts:

- PostgreSQL;
- MinIO;
- API;
- worker;
- scheduler;
- web application;
- a development OIDC adapter that refuses non-development mode.

### 19.2 Customer-hosted

The same images support:

- customer PostgreSQL;
- customer S3-compatible storage;
- customer OIDC issuer;
- customer root-key provider;
- customer ingress and TLS.

### 19.3 Zentropy-managed

The first managed environment requires:

- managed PostgreSQL;
- S3-compatible storage;
- production OIDC;
- KMS-backed credential keys;
- isolated worker networking;
- TLS;
- backups;
- monitoring and alerts;
- a staging environment separate from production.

Building deployment artifacts is authorized by this specification. Creating or
changing a production deployment requires a separate explicit operator
instruction.

## 20. Subprojects

The complete SaaS is delivered through four independently reviewable
subprojects.

### Subproject 1: Pilot evidence engine

Produces:

- pilot manifest validation;
- offline replay and live allowlisted execution;
- monitoring refresh;
- grounded extraction;
- reports and tamper-evident bundles;
- CLI and MCP parity;
- result and progress-event interfaces consumed by SaaS workers.

Specification:
`docs/superpowers/specs/2026-07-30-gather-pilot-engine-design.md`.

### Subproject 2: Multi-tenant control plane

Produces:

- database schema and migrations;
- OIDC identity;
- organizations, memberships, and RLS;
- source policy and encrypted credentials;
- job queue, scheduler, workers, and S3 storage;
- versioned API;
- audit and operational telemetry.

### Subproject 3: Customer web application

Produces:

- authenticated organization and workspace application;
- source, run, corpus, change, and report workflows;
- server-sent run events;
- remote report sharing and revocation;
- responsive, accessible production UI.

### Subproject 4: Commercial and operational release

Produces:

- feature-flagged Stripe integration;
- deterministic exports;
- Docker Compose and production container images;
- backup, restore, security, privacy, retention, support, and incident runbooks;
- hosted or customer-hosted pilot readiness;
- PSL-specific and reusable product pitch packages.

Each subproject receives its own implementation plan and verification gate.

## 21. Testing

### 21.1 Engine

- existing Gather suite remains green;
- offline execution opens no socket;
- source allowlists and redirect checks fail closed;
- partial runs preserve successful evidence;
- monitoring chains and reports verify;
- deliberate artifact tampering fails verification.

### 21.2 Tenancy and authorization

- every tenant-owned route denies a user from another organization;
- database RLS denies cross-tenant reads and writes even when application
  predicates are omitted in a negative test;
- role tests cover every route and administrative action;
- invitation reuse, expiration, and revocation fail;
- worker and scheduler roles cannot bypass RLS.

### 21.3 Jobs and storage

- idempotent run creation does not duplicate jobs;
- expired leases recover without duplicating completed evidence;
- cancellation preserves partial receipts;
- object digest mismatch prevents metadata commit;
- cross-organization object access fails;
- backup and restore preserve evidence verification.

### 21.4 Secrets and network safety

- credential plaintext never appears in API responses, logs, receipts, reports,
  audit events, or database metadata;
- production refuses the development key provider;
- cross-origin redirects strip credentials;
- private address redirects fail;
- browser workers cannot reach a private-network fixture;
- uploaded files are never executed.

### 21.5 Reports, sharing, and billing

- shared reports redact every private field;
- revoked and expired share tokens fail;
- public report CSP contains no third-party origin;
- full export requires explicit authorization;
- bundle tampering fails offline verification;
- disabled billing exposes no checkout action;
- webhook signatures and event idempotency are enforced;
- billing state never overrides organization authorization by itself.

### 21.6 Frontend

- keyboard navigation and accessible names cover primary workflows;
- organization switching clears prior organization query state;
- run progress reconnects safely;
- failure and unavailable states remain visible;
- no private payload enters browser analytics or error telemetry;
- production build and route smoke tests pass.

## 22. SaaS Pilot Acceptance

The SaaS pilot is complete only when:

1. Two independent organizations can use the system with proven data
   isolation.
2. A user can create a workspace, configure representative missions, run
   Gather, inspect evidence, refresh monitoring, generate a report, share it,
   revoke it, and export it without a terminal.
3. The representative offline showcase and a controlled live run both pass.
4. A worker restart recovers a leased job without duplicating completed
   evidence.
5. Corpus objects, run receipts, monitoring history, reports, and exports
   independently verify.
6. Shared reports and bundles contain no private evidence.
7. OIDC, role enforcement, RLS, credential encryption, source policy, browser
   isolation, and audit tests pass.
8. Billing passes in test mode and remains disabled in the pilot environment.
9. Backup and restore are exercised against a separate environment.
10. Docker Compose creates a complete reproducible stack.
11. A staging deployment or customer-hosted deployment candidate passes health,
    migration, smoke, and rollback checks.
12. Security, privacy, retention, backup, incident, support, and deployment
    documentation is complete.
13. The PSL and reusable partner packages demonstrate representative value and
    state that Gather remains a retained Zentropy Labs capability.

## 23. Pitch and Package

The product package leads with one outcome:

> Turn difficult mixed sources into a continuously monitored, operator-controlled,
> verifiable research corpus.

Representative value is shown through:

- venture validation and portfolio intelligence;
- technical and scientific discovery;
- media and operational monitoring;
- authenticated and private source intake;
- evidence-grounded structured findings;
- continuous change custody;
- independent verification after export.

The PSL package explains how Gather supports both studio validation and fund
diligence while remaining part of the broader Zentropy workbench.

The reusable package includes:

- product brief;
- architecture and security brief;
- representative capability matrix;
- live and offline demonstration;
- sample redacted report;
- pilot operating model;
- deployment choices;
- proposed commercial terms labeled as proposed;
- limitations and `does_not_prove`.

No package presents Gather as available for acquisition.

## 24. Non-Goals for the First SaaS Pilot

The first SaaS pilot does not:

- promise unrestricted hostile browser safety;
- claim truth or comprehensive coverage from captured sources;
- publish billing prices without approval;
- add mobile-native applications;
- implement enterprise SAML or SCIM before a design partner requires them;
- create independent microservices without measured scaling need;
- perform a production deployment without explicit approval;
- send outreach or bind a partner to terms without explicit authorization.

## 25. Does Not Prove

Completing the SaaS does not by itself prove:

- product-market fit;
- willingness to pay;
- legal sufficiency for every regulated retention regime;
- correctness of source claims, OCR, transcription, or external metadata;
- safety of arbitrary browser automation;
- security against vulnerabilities not exercised by the tests;
- that a host provider implemented its controls correctly;
- that PSL or another organization will partner, invest, advise, or purchase.

Those require customer use, independent security review, deployment evidence,
and commercial conversations.
