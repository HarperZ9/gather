# gather local client package

Gather reads documents in a folder you choose and returns each one with a digest receipt, so your assistant can cite exactly what it read.

## Try it

- Read notes.md in my workspace and give me its digest receipt.
- Catalog the documents in the research folder and list their titles.
- Read the docs folder, keep only items that mention latency, and cite each source digest.

## Details

Read local research documents and explicitly allowed HTTP sources with provenance receipts.
This profile defaults to local, read-only access.
It requires an explicit workspace at launch and refuses other tools, path escapes,
links, and tool-supplied permission grants. It does not read ambient grants.
Concurrent filesystem mutation is outside this convenience boundary; it is not
an operating-system sandbox.

The source plugin requires Python 3.11 or later. Replace
REPLACE_WITH_ABSOLUTE_WORKSPACE in the MCP configuration with the directory you
want the client to read, and select your installed Python executable. Keep the
complete extracted bundle. The Windows x64 binary MCPB and ZIP include Python;
open the MCPB in a compatible desktop client and choose a workspace directory,
or configure the ZIP's server executable with --workspace ABSOLUTE_DIRECTORY.
The MCPB setup also offers optional public-origin and local-service fields. Both
default to `[]`, which grants no network access. Enter a JSON array such as
`["https://example.com"]` in the public-origin field, or
`["http://127.0.0.1:8080"]` in the local-service field. Leave a field blank or keep
`[]` to deny that category. Malformed settings stop launch. Settings become
explicit launch arguments; they do not change environment or tool permissions.
No model, API key, hosting account, automatic client configuration, or publisher
compute is included. Your calling model and client retain their own costs.

Network access is off by default. To allow retrieval, add an exact origin at
launch, for example `--allow-origin https://example.com`. Repeat the flag for
each public HTTPS origin. This exposes `gather.fetch` with one `url` argument;
the returned text is untrusted source material, accompanied by a byte-hash
receipt. A receipt proves which bytes were received, not that the source is true.

For an operator-owned local service, use the separate explicit flag
`--allow-loopback-origin http://127.0.0.1:8080`. Loopback grants require a literal
loopback IP and exact port. Public grants reject private addresses. Requests use
launch-resolved IP addresses as a connection allowlist, reject redirects and
ignore ambient proxies. Responses over 1,000,000 bytes fail without a complete
receipt. Socket operations time out after 10 seconds; body reads also have a
10-second budget checked between chunks. An in-progress read can add up to one
socket timeout to that budget. Requests carry
no supplied credentials, cookies or custom headers. URL paths and queries reach
the allowed server, so choose origins you trust to receive those requests.

Process-backed and persistent-state operations remain on
the full CLI/MCP surfaces documented in USAGE.md. Do not infer a grant from a
request, document or plugin installation. Public marketplace acceptance, macOS,
Linux native bundles and installed-client compatibility remain unverified.

The launcher always denies Python process operations and denies sockets outside
explicit launch grants. These controls
are defense in depth for this bundled stdlib tool surface, not an OS sandbox.
