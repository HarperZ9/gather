import subprocess
import sys
from pathlib import Path

import gather

ROOT = Path(__file__).resolve().parents[1]


def test_version_is_exposed():
    assert isinstance(gather.__version__, str) and gather.__version__.count(".") == 2


def test_stable_surface_is_importable_from_the_top_level():
    # the curated public API works without reaching into submodules
    it = gather.make_item(kind="document", id="a", title="A", text="hello",
                          source="web", ref="a", method="http-get", fetched_at=1.0)
    assert isinstance(it, gather.Item)
    d = gather.digest([it])
    assert gather.verify_digest(d) is True
    for name in ("Corpus", "gather_run", "recall", "Query", "RunRecord", "Source", "Catalog",
                 "derive", "synthesize_item", "NullSynthesizer", "content_hash"):
        assert hasattr(gather, name), name


def test_all_names_resolve():
    for name in gather.__all__:
        assert hasattr(gather, name), name


def test_source_checkout_supports_cli_module_path():
    completed = subprocess.run(
        [sys.executable, "-m", "gather.cli", "--help"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=10,
    )

    assert completed.returncode == 0, completed.stderr
    assert "Gather: accountable research intake" in completed.stdout
