# gather local client package

Read local research documents and return provenance receipts. This read-only profile is an unpublished development candidate.
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
No model, API key, hosting account, automatic client configuration, or publisher
compute is included. Your calling model and client retain their own costs.

This profile does not yet qualify the full product's mature workflow. Network
retrieval, process-backed benchmarks and persistent-state operations remain on
the full CLI/MCP surfaces documented in USAGE.md. Do not infer a grant from a
request, document or plugin installation. Public marketplace acceptance, macOS,
Linux native bundles and installed-client compatibility remain unverified.

The local launcher denies Python process and socket operations. Index map reports
Git metadata as unavailable because this profile cannot launch Git. These controls
are defense in depth for this bundled stdlib tool surface, not an OS sandbox.
