from __future__ import annotations

from typing import Protocol

from gather.item import Item, content_hash, make_item


def derive(
    inputs: list[Item],
    statement: str,
    *,
    fetched_at: float,
    ref: str,
    method: str = "synthesized",
    id: str | None = None,
    title: str = "",
    kind: str = "synthesis",
    source: str = "synthesis",
) -> Item:
    """Build one derived Item from a set of input Items and a given ``statement``.

    A derived item is a new statement assembled or inferred from inputs, not a thing
    fetched directly, and the receipt says exactly that. The receipt's sha256 fingerprints
    the ``statement`` itself (the inference is a new statement, so it can only witness
    itself, not its sources), and ``derived_from`` records the content hash of each input,
    a re-checkable pointer into the corpus: given the inputs you can confirm the exact
    content the statement was built from is unaltered. ``method`` labels how direct the
    statement is ("synthesized" for an inferred claim, "compiled" for a verbatim assembly),
    so a derived item is never mistaken for a direct quote.

    Pure and deterministic: it records the statement it is given, it does not invent one.
    Raises ValueError on empty inputs (you cannot derive a statement from nothing).
    """
    if not inputs:
        raise ValueError("derive needs at least one input item: a statement from nothing is not derivable")
    derived_from = tuple(i.provenance.sha256 for i in inputs)
    return make_item(
        kind=kind,
        id=id or content_hash(statement)[:16],
        title=title or ref,
        text=statement,
        source=source,
        ref=ref,
        method=method,
        fetched_at=fetched_at,
        derived_from=derived_from,
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

    method = "compiled"

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

    The bridge from the Synthesizer seam to a receipted Item: the statement comes from the
    synthesizer, and the item is stamped with the synthesizer's own ``method`` (so the
    NullSynthesizer yields a ``compiled`` item and a model yields a ``synthesized`` one),
    with ``derived_from`` set to the inputs. The honesty is mechanical, not a promise.
    """
    statement = synth.synthesize(inputs, prompt)
    return derive(
        inputs, statement, fetched_at=fetched_at, ref=ref, id=id,
        title=title or prompt, method=synth.method, kind=kind,
    )
