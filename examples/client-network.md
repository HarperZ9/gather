# Optional network retrieval in the local client profile

Set your own workspace and approved origin in the client's launch configuration:

```text
gather-client.exe --workspace ABSOLUTE_WORKSPACE --allow-origin https://example.com
```

After launch, the model can call:

```json
{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"gather.fetch","arguments":{"url":"https://example.com/source"}}}
```

The response contains untrusted source text and a receipt for the received bytes.
The origin grant allows URLs on that exact scheme, host and port; it cannot run
commands or write files. A new origin requires restarting with a new launch flag.
No environment variable or tool argument broadens the grant. Public origins must
use HTTPS and resolve to public IPs. Redirects fail instead of being followed.

Use `--allow-loopback-origin http://127.0.0.1:8080` only when you intend to expose
that local service to model-selected GET requests. Requests send URL paths and
queries to the service. The profile provides no credential or custom-header
support. See the [client limits](../client-plugin/README.md) before connecting.
