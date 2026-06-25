from __future__ import annotations

from typing import Protocol

from gather.item import Item, content_hash, make_item

SYNTHESIZED = "synthesized"  # the reserved label: an inferred claim, only producible through the seam
COMPILED = "compiled"        # a deterministic verbatim assembly, no new claim


def _make_derived(
    inputs: list[Item],
    statement: str,
    *,
    method: str,
    fetched_at: float,
    ref: str,
    id: str | None,
    title: str,
    kind: str,
    source: str,
) -> Item:
    """Shared builder. Records a statement as derived from inputs, with a given method.

    The sha256 fingerprints the ``statement`` (the inference or assembly is a new piece of
    text and can only witness itself), and ``derived_from`` records the content hash of each
    input in order, a re-checkable pointer back to the exact source content.
    """
    if not inputs:
        raise ValueError("derive needs at least one input item: a statement from nothing is not derivable")
    return make_item(
        kind=kind,
        id=id or content_hash(statement)[:16],
        title=title or ref,
        text=statement,
        source=source,
        ref=ref,
        method=method,
        fetched_at=fetched_at,
        derived_from=tuple(i.provenance.sha256 for i in inputs),
    )


def derive(
    inputs: list[Item],
    statement: str,
    *,
    fetched_at: float,
    ref: str,
    method: str = COMPILED,
    id: str | None = None,
    title: str = "",
    kind: str = "synthesis",
    source: str = "synthesis",
) -> Item:
    """Build one derived item: a statement assembled from inputs, not fetched directly.

    This is the low-level honest builder. It defaults to ``method="compiled"`` and refuses
    ``method="synthesized"``: an inferred claim is only ever producible through the
    Synthesizer seam (``synthesize_item``), where a real model stands behind it, so a bare
    ``derive`` call can never dress something up as a synthesis it did not perform. Like
    ``make_item``, the caller is responsible for the truth of any other label it passes.

    Pure and deterministic. Raises ValueError on empty inputs or on ``method="synthesized"``.
    """
    if method == SYNTHESIZED:
        raise ValueError('method="synthesized" is reserved for a model through the Synthesizer seam; use synthesize_item')
    return _make_derived(
        inputs, statement, method=method, fetched_at=fetched_at, ref=ref,
        id=id, title=title, kind=kind, source=source,
    )


class Synthesizer(Protocol):
    """The seam where a statement gets produced from inputs: the optional model edge.

    ``synthesize`` turns inputs and a prompt into one statement. ``method`` is the honesty
    label its statements deserve: "synthesized" for a real model that infers a new claim,
    "compiled" for a deterministic verbatim assembly. The default is the deterministic
    NullSynthesizer (compilation), so Gather stands alone and never fabricates a synthesis
    it cannot actually perform; a model plugs in through this shape, the peer-composition
    way, without the core importing it.
    """

    method: str

    def synthesize(self, inputs: list[Item], prompt: str) -> str: ...


class NullSynthesizer:
    """The standing default: a deterministic, extractive compilation, never a new claim.

    With no model wired in, Gather still composes inputs honestly: it assembles them
    verbatim under the prompt as a heading and labels the result ``compiled``. It invents
    nothing, so it is safe to be the default. Real abstractive synthesis (a new inferred
    claim, ``method="synthesized"``) requires a model plugged into the Synthesizer seam.
    """

    method = COMPILED

    def synthesize(self, inputs: list[Item], prompt: str) -> str:
        parts = [prompt.strip()] if prompt.strip() else []
        for it in inputs:
            head = it.title.strip() or f"{it.provenance.source}:{it.id}"
            parts.append(f"- {head}: {it.text.strip()}")
        return "\n".join(parts)


def synthesize_item(
    synth: Synthesizer,
    inputs: list[Item],
    prompt: str,
    *,
    fetched_at: float,
    ref: str,
    id: str | None = None,
    title: str = "",
    kind: str = "synthesis",
) -> Item:
    """Run a synthesizer over inputs and stamp the result with that synthesizer's method.

    The only path to a ``synthesized`` item, and the bridge from the Synthesizer seam to a
    receipted Item: the statement comes from the synthesizer, and the item is stamped with
    the synthesizer's own ``method`` (so the NullSynthesizer yields a ``compiled`` item and
    a model yields a ``synthesized`` one), with ``derived_from`` set to the inputs. The
    honesty is mechanical, not a promise: the label is the producer's, not the caller's.
    """
    statement = synth.synthesize(inputs, prompt)
    return _make_derived(
        inputs, statement, method=synth.method, fetched_at=fetched_at, ref=ref,
        id=id, title=title or prompt, kind=kind, source="synthesis",
    )
