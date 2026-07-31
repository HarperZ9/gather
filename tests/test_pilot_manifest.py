import copy
import json
import os
from pathlib import Path

import pytest

from gather.pilot_manifest import (
    PilotManifest,
    load_pilot_manifest,
    manifest_digest,
    manifest_payload,
    validate_pilot_manifest,
)


def valid_manifest(tmp_path: Path) -> dict[str, object]:
    """A hand-written offline manifest that uses only the allowlisted root."""
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir(exist_ok=True)
    (fixtures / "source.html").write_text("<h1>offline</h1>", encoding="utf-8")
    return {
        "schema": "gather.pilot-manifest/1",
        "pilot_id": "pilot-one",
        "title": "Offline pilot",
        "mode": "offline",
        "deployment": {"mode": "workstation", "custodian": "customer"},
        "policy": {
            "allowed_hosts": [],
            "trusted_browser_hosts": [],
            "allowed_local_roots": ["fixtures"],
            "enabled_adapters": ["docs"],
            "credentials": [],
            "report_private_content": False,
        },
        "missions": [
            {
                "id": "mission-one",
                "title": "Offline evidence",
                "sources": [
                    {
                        "id": "source-one",
                        "adapter": "docs",
                        "target": "fixtures/source.html",
                        "fixture": None,
                        "refresh_fixture": None,
                        "visibility": "private",
                        "monitor": False,
                        "required": True,
                        "extraction": None,
                        "options": {},
                    }
                ],
            }
        ],
    }


def source(data: dict[str, object]) -> dict[str, object]:
    return data["missions"][0]["sources"][0]  # type: ignore[index, return-value]


def test_valid_offline_docs_manifest_has_immutable_runtime_shapes(tmp_path: Path) -> None:
    manifest = validate_pilot_manifest(valid_manifest(tmp_path), tmp_path)

    assert isinstance(manifest, PilotManifest)
    assert manifest.mode == "offline"
    assert manifest.deployment.mode == "workstation"
    assert manifest.deployment.custodian == "customer"
    assert manifest.policy.enabled_adapters == ("docs",)
    assert manifest.missions[0].sources[0].resolved_target == tmp_path / "fixtures" / "source.html"


def test_manifest_digest_is_independent_of_input_key_order(tmp_path: Path) -> None:
    first = valid_manifest(tmp_path)
    second = json.loads(json.dumps(first))
    second["policy"] = dict(reversed(list(second["policy"].items())))

    one = validate_pilot_manifest(first, tmp_path)
    two = validate_pilot_manifest(second, tmp_path)

    assert manifest_payload(one) == manifest_payload(two)
    assert manifest_digest(one) == manifest_digest(two)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda d: d.update({"surprise": True}), "unknown manifest field"),
        (lambda d: d["policy"].update({"wildcard": "*"}), "unknown policy field"),
        (lambda d: source(d).update({"retry": 9}), "unknown source field"),
        (lambda d: d["missions"][0].update({"extra": True}), "unknown mission field"),
        (lambda d: d["deployment"].update({"extra": True}), "unknown deployment field"),
    ],
)
def test_closed_shapes_refuse_unknown_fields(tmp_path: Path, mutate, message: str) -> None:
    data = valid_manifest(tmp_path)
    mutate(data)
    with pytest.raises(ValueError, match=message):
        validate_pilot_manifest(data, tmp_path)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda d: d.update({"pilot_id": "Bad ID"}), "pilot_id"),
        (lambda d: d["missions"][0].update({"id": "Bad ID"}), "mission.id"),
        (lambda d: source(d).update({"id": "Bad ID"}), "source.id"),
        (lambda d: d.update({"mode": "staging"}), "manifest.mode"),
        (lambda d: d["deployment"].update({"mode": "invalid"}), "deployment.mode"),
        (lambda d: d["deployment"].update({"custodian": "invalid"}), "deployment.custodian"),
        (lambda d: source(d).update({"visibility": "partner"}), "visibility"),
        (lambda d: source(d)["options"].update({"unknown": True}), "docs options"),
        (lambda d: source(d).update({"extraction": {"title": {"selector": "h1"}}}), "does not support extraction"),
        (lambda d: d["policy"].update({"credentials": ["bad credential"]}), "credential"),
    ],
)
def test_rejects_invalid_values_with_located_errors(tmp_path: Path, mutate, message: str) -> None:
    data = valid_manifest(tmp_path)
    mutate(data)
    with pytest.raises(ValueError, match=message):
        validate_pilot_manifest(data, tmp_path)


