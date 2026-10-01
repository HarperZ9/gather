"""Qualify real native stdio in a synthetic workspace, without Python on PATH."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
from native_windows_process import run_process
SPEC = json.loads(Path(__file__).with_name("client-package.json").read_text())

EXPECTED_TOOLS = set(["gather.docs"])

def strict_json(text):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result
    def nonfinite(_):
        raise ValueError("nonfinite JSON number")
    return json.loads(text, object_pairs_hook=unique, parse_constant=nonfinite)

def payload_of(result):
    content = result.get("content")
    if not isinstance(content, list) or len(content) != 1 or content[0].get("type") != "text" or not isinstance(content[0].get("text"), str):
        raise ValueError("invalid native content shape")
    value = strict_json(content[0]["text"])
    if not isinstance(value, dict):
        raise ValueError("native tool payload must be an object")
    return value

def check(executable, version):
    executable = Path(executable).resolve(strict=True)
    before = hashlib.sha256(executable.read_bytes()).hexdigest()
    with tempfile.TemporaryDirectory(prefix=SPEC["name"]+"-native-") as folder:
        home = Path(folder)
        workspace = home/"workspace"
        workspace.mkdir()
        (workspace/"sample.md").write_text("A synthetic document contains 14 records.", encoding="utf-8")
        (workspace/"thesis.json").write_text(json.dumps({"title":"Synthetic",
            "claims":[{"text":"14 records exist","falsification":"a count other than 14"}]}),encoding="utf-8")
        (home/"outside.md").write_text("Outside the selected workspace.",encoding="utf-8")
        env = {k:v for k,v in os.environ.items() if k.upper() in {"SYSTEMROOT","WINDIR","SYSTEMDRIVE"}}
        env["PATH"] = str(Path(env.get("SYSTEMROOT","C:/Windows"))/"System32")
        env.update({k:str(home) for k in ("HOME","USERPROFILE","APPDATA","LOCALAPPDATA","TEMP","TMP")})
        env["GATHER_ALLOW_EXEC"] = "all"
        env["GATHER_ALLOW_NETWORK"] = "all"
        def call(rid, name, args):
            return {"jsonrpc":"2.0","id":rid,"method":"tools/call","params":{"name":name,"arguments":args}}
        outside = dict(SPEC["args"])
        outside[next(iter(outside))] = str(home/"outside.md")
        requests = [
            {"jsonrpc":"2.0","id":1,"method":"initialize","params":{"capabilities":{"sampling":{}}}},
            {"jsonrpc":"2.0","id":2,"method":"tools/list"},
            call(3,SPEC["tool"],SPEC["args"]), call(4,SPEC["danger"],{}),
            call(5,SPEC["tool"],outside),
            call(6,SPEC["tool"],{**SPEC["args"],"allow_exec":True})]
        wire = "".join(json.dumps(row)+"\n" for row in requests)
        code, out, err = run_process(executable,["--workspace",str(workspace)],env,home,wire,timeout=45)
        if code != 0 or err:
            raise ValueError("native MCP failed: "+err[:500])
        rows = [strict_json(line) for line in out.splitlines()]
        if any(set(row) != {"jsonrpc", "id", "result"} or row["jsonrpc"] != "2.0" or type(row["id"]) is not int for row in rows):
            raise ValueError("invalid or unsolicited protocol response")
        if [row.get("id") for row in rows] != [1,2,3,4,5,6] or any("result" not in row for row in rows):
            raise ValueError("native protocol responses missing, duplicated or unsolicited")
        if rows[0]["result"]["serverInfo"]["version"] != version:
            raise ValueError("native version mismatch")
        if rows[0]["result"]["serverInfo"]["name"] != SPEC["name"] + "-local" or rows[0]["result"].get("protocolVersion") != "2025-06-18":
            raise ValueError("native server identity/protocol mismatch")
        tools = {row["name"] for row in rows[1]["result"]["tools"]}
        if tools != EXPECTED_TOOLS or len(rows[1]["result"]["tools"]) != len(EXPECTED_TOOLS):
            raise ValueError("native tool profile mismatch")
        if rows[2]["result"].get("isError") is not False:
            raise ValueError("safe workflow failed: "+json.dumps(rows[2]))
        payload = payload_of(rows[2]["result"])
        if not payload:
            raise ValueError("safe workflow returned no evidence")
        if payload.get("verified") is not True or payload.get("catalog", [{}])[0].get("id") != "sample.md":
            raise ValueError("document provenance result missing")
        if any(row["result"].get("isError") is not True for row in rows[3:]):
            raise ValueError("native permission/path refusal failed")
        if [payload_of(row["result"]).get("code") for row in rows[3:]] != ["TOOL_NOT_GRANTED", "PATH_DENIED", "ARGUMENTS_DENIED"]:
            raise ValueError("internal errors cannot qualify as permission refusals")
        code, out, err = run_process(executable,[],env,home,"",timeout=15)
        if code != 2 or out or "--workspace" not in err:
            raise ValueError("missing workspace did not fail closed")
    if hashlib.sha256(executable.read_bytes()).hexdigest() != before:
        raise ValueError("executable changed during verification")
    return {"status":"PASS","version":version,"executable_sha256":before,
            "tools":sorted(tools),"checks":["safe local workflow","outside path refused",
            "unknown permission refused","ungranted tool refused","launch root required"],
            "does_not_prove":["installed client compatibility","global egress isolation",
                              "full product workflow","semantic truth"]}
