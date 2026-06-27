from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from gather.derive import Synthesizer
    from gather.item import Item
    from gather.run import Job, RunRecord, StoreLike


@dataclass(frozen=True, slots=True)
class RunPlan:
    jobs: list[Job]
    scope: list[str]
    store: StoreLike | None
    synthesizer: Synthesizer | None
    synth_prompt: str
    provenance: Any


def load_run_config(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def build_source(name: str, opts: dict):
    """Construct a source adapter by name (lazy imports keep impure edges out of cold paths)."""
    if name == "web":
        from gather.web import WebSource
        return WebSource()
    if name == "feed":
        from gather.feed import FeedSource
        return FeedSource()
    if name == "docs":
        from gather.docs import DocsSource
        return DocsSource()
    if name == "arxiv":
        from gather.arxiv import ArxivSource
        return ArxivSource(max_results=int(opts.get("max_results", 10)))
    if name == "video":
        from gather.video import VideoSource
        return VideoSource(with_comments=bool(opts.get("comments", False)))
    if name == "pdf":
        from gather.pdf import PdfSource
        return PdfSource()
    if name == "api":
        from gather.api import ApiSource
        return ApiSource(
            auth_env=opts.get("auth_env", "GATHER_API_TOKEN"),
            items_key=opts.get("items_key"), id_key=opts.get("id_key", "id"),
            title_key=opts.get("title_key", "title"), text_key=opts.get("text_key"),
        )
    if name == "browser":
        from gather.browser import BrowserSource
        return BrowserSource()
    if name == "ocr":
        from gather.ocr import OcrSource
        return OcrSource()
    if name == "transcribe":
        from gather.transcribe import TranscribeSource
        return TranscribeSource()
    raise ValueError(f"unknown source: {name!r}")


def plan_from_config(cfg: dict) -> RunPlan:
    from gather.derive import NullSynthesizer
    from gather.store import Corpus

    job_specs = cfg.get("jobs", [])
    if not isinstance(job_specs, list) or not job_specs:
        raise ValueError("config needs a non-empty 'jobs' list")
    jobs = []
    for job in job_specs:
        if "source" not in job or "target" not in job:
            raise ValueError(f"each job needs 'source' and 'target': {job}")
        jobs.append((build_source(job["source"], job), job["target"]))

    scope = cfg.get("scope", [])
    if not isinstance(scope, list):
        raise ValueError("'scope' must be a list of strings")

    store = Corpus(cfg["store"]) if cfg.get("store") else None
    synth_cmd = cfg.get("synthesizer")
    synthesizer: Synthesizer | None
    if synth_cmd:
        if not isinstance(synth_cmd, list):
            raise ValueError('"synthesizer" must be a command list, e.g. ["llm", "-m", "model"]')
        from gather.model import SubprocessSynthesizer
        synthesizer = SubprocessSynthesizer(synth_cmd)
    elif cfg.get("synthesize"):
        synthesizer = NullSynthesizer()
    else:
        synthesizer = None

    prov_cmd = cfg.get("provenance")
    if prov_cmd is not None and not isinstance(prov_cmd, list):
        raise ValueError('"provenance" must be a command list, e.g. ["python", "-m", "provenance", "check"]')
    provider = None
    if prov_cmd:
        from gather.provenance import SubprocessProvenanceProvider
        provider = SubprocessProvenanceProvider(prov_cmd)

    return RunPlan(
        jobs=jobs,
        scope=scope,
        store=store,
        synthesizer=synthesizer,
        synth_prompt=cfg.get("synth_prompt", ""),
        provenance=provider,
    )


def run_plan(plan: RunPlan, *, clock: Callable[[], float] = time.time) -> tuple[RunRecord, list[Item]]:
    from gather.run import gather_run

    return gather_run(
        plan.jobs,
        clock=clock,
        scope=plan.scope,
        store=plan.store,
        synthesizer=plan.synthesizer,
        synth_prompt=plan.synth_prompt,
        provenance=plan.provenance,
    )


def run_from_config_path(path: str, *, clock: Callable[[], float] = time.time) -> tuple[RunRecord, list[Item]]:
    return run_plan(plan_from_config(load_run_config(path)), clock=clock)
