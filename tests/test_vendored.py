"""The vendored safe_spawn helper stays byte-identical to the canonical 1.0.0 release."""
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# The canonical SHA-256 of safe_spawn.py 1.0.0, from the helper's own SHA256SUMS.
CANONICAL = {"safe_spawn.py": "cb2dfa9447380f637d294244c6bdf591db1a4a1abf40312a4671b785b8e1bea6"}


def _records():
    rows = []
    for line in (ROOT / "VENDORED.sha256").read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#"):
            digest, rel = line.split(None, 1)
            rows.append((digest.lower(), rel.strip().lstrip("*")))
    return rows


def test_every_vendored_copy_matches_its_record_and_the_canonical_hash():
    rows = _records()
    assert rows, "VENDORED.sha256 lists no copies"
    for digest, rel in rows:
        data = (ROOT / rel).read_bytes()
        assert hashlib.sha256(data).hexdigest() == digest, f"{rel} drifted from its record"
        assert CANONICAL.get(Path(rel).name) == digest, f"{rel} is not a canonical release"


def test_the_package_imports_the_vendored_helper():
    from gather._vendor import safe_spawn

    assert safe_spawn.SAFE_SPAWN_VERSION == "1.0.0"
