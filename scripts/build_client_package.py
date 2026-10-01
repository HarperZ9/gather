"""Build deterministic local client bundles; release mode requires exact clean tags."""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SPEC = json.loads((ROOT / "scripts/client-package.json").read_text())
def digest(data):
    return hashlib.sha256(data).hexdigest()

def version():
    text = (ROOT / "src" / SPEC["pkg"] / "__init__.py").read_text(encoding="utf-8")
    match = re.search(r'^__version__ = ["\']([^"\']+)', text, re.M)
    if not match:
        raise ValueError("missing package version")
    value = match[1]
    import tomllib
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    if "version" in project and project["version"] != value:
        raise ValueError("project/module version mismatch")
    for file in ("plugin.json", ".claude-plugin/plugin.json", ".codex-plugin/plugin.json"):
        if json.loads((ROOT / "client-plugin" / file).read_text())["version"] != value:
            raise ValueError("plugin version mismatch")
    if SPEC["version"] != value:
        raise ValueError("client package version mismatch")
    return value

def git(*args):
    return subprocess.check_output(["git", "-C", str(ROOT), *args], text=True).strip()

def qualify(mode):
    value = version()
    head = git("rev-parse", "HEAD")
    if mode == "release":
        if not value.endswith(".0"):
            raise ValueError("mature release must end in .0")
        if git("status", "--porcelain", "--untracked-files=all"):
            raise ValueError("release source must be clean")
        if git("rev-parse", "--verify", "refs/tags/v" + value + "^{commit}") != head:
            raise ValueError("release must match exact version tag")
        if os.environ.get("GITHUB_REF", "refs/tags/v" + value) != "refs/tags/v" + value:
            raise ValueError("release ref mismatch")
    return {"mode": mode, "version": value, "commit": head}

def entries(root):
    if root.is_symlink() or getattr(root.lstat(), "st_file_attributes", 0) & 0x400:
        raise ValueError("package root is a link or reparse point")
    root = root.resolve()
    result = {}
    for directory, dirs, files in os.walk(root, followlinks=False):
        for name in [*dirs, *files]:
            path = Path(directory) / name
            if name.lower().startswith(".env") or name.lower() in {"credentials", "credentials.json", "secrets", "secrets.json"} or path.suffix.lower() in {".key", ".pem", ".pfx", ".p12"}:
                raise ValueError("credential-like material cannot enter a client package")
            if path.is_symlink() or getattr(path.lstat(), "st_file_attributes", 0) & 0x400:
                raise ValueError("package contains a link or reparse point")
            if not path.resolve().is_relative_to(root):
                raise ValueError("package path escaped")
        dirs[:] = [d for d in dirs if d not in {"__pycache__", ".git"} and not d.endswith((".egg-info", ".dist-info"))]
        for name in files:
            path = Path(directory) / name
            if path.suffix not in {".pyc", ".pyo"}:
                result[path.relative_to(root).as_posix()] = path.read_bytes()
    return result

def write_zip(path, payload):
    with zipfile.ZipFile(path, "x", compression=zipfile.ZIP_STORED) as archive:
        for name, data in sorted(payload.items()):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data)

def checksums(payload):
    return "".join(f"{digest(data)}  {name}\n" for name, data in sorted(payload.items())).encode()

