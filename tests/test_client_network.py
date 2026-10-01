"""Real HTTP fixtures test launch authority without external network calls."""
import hashlib
import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest


@pytest.fixture
def endpoint():
    hits = []
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            hits.append(self.path)
            if self.path == "/redirect":
                self.send_response(302)
                self.send_header("Location", "/secret")
                self.end_headers()
                return
            self.send_response(200)
            if self.path == "/short":
                self.send_header("Content-Length", "100")
                self.end_headers()
                self.wfile.write(b"short")
                return
            self.end_headers()
            self.wfile.write(b"x" * 1_000_001 if self.path == "/large" else b"Synthetic evidence: 14 records.")
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}", hits
    server.shutdown()
    server.server_close()
    thread.join()


def launch(tmp_path, requests, flags=()):
    launcher = Path(__file__).resolve().parents[1] / "client-plugin/server/serve.py"
    return subprocess.run([sys.executable, "-I", "-S", "-B", str(launcher),
        "--workspace", str(tmp_path), *flags], input="".join(json.dumps(r)+"\n" for r in requests),
        env={**os.environ, "GATHER_ALLOW_NETWORK": "all", "HTTP_PROXY": "http://127.0.0.1:1"},
        capture_output=True, text=True, timeout=20)


def call(url, **extra):
    return {"id": 1, "method": "tools/call", "params": {"name": "gather.fetch",
        "arguments": {"url": url, **extra}}}


def test_explicit_launch_fetch_returns_real_body_and_receipt(tmp_path, endpoint):
    origin, hits = endpoint
    result = launch(tmp_path, [call(origin+"/source")], ["--allow-loopback-origin", origin])
    assert result.returncode == 0, result.stderr
    response = json.loads(result.stdout)["result"]
    assert not response["isError"], response
    data = json.loads(response["content"][0]["text"])
    assert data["text"] == "Synthetic evidence: 14 records."
    assert data["receipt"]["content_sha256"] == hashlib.sha256(data["text"].encode()).hexdigest()
    assert data["receipt"]["status"] == 200
    assert hits == ["/source"]


def test_default_environment_cannot_grant_network(tmp_path, endpoint):
    origin, hits = endpoint
    result = launch(tmp_path, [call(origin)])
    assert json.loads(result.stdout)["result"]["isError"]
    assert hits == []


def test_redirect_and_tool_grants_do_not_extend_launch_scope(tmp_path, endpoint):
    origin, hits = endpoint
    result = launch(tmp_path, [call(origin+"/redirect"), call(origin, allow_network=True),
        call("http://127.0.0.1:1/outside")], ["--allow-loopback-origin", origin])
    assert result.returncode == 0, result.stderr
    assert all(row["result"]["isError"] for row in map(json.loads, result.stdout.splitlines()))
    assert hits == ["/redirect"]


@pytest.mark.parametrize("origin", ["http://127.0.0.1:80", "https://user:pass@example.com", "https://example.com/path", "https://example.com?x=1"])
def test_public_launch_refuses_nonpublic_or_nonorigin(tmp_path, origin):
    result = launch(tmp_path, [], ["--allow-origin", origin])
    assert result.returncode != 0


def test_large_response_is_not_receipted_as_complete(tmp_path, endpoint):
    origin, hits = endpoint
    result = launch(tmp_path, [call(origin+"/large")], ["--allow-loopback-origin", origin])
    assert result.returncode == 0, result.stderr
    response = json.loads(result.stdout)["result"]
    assert response["isError"]
    assert "no complete receipt" in response["content"][0]["text"]
    assert hits == ["/large"]


def test_premature_eof_is_not_receipted_as_complete(tmp_path, endpoint):
    origin, hits = endpoint
    result = launch(tmp_path, [call(origin+"/short")], ["--allow-loopback-origin", origin])
    assert result.returncode == 0, result.stderr
    response = json.loads(result.stdout)["result"]
    assert response["isError"]
    assert "incomplete response" in response["content"][0]["text"]
    assert hits == ["/short"]


def test_opt_in_keeps_process_and_outside_socket_denial(tmp_path, endpoint):
    origin, hits = endpoint
    source = Path(__file__).resolve().parents[1] / "src"
    script = """
import sys, socket, subprocess
sys.path.insert(0, sys.argv[1])
from gather.client_network import NetworkGrant
from gather.client_mcp import install_process_boundary
grant = NetworkGrant.from_launch(loopback=[sys.argv[2]])
install_process_boundary(grant)
for operation in [lambda: socket.create_connection(('127.0.0.1', 1)),
                  lambda: subprocess.run([sys.executable, '-c', 'pass'])]:
    try:
        operation()
    except PermissionError:
        print('DENIED')
    else:
        raise AssertionError('boundary widened')
"""
    result = subprocess.run([sys.executable, "-I", "-S", "-c", script, str(source), origin],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["DENIED", "DENIED"]
    assert hits == []


def test_pinned_socket_blocks_rebound_address():
    from gather.client_network import NetworkGrant
    grant = NetworkGrant(frozenset({("https", "example.com", 443)}), frozenset({("8.8.8.8", 443)}))
    grant.audit_socket("socket.connect", (None, ("8.8.8.8", 443)))
    with pytest.raises(PermissionError):
        grant.audit_socket("socket.connect", (None, ("127.0.0.1", 443)))


def test_continuing_response_cannot_extend_read_budget(endpoint, monkeypatch):
    from gather import client_network
    origin, _ = endpoint
    grant = client_network.NetworkGrant.from_launch(loopback=[origin])
    ticks = iter([0.0, 11.0])
    monkeypatch.setattr(client_network, "monotonic", lambda: next(ticks), raising=False)
    with pytest.raises(ValueError, match="time budget"):
        grant.get(origin)