def test_refuses_duplicate_mission_and_source_ids(tmp_path: Path) -> None:
    missions = valid_manifest(tmp_path)["missions"]
    duplicate_mission = copy.deepcopy(missions[0])
    missions.append(duplicate_mission)
    with pytest.raises(ValueError, match="duplicate mission id"):
        validate_pilot_manifest({**valid_manifest(tmp_path), "missions": missions}, tmp_path)

    data = valid_manifest(tmp_path)
    duplicate_source = copy.deepcopy(source(data))
    data["missions"][0]["sources"].append(duplicate_source)
    with pytest.raises(ValueError, match="duplicate source id"):
        validate_pilot_manifest(data, tmp_path)


def test_rejects_local_path_escape_and_symlink_escape(tmp_path: Path) -> None:
    data = valid_manifest(tmp_path)
    source(data)["target"] = "fixtures/../outside.html"
    (tmp_path / "outside.html").write_text("outside", encoding="utf-8")
    with pytest.raises(ValueError, match="allowed local root"):
        validate_pilot_manifest(data, tmp_path)

    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.html").write_text("secret", encoding="utf-8")
    try:
        (tmp_path / "fixtures" / "escape").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("the current Windows environment does not permit symlink creation")
    data = valid_manifest(tmp_path)
    source(data)["target"] = "fixtures/escape/secret.html"
    with pytest.raises(ValueError, match="allowed local root"):
        validate_pilot_manifest(data, tmp_path)


def test_offline_network_source_requires_fixture_and_live_source_forbids_one(tmp_path: Path) -> None:
    data = valid_manifest(tmp_path)
    data["policy"]["allowed_hosts"] = ["example.com"]
    data["policy"]["enabled_adapters"] = ["web"]
    source(data).update({"adapter": "web", "target": "https://example.com/evidence", "fixture": None})
    with pytest.raises(ValueError, match="offline network source requires a fixture"):
        validate_pilot_manifest(data, tmp_path)

    data = valid_manifest(tmp_path)
    data.update({"mode": "live"})
    data["deployment"]["mode"] = "workstation"
    data["policy"]["allowed_hosts"] = ["example.com"]
    data["policy"]["enabled_adapters"] = ["web"]
    source(data).update(
        {"adapter": "web", "target": "https://example.com/evidence", "fixture": "fixtures/source.html"}
    )
    with pytest.raises(ValueError, match="live source may not define a fixture"):
        validate_pilot_manifest(data, tmp_path)


def test_refresh_fixture_requires_a_monitoring_adapter_and_monitor_flag(tmp_path: Path) -> None:
    data = valid_manifest(tmp_path)
    source(data)["refresh_fixture"] = "fixtures/source.html"
    with pytest.raises(ValueError, match="refresh_fixture requires monitor"):
        validate_pilot_manifest(data, tmp_path)


def test_live_source_rejects_refresh_fixture(tmp_path: Path) -> None:
    data = valid_manifest(tmp_path)
    data["mode"] = "live"
    data["policy"].update({"allowed_hosts": ["example.com"], "enabled_adapters": ["web"]})
    source(data).update(
        {
            "adapter": "web",
            "target": "https://example.com/evidence",
            "fixture": None,
            "refresh_fixture": "fixtures/source.html",
            "monitor": True,
        }
    )

    with pytest.raises(ValueError, match="live source may not define a refresh_fixture"):
        validate_pilot_manifest(data, tmp_path)


def test_extraction_uses_a_closed_fields_object(tmp_path: Path) -> None:
    data = valid_manifest(tmp_path)
    data["policy"].update({"allowed_hosts": ["example.com"], "enabled_adapters": ["web"]})
    source(data).update(
        {
            "adapter": "web",
            "target": "https://example.com/evidence",
            "fixture": "fixtures/source.html",
            "extraction": {"fields": {"title": {"selector": "h1"}}},
        }
    )

    manifest = validate_pilot_manifest(data, tmp_path)
    assert manifest.missions[0].sources[0].extraction["title"].selector == "h1"  # type: ignore[index]


def test_extraction_rejects_unknown_top_level_keys(tmp_path: Path) -> None:
    data = valid_manifest(tmp_path)
    data["policy"].update({"allowed_hosts": ["example.com"], "enabled_adapters": ["web"]})
    source(data).update(
        {
            "adapter": "web",
            "target": "https://example.com/evidence",
            "fixture": "fixtures/source.html",
            "extraction": {"fields": {}, "surprise": True},
        }
    )

    with pytest.raises(ValueError, match="unknown extraction field"):
        validate_pilot_manifest(data, tmp_path)


