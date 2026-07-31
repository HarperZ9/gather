"""Deterministic shared and full pilot bundles.

A shared bundle carries only the safe public surfaces (report, receipt,
manifest digest, bundle receipt) as a deterministic ZIP that any third party
re-verifies without private source material. A full bundle additionally carries
the verified artifact root (corpus, monitor state, history) and requires
explicit confirmation.
"""
from __future__ import annotations

import json
import os
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from gather.pilot import PilotRefusal, verify_pilot
from gather.pilot_report import canonical_json_bytes, sha256_bytes

PILOT_BUNDLE_SCHEMA = "gather.pilot-bundle/1"

SHARED_MEMBERS = (
    "bundle-receipt.json",
    "manifest-digest.json",
    "pilot-receipt.json",
    "report.html",
    "report.json",
)

# Relative artifact-root members excluded from a shared bundle (private).
_PRIVATE_ROOT_MEMBERS = ("corpus", "monitor-state.json", "history", "manifest.json")

_BUNDLE_RECEIPT_FIELDS = {
    "schema",
    "visibility",
    "source_receipt_sha256",
    "members",
    "bundle_digest",
}


@dataclass(frozen=True, slots=True)
class PilotBundleReceipt:
    schema: str
    visibility: str
    source_receipt_sha256: str
    members: tuple[tuple[str, str], ...]
    bundle_digest: str

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "visibility": self.visibility,
            "source_receipt_sha256": self.source_receipt_sha256,
            "members": [list(pair) for pair in self.members],
            "bundle_digest": self.bundle_digest,
        }


@dataclass(frozen=True, slots=True)
class BundleVerification:
    schema_verified: bool
    member_digests_verified: bool
    bundle_digest_verified: bool
    source_verified: bool
    paths_verified: bool

    @property
    def ok(self) -> bool:
        return (
            self.schema_verified
            and self.member_digests_verified
            and self.bundle_digest_verified
            and self.source_verified
            and self.paths_verified
        )


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_STORED
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    return info


def _safe_relative(name: str) -> bool:
    posix = PurePosixPath(name)
    return (
        bool(name)
        and not posix.is_absolute()
        and ".." not in posix.parts
        and "\\" not in name
        and posix.as_posix() == name
    )


def _read_json(path: Path) -> dict[str, object] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _manifest_digest_payload(manifest: Mapping[str, object]) -> dict[str, object]:
    """Safe, public identity projection of the manifest.

    Includes only schema, pilot id, manifest digest, deployment, and the
    mission/source id/adapter/visibility/outcome scaffold. Omits targets,
    fixtures, local roots, credentials, and option values.
    """
    missions: list[dict[str, object]] = []
    raw_missions = manifest.get("missions")
    if isinstance(raw_missions, list):
        for mission in raw_missions:
            if not isinstance(mission, Mapping):
                continue
            sources_out: list[dict[str, object]] = []
            raw_sources = mission.get("sources")
            if isinstance(raw_sources, list):
                for source in raw_sources:
                    if isinstance(source, Mapping):
                        sources_out.append(
                            {
                                "id": source.get("id"),
                                "adapter": source.get("adapter"),
                                "visibility": source.get("visibility"),
                            }
                        )
            missions.append({"id": mission.get("id"), "sources": sources_out})
    return {
        "schema": "gather.pilot-manifest-digest/1",
        "pilot_id": manifest.get("pilot_id"),
        "manifest_sha256": sha256_bytes(canonical_json_bytes(manifest)),
        "deployment": manifest.get("deployment"),
        "missions": missions,
    }


def _bundle_digest(
    visibility: str,
    source_receipt_sha256: str,
    members: tuple[tuple[str, str], ...],
) -> str:
    payload = {
        "schema": PILOT_BUNDLE_SCHEMA,
        "visibility": visibility,
        "source_receipt_sha256": source_receipt_sha256,
        "members": [[path, sha] for path, sha in sorted(members)],
    }
    return sha256_bytes(canonical_json_bytes(payload))


def _shared_member_bytes(root: Path) -> dict[str, bytes]:
    """Build the public member bodies, synthesizing the safe projections."""
    manifest = _read_json(root / "manifest.json")
    pilot_receipt = _read_json(root / "pilot-receipt.json")
    if manifest is None or pilot_receipt is None:
        raise PilotRefusal("pilot root is missing a manifest or receipt")
    policy = manifest.get("policy")
    if isinstance(policy, Mapping) and policy.get("report_private_content") is True:
        raise PilotRefusal("shared bundle refuses a manifest that requests private content")
    members: dict[str, bytes] = {
        "report.json": (root / "report.json").read_bytes(),
        "report.html": (root / "report.html").read_bytes(),
        "pilot-receipt.json": (root / "pilot-receipt.json").read_bytes(),
        "manifest-digest.json": canonical_json_bytes(_manifest_digest_payload(manifest)),
    }
    source_receipt_sha256 = pilot_receipt.get("manifest_sha256")
    if not isinstance(source_receipt_sha256, str):
        raise PilotRefusal("pilot receipt lacks a manifest digest")
    member_digests = tuple((name, sha256_bytes(body)) for name, body in members.items())
    receipt = PilotBundleReceipt(
        schema=PILOT_BUNDLE_SCHEMA,
        visibility="shared",
        source_receipt_sha256=source_receipt_sha256,
        members=member_digests,
        bundle_digest=_bundle_digest("shared", source_receipt_sha256, member_digests),
    )
    members["bundle-receipt.json"] = canonical_json_bytes(receipt.to_dict())
    return members


