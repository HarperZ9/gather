# Privacy

This local profile reads only submitted paths under the workspace selected at
launch. Tool output is returned to the connected client and its chosen model.
No publisher service, telemetry endpoint, inference engine, or credential store
is used by this profile. Do not include confidential data in the selected
workspace unless that client and model are authorized to receive it.

## What it stores and sends

This profile stores nothing on disk. Network access is off unless the person who
installs the plugin names exact origins at launch: public HTTPS origins in the
allowed public origins setting, or literal loopback origins such as
`http://127.0.0.1:8080` in the local service setting. Then `gather.fetch` sends GET
requests to those origins only, without credentials, cookies, custom headers or
redirects. The URL path and query chosen by the model reach that origin. The
hostnames of granted origins are looked up through the system DNS resolver. No
other destination is contacted.

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

## Retention and support

Gather keeps no data after a call returns. Support and security reports:
https://github.com/HarperZ9/gather/issues