def test_policy_and_source_boolean_defaults_apply_only_when_absent(tmp_path: Path) -> None:
    data = valid_manifest(tmp_path)
    del data["policy"]["report_private_content"]
    del source(data)["required"]

    manifest = validate_pilot_manifest(data, tmp_path)
    item = manifest.missions[0].sources[0]
    assert manifest.policy.report_private_content is False
    assert item.required is True


def test_nested_options_are_immutable_and_do_not_change_the_digest(tmp_path: Path) -> None:
    data = valid_manifest(tmp_path)
    data["policy"].update({"allowed_hosts": ["export.arxiv.org"], "enabled_adapters": ["arxiv"]})
    source(data).update(
        {
            "adapter": "arxiv",
            "target": "https://export.arxiv.org/api/query",
            "fixture": "fixtures/source.html",
            "options": {"max_results": {"limits": ["fixed"]}},
        }
    )
    manifest = validate_pilot_manifest(data, tmp_path)
    options = manifest.missions[0].sources[0].options
    digest = manifest_digest(manifest)

    with pytest.raises(TypeError):
        options["max_results"]["limits"] = ("changed",)  # type: ignore[index]
    assert manifest_digest(manifest) == digest
    assert manifest_payload(manifest)["missions"][0]["sources"][0]["options"] == {
        "max_results": {"limits": ["fixed"]}
    }


def test_load_pilot_manifest_reads_a_json_object_relative_to_its_file(tmp_path: Path) -> None:
    path = tmp_path / "pilot.json"
    path.write_text(json.dumps(valid_manifest(tmp_path)), encoding="utf-8")

    manifest = load_pilot_manifest(path)
    assert manifest.base_dir == tmp_path
    assert manifest.pilot_id == "pilot-one"


@pytest.mark.parametrize(("contents", "message"), [("{", "invalid pilot manifest JSON"), ("[]", "manifest must be an object")])
def test_load_pilot_manifest_rejects_invalid_json_shapes(tmp_path: Path, contents: str, message: str) -> None:
    path = tmp_path / "pilot.json"
    path.write_text(contents, encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        load_pilot_manifest(path)


def test_browser_requires_trusted_exact_host_and_rejects_host_shortcuts(tmp_path: Path) -> None:
    data = valid_manifest(tmp_path)
    data["policy"].update(
        {
            "allowed_hosts": ["example.com"],
            "trusted_browser_hosts": [],
            "enabled_adapters": ["browser"],
        }
    )
    source(data).update({"adapter": "browser", "target": "https://example.com/evidence", "fixture": "fixtures/source.html"})
    with pytest.raises(ValueError, match="trusted browser host"):
        validate_pilot_manifest(data, tmp_path)

    data["policy"]["trusted_browser_hosts"] = ["example.com"]
    source(data)["target"] = "https://sub.example.com/evidence"
    with pytest.raises(ValueError, match="allowed host"):
        validate_pilot_manifest(data, tmp_path)


@pytest.mark.parametrize(
    "target",
    [
        "https://Example.com/evidence",
        "https://example.com./evidence",
        "https://example.com:443/evidence",
        "https://user@example.com/evidence",
        "https://127.0.0.1/evidence",
    ],
)
def test_network_targets_reject_noncanonical_hosts(tmp_path: Path, target: str) -> None:
    data = valid_manifest(tmp_path)
    data["policy"].update({"allowed_hosts": ["example.com"], "enabled_adapters": ["web"]})
    source(data).update({"adapter": "web", "target": target, "fixture": "fixtures/source.html"})
    with pytest.raises(ValueError, match="host|port|user information"):
        validate_pilot_manifest(data, tmp_path)


def test_payload_omits_runtime_paths_and_never_reads_credential_values(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "not-a-manifest-value"
    monkeypatch.setitem(os.environ, "PILOT_SECRET", secret)
    data = valid_manifest(tmp_path)
    data["policy"]["credentials"] = ["PILOT_SECRET"]
    manifest = validate_pilot_manifest(data, tmp_path)

    payload = manifest_payload(manifest)
    serialized = json.dumps(payload, sort_keys=True)
    assert str(tmp_path) not in serialized
    assert secret not in serialized
    assert payload["missions"][0]["sources"][0]["target"] == "fixtures/source.html"
    assert "resolved_target" not in serialized
