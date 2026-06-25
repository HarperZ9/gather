import importlib.util
import pathlib


def _load_demo():
    p = pathlib.Path(__file__).resolve().parent.parent / "examples" / "demo.py"
    spec = importlib.util.spec_from_file_location("gather_demo", p)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_demo_runs_and_shows_the_load_bearing_facts(capsys):
    # pins the facts the README's "Watch it work" block promises, immune to hash churn
    _load_demo().main()
    out = capsys.readouterr().out
    assert out.count("verify=True") == 3          # three items, each with a valid receipt
    assert "verified True" in out                 # the witnessed digest verifies
    assert "verifies: False  <- caught" in out    # tampering one receipt is caught
