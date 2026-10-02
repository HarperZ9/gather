# Gather local client

Gather reads documents in a folder you choose and returns each one with a digest receipt, so your assistant can cite exactly what it read.

## Try it

- Read notes.md in my workspace and give me its digest receipt.
- Read report.md, keep it only if it mentions latency, and give its source digest.
- Fetch https://example.com/changelog and give me the byte receipt. This needs that origin in the allowed public origins setting.

## Details

The profile exposes `gather.docs`, which reads one text file per call from the
workspace you select and returns catalog rows with digest receipts. When you allow
at least one origin, it also exposes `gather.fetch`, which sends one GET request to
an allowed origin and returns the text with a byte-hash receipt. A receipt proves
which bytes were read, not that the source is true.

The profile refuses other tools, path escapes, links, reparse points, network and
device paths, and tool-supplied permission grants. It does not read grants from
environment variables. Concurrent filesystem changes are outside this boundary,
and it is not an operating-system sandbox. Process-backed intake, arXiv search and
persistent-state operations stay on the full CLI and MCP server documented in
USAGE.md.

No model, API key, hosting account or publisher compute is included. Your client
and its model keep their own costs.

## Install

In Claude Code, enabling the plugin asks for three settings:

- **Readable workspace**: the directory Gather may read. Required.
- **Allowed public HTTPS origins**: a JSON array such as `["https://example.com"]`.
  Defaults to `[]`, which grants no public network access.
- **Allowed local service origins**: a JSON array such as `["http://127.0.0.1:8080"]`.
  Defaults to `[]`, which grants no local service access.

The Claude manifest passes these values as `${user_config.*}` launch arguments.
Blank or `[]` settings grant nothing, and a malformed setting stops launch. The
source plugin needs Python 3.11 or later on the `PATH` as `python3`.
The plugin folder carries its own copy of the server code in `server/src`, so it
runs without the rest of the repository. If that folder is missing, the server
stops with a message asking you to reinstall the plugin.

Portable and Codex manifests keep the placeholder `REPLACE_WITH_ABSOLUTE_WORKSPACE`.
Replace it with the absolute directory the client may read, and select your
installed Python executable. Keep the complete extracted bundle. No client
configuration is edited automatically.

The Windows x64 MCPB and ZIP include Python. Open the MCPB in a compatible desktop
client and choose a workspace and the same two optional origin settings, or run the
ZIP's server executable with `--workspace ABSOLUTE_DIRECTORY`. The Windows executable unpacks
its bundled runtime to a temporary folder while it runs.

## Network grants

Network access is off unless you name origins at launch. From the command line,
`--allow-origin https://example.com` grants one public HTTPS origin, and
`--allow-loopback-origin http://127.0.0.1:8080` grants one service on your own
computer. Repeat a flag for each origin. The JSON settings above become the flags
`--allow-origins-json` and `--allow-loopback-origins-json`.

Public grants must use HTTPS and resolve only to public addresses. Loopback grants
need a literal loopback IP and exact port. Requests connect only to the addresses
resolved at launch, refuse redirects and ignore system proxy settings. Responses
over 1,000,000 bytes fail without a complete receipt. Socket operations time out
after 10 seconds, and body reads have a 10-second budget checked between chunks.
Requests carry a Gather User-Agent and standard Accept headers, and never carry
credentials, cookies or custom headers. URL paths and queries chosen by the model
reach the allowed server, so grant only origins you trust to receive them.

## What this plugin runs and handles

**Hooks.** This plugin has no hooks.

**MCP server.** The plugin starts one MCP server named `gather`. Claude Code runs this command:

```text
python3 -I -S -B ${CLAUDE_PLUGIN_ROOT}/server/serve.py --workspace ${user_config.workspace} --allow-origins-json ${user_config.allowed_origins} --allow-loopback-origins-json ${user_config.loopback_origins}
```

- `-I -S -B` start Python in isolated mode. Python then ignores its own `PYTHON*` environment variables and your user packages, skips the site module, and writes no bytecode files.
- `${CLAUDE_PLUGIN_ROOT}` is the folder where Claude Code installed the plugin.
- `${user_config.workspace}` is the folder you chose as the readable workspace. The server reads files only inside it.
- `${user_config.allowed_origins}` is your list of public HTTPS origins. The default `[]` allows none.
- `${user_config.loopback_origins}` is your list of services on your own computer, such as `http://127.0.0.1:8080`. The default `[]` allows none.

The server offers `gather.docs`, which reads one text file in the workspace per call. If you allow at least one origin, it also offers `gather.fetch`, which reads one web address on an allowed origin per call. The server cannot start other programs.

**Network.** With both origin lists empty, the server makes no network connection. It blocks every socket. When you allow origins:

- At launch, the server looks up each allowed host name through your computer's DNS resolver. It looks the name up again for each request.
- Each `gather.fetch` call sends one GET request to an allowed origin. The server connects only to the addresses it found at launch.
- The request carries the path and query that the model chooses.
- The request carries these headers: `User-Agent: gather/<version> (+https://github.com/HarperZ9/gather)`, `Accept`, `Accept-Language: en-US,en;q=0.9`, `Accept-Encoding: identity`, `Host` and `Connection: close`.
- The request carries no cookies, passwords, tokens or other headers. The server does not follow redirects and ignores proxy settings.
- Public origins must use HTTPS and must resolve only to public addresses. A local service origin must be a loopback IP address with a port.

The server contacts no other destination.

**Files written.** The server writes no files or folders. It keeps no cache and no log. It sends its answers to Claude Code on standard output, and startup errors go to standard error. Nothing stays after a call returns.

**Environment variables and credentials.** Gather's own code reads no environment variables and no credentials when this plugin runs. Python's standard library reads these:

- `COLUMNS` and `LINES`: the argument parser uses them to set the width of help and error text.
- `LANG`, `LANGUAGE`, `LC_ALL` and `LC_MESSAGES`: the argument parser uses them to choose the language of its messages.
- `SSLKEYLOGFILE`: Python checks it each time `gather.fetch` prepares a request. Isolated mode makes Python ignore it, so no TLS key log is written.
- `SSL_CERT_FILE` and `SSL_CERT_DIR`: the TLS library can use them to find trusted certificates for HTTPS requests.

Some modules the server loads also contain code that reads `GATHER_ALLOW_EXEC`, `GATHER_ALLOW_NETWORK`, `GATHER_AUTH_ENV_ALLOW`, `GATHER_CHILD_ENV` and `SystemRoot`. That code serves the full Gather server and child programs. This plugin never runs it, so these variables grant nothing here.

## Data and network

| Question | Answer |
| --- | --- |
| What it reads | Text files under the workspace you select, one file of up to 8,000,000 bytes per call. With a grant, GET responses from the origins you name |
| What it stores | Nothing. The source server writes no files, cache or bytecode |
| Network calls | None by default. With a grant: DNS lookups for each granted host through your system resolver at launch and per request, and HTTP(S) GET requests to the exact origins you list in **Allowed public HTTPS origins** or **Allowed local service origins**. No other destination is reachable |
| Telemetry | None |
| Retention | Nothing is kept after a call returns |

Tool output goes to the connected client, and that client's model provider handles
it under its own privacy policy. See [PRIVACY.md](PRIVACY.md).

## Limits

The launcher denies Python process operations and denies sockets outside explicit
launch grants. These controls are defense in depth for this bundled standard-library
tool surface, not an operating-system sandbox. Do not infer a grant from a request,
a document or a plugin installation. macOS and Linux native bundles and
installed-client compatibility remain unverified.