def _full_member_bytes(root: Path) -> dict[str, bytes]:
    """The full bundle: the verified artifact root plus the bundle receipt."""
    manifest = _read_json(root / "manifest.json")
    pilot_receipt = _read_json(root / "pilot-receipt.json")
    if manifest is None or pilot_receipt is None:
        raise PilotRefusal("pilot root is missing a manifest or receipt")
    source_receipt_sha256 = pilot_receipt.get("manifest_sha256")
    if not isinstance(source_receipt_sha256, str):
        raise PilotRefusal("pilot receipt lacks a manifest digest")
    members: dict[str, bytes] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            rel = path.relative_to(root).as_posix()
            members[rel] = path.read_bytes()
    member_digests = tuple((name, sha256_bytes(body)) for name, body in members.items())
    receipt = PilotBundleReceipt(
        schema=PILOT_BUNDLE_SCHEMA,
        visibility="full",
        source_receipt_sha256=source_receipt_sha256,
        members=member_digests,
        bundle_digest=_bundle_digest("full", source_receipt_sha256, member_digests),
    )
    members["bundle-receipt.json"] = canonical_json_bytes(receipt.to_dict())
    return members


def _write_zip(out: Path, members: dict[str, bytes]) -> None:
    if out.exists():
        raise PilotRefusal("bundle output already exists")
    for name in members:
        if not _safe_relative(name):
            raise PilotRefusal(f"bundle member path is not a safe relative POSIX path: {name}")
    temporary = out.with_name(out.name + ".tmp")
    try:
        with zipfile.ZipFile(temporary, "w", zipfile.ZIP_STORED) as zf:
            for name in sorted(members):
                zf.writestr(_zip_info(name), members[name])
        os.replace(temporary, out)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def create_pilot_bundle(
    root: Path,
    output: Path,
    *,
    visibility: str,
    include_private_evidence: bool = False,
) -> PilotBundleReceipt:
    """Create a deterministic shared or full bundle from a verified pilot root.

    Verifies the source root first. ``visibility="shared"`` produces the public
    surface only; ``visibility="full"`` adds the artifact root and requires
    ``include_private_evidence=True``.
    """
    if not verify_pilot(root).ok:
        raise PilotRefusal("pilot root does not verify; refusing to bundle")
    if visibility == "shared":
        members = _shared_member_bytes(root)
    elif visibility == "full":
        if not include_private_evidence:
            raise PilotRefusal("full bundle requires explicit include_private_evidence confirmation")
        members = _full_member_bytes(root)
    else:
        raise PilotRefusal(f"unknown bundle visibility: {visibility}")
    _write_zip(Path(output), members)
    receipt_body = members["bundle-receipt.json"]
    receipt_value = json.loads(receipt_body)
    return PilotBundleReceipt(
        schema=receipt_value["schema"],
        visibility=receipt_value["visibility"],
        source_receipt_sha256=receipt_value["source_receipt_sha256"],
        members=tuple(tuple(pair) for pair in receipt_value["members"]),
        bundle_digest=receipt_value["bundle_digest"],
    )


def verify_pilot_bundle(zip_path: Path) -> BundleVerification:
    """Re-derive the bundle digest and check every member digest; reject extras."""
    try:
        with zipfile.ZipFile(zip_path) as zf:
            infos = zf.infolist()
            names = [info.filename for info in infos]
            bodies = {info.filename: zf.read(info) for info in infos}
    except (OSError, zipfile.BadZipFile):
        return BundleVerification(False, False, False, False, False)

    paths_ok = all(_safe_relative(n) for n in names) and len(set(names)) == len(names)
    receipt_body = bodies.get("bundle-receipt.json")
    if receipt_body is None:
        return BundleVerification(False, False, False, False, paths_ok)
    try:
        receipt = json.loads(receipt_body)
    except json.JSONDecodeError:
        return BundleVerification(False, False, False, False, paths_ok)
    if not isinstance(receipt, Mapping) or set(receipt) != _BUNDLE_RECEIPT_FIELDS:
        return BundleVerification(False, False, False, False, paths_ok)
    schema_ok = receipt.get("schema") == PILOT_BUNDLE_SCHEMA
    visibility = receipt.get("visibility")
    source_sha = receipt.get("source_receipt_sha256")
    listed = receipt.get("members")
    if not isinstance(visibility, str) or not isinstance(source_sha, str) or not isinstance(listed, list):
        return BundleVerification(False, False, False, False, paths_ok)

    member_pairs: list[tuple[str, str]] = []
    for entry in listed:
        if (
            not isinstance(entry, list)
            or len(entry) != 2
            or not isinstance(entry[0], str)
            or not isinstance(entry[1], str)
        ):
            return BundleVerification(schema_ok, False, False, False, paths_ok)
        member_pairs.append((entry[0], entry[1]))

    # Every body except the receipt must be a listed member; no extras.
    body_names = set(bodies) - {"bundle-receipt.json"}
    listed_names = {name for name, _ in member_pairs}
    member_digests_ok = body_names == listed_names and all(
        sha256_bytes(bodies[name]) == sha for name, sha in member_pairs
    )

    expected_digest = _bundle_digest(visibility, source_sha, tuple(member_pairs))
    bundle_digest_ok = expected_digest == receipt.get("bundle_digest")

    return BundleVerification(
        schema_verified=schema_ok,
        member_digests_verified=member_digests_ok,
        bundle_digest_verified=bundle_digest_ok,
        source_verified=isinstance(source_sha, str) and bool(source_sha),
        paths_verified=paths_ok,
    )