def build(output, mode="release", native=False):
    qualified = qualify(mode)
    output = Path(output).absolute()
    if output.exists() or output.resolve().is_relative_to(ROOT):
        raise ValueError("output must be a new directory outside source")
    source = entries(ROOT / "src")
    scripts = entries(ROOT / "scripts")
    plugin = entries(ROOT / "client-plugin")
    tracked = set(git("ls-files").splitlines())
    if mode == "release":
        candidates = {**{"src/"+k:v for k,v in source.items()},
                      **{"scripts/"+k:v for k,v in scripts.items()},
                      **{"client-plugin/"+k:v for k,v in plugin.items()}}
        if set(candidates) - tracked:
            raise ValueError("release payload contains untracked or ignored files")
    source_hashes = {**{"src/"+k: digest(v) for k,v in source.items()},
                     **{"scripts/"+k: digest(v) for k,v in scripts.items()},
                     **{"client-plugin/"+k: digest(v) for k,v in plugin.items()}}
    output.mkdir(parents=True)
    payload = {**plugin, **{"server/src/"+k:v for k,v in source.items()}}
    payload["LICENSE"] = (ROOT / "LICENSE").read_bytes()
    payload["SOURCE.json"] = (json.dumps(qualified, indent=2)+"\n").encode()
    payload["PAYLOAD-SHA256SUMS"] = checksums(payload)
    label = "-dev" if mode == "dev" else ""
    stem = SPEC["name"] + "-client-" + qualified["version"] + label
    artifacts = output / "artifacts"
    artifacts.mkdir()
    paths = [artifacts / (stem + "-source.zip")]
    write_zip(paths[0], payload)
    receipt = {"source": qualified, "source_sha256": source_hashes, "native": None,
               "does_not_prove": ["full product workflow maturity", "client installation",
                                  "marketplace acceptance", "OS sandbox isolation"]}
    if native:
        if sys.platform != "win32" or platform.machine().lower() not in {"amd64", "x86_64"}:
            raise ValueError("native build requires Windows x64")
        env = {k:v for k,v in os.environ.items() if k.upper() in {"SYSTEMROOT","WINDIR","TEMP","TMP","SYSTEMDRIVE"}}
        env["PATH"] = os.pathsep.join([sys.base_prefix, str(Path(env.get("SYSTEMROOT", "C:/Windows"))/"System32")])
        home = output / "build-home"
        home.mkdir()
        env.update({k:str(home) for k in ("HOME","USERPROFILE","APPDATA","LOCALAPPDATA")})
        command = [sys.executable, "-m", "PyInstaller", "--onefile", "--console", "--clean",
                   "--name", SPEC["name"]+"-local", "--paths", str(ROOT/"src"),
                   "--collect-submodules", SPEC["pkg"],
                   "--distpath", str(output/"stage"), "--workpath", str(output/"work"),
                   "--specpath", str(output/"spec"), str(ROOT/"scripts/native_client_entry.py")]
        with (output/"freeze.log").open("w", encoding="utf-8") as log:
            subprocess.run(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, check=True)
        from native_build_provenance import dependencies
        native_deps = dependencies(output / ("work/"+SPEC["name"]+"-local/Analysis-00.toc"), sys.base_prefix)
        exe = output / ("stage/"+SPEC["name"]+"-local.exe")
        from check_native_client import check
        validation = check(exe, qualified["version"])
        native_payload = {"server/"+exe.name:exe.read_bytes(), "LICENSE":payload["LICENSE"],
                          "README.md":plugin["README.md"],
                          "PYTHON-LICENSE.txt":(Path(sys.base_prefix)/"LICENSE.txt").read_bytes()}
        dist = importlib.metadata.distribution("pyinstaller")
        copying = [dist.locate_file(p) for p in dist.files if str(p).endswith("/licenses/COPYING.txt")]
        if len(copying) != 1:
            raise ValueError("PyInstaller license not found")
        native_payload["PYINSTALLER-LICENSE.txt"] = copying[0].read_bytes()
        manifest = {"manifest_version":"0.3", "name":SPEC["name"]+"-local",
            "version":qualified["version"], "display_name":SPEC["name"].title()+" Local",
            "description":SPEC["desc"], "author":{"name":"Zain Dana Harper"}, "license":"FSL-1.1-MIT",
            "server":{"type":"binary", "entry_point":"server/"+exe.name, "mcp_config":{
                "command":"${__dirname}/server/"+exe.name,
                "args":["--workspace", "${user_config.workspace}"], "env":{}}},
            "user_config":{"workspace":{"type":"directory", "title":"Readable workspace",
                "description":"Local directory this profile may read. Choose only approved files.", "required":True}},
            "compatibility":{"platforms":["win32"]}}
        native_payload["manifest.json"] = (json.dumps(manifest, indent=2)+"\n").encode()
        native_payload["QUALIFICATION.json"] = (json.dumps({"source":qualified,"validation":validation}, indent=2)+"\n").encode()
        native_payload["PAYLOAD-SHA256SUMS"] = checksums(native_payload)
        for suffix in ("zip","mcpb"):
            target = artifacts / (stem+"-win-x64."+suffix)
            write_zip(target, native_payload)
            paths.append(target)
        receipt["native"] = {"validation":validation, "dependencies":native_deps, "python":sys.version,
                            "pyinstaller":importlib.metadata.version("pyinstaller"), "command":command}
    current = {**{"src/"+k:digest(v) for k,v in entries(ROOT/"src").items()},
               **{"scripts/"+k:digest(v) for k,v in entries(ROOT/"scripts").items()},
               **{"client-plugin/"+k:digest(v) for k,v in entries(ROOT/"client-plugin").items()}}
    if current != source_hashes:
        raise ValueError("source changed during build")
    receipt["artifacts"] = {p.name:digest(p.read_bytes()) for p in paths}
    (output/"build-receipt.json").write_text(json.dumps(receipt,indent=2)+"\n",encoding="utf-8")
    (artifacts/"CLIENT-SHA256SUMS.txt").write_bytes(checksums({p.name:p.read_bytes() for p in paths}))
    return paths

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output")
    parser.add_argument("--mode", choices=("dev","release"), default="release")
    parser.add_argument("--native", action="store_true")
    args = parser.parse_args()
    for path in build(args.output, args.mode, args.native):
        print(path)
