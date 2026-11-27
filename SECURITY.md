# Security Policy

## Supported versions

`gather-engine` is distributed on PyPI and packaged as a local research collection CLI and stdio MCP
server. Security fixes ship in the current release line as a new release. Older lines do not receive
backports.

| Version | Supported |
|-|-|
| 2.6.x | Yes |
| < 2.6 | No |

## Reporting a vulnerability

Report suspected vulnerabilities privately through GitHub: open this repository's **Security** tab
and select **Report a vulnerability**, or open
<https://github.com/HarperZ9/gather/security/advisories/new>.
Keep security reports out of public issues, pull requests, and discussions.

Include:

- the affected version and operating system,
- a concise description of the issue and its impact,
- the minimal input or steps needed to reproduce it.

The maintainer, Zain Dana Harper, acknowledges reports and works on a fix before public disclosure.
Allow a reasonable period to remediate before disclosing.

## Scope and trust model

Gather collects and deconstructs research material (web pages, papers, APIs, PDFs, audio, and video)
into a local corpus with source hashes.

- **Explicit network edges.** Gather fetches remote URLs only when you invoke collection commands on
  those targets. Fetched documents, HTML, PDFs, and media payloads are untrusted external input and
  are stored as data inside the configured corpus directory.
- **Local storage and provenance.** Collected artifacts and source hashes live on local storage that
  you control. Gather emits zero telemetry.
- **MCP surface.** The MCP server communicates over stdio JSON-RPC, opens no network listener, and
  operates within the configured corpus directory. Tool outputs flow to the connected MCP client.
- **What counts as a vulnerability.** Arbitrary code or command execution triggered by malicious web
  content, PDF, media, or API responses; path traversal writing outside the configured corpus root;
  SSRF bypassing documented host or scheme restrictions; or hash provenance verification accepting
  tampered corpus entries.
- **What does not count.** Upstream remote sites returning HTTP errors or malformed content that
  Gather rejects cleanly.

## Good practice

- Keep optional API credentials in environment variables, never in corpus files or source lists.
- Run collection jobs against untrusted remote URLs or media files with least-privilege accounts or
  in a sandboxed environment.
