from __future__ import annotations

import subprocess

from gather.item import Item

DEFAULT_MAX_INPUT_CHARS = 8000
DEFAULT_MAX_INPUTS = 50  # cap the fan-in so a large corpus cannot build an unbounded model prompt


def build_prompt(
    inputs: list[Item], prompt: str, *,
    max_chars: int = DEFAULT_MAX_INPUT_CHARS, max_inputs: int = DEFAULT_MAX_INPUTS,
) -> str:
    """Assemble the text handed to a model: the instruction, then each input bounded to ``max_chars``.
    At most ``max_inputs`` inputs are included (the prompt notes any omitted, never silently), so the
    total prompt is bounded by ``max_inputs * max_chars``. Pure and deterministic; preserves order."""
    parts = [prompt.strip()] if prompt.strip() else []
    parts.append("Sources:")
    for it in inputs[:max_inputs]:
        head = it.title.strip() or f"{it.provenance.source}:{it.id}"
        parts.append(f"- {head}: {it.text.strip()[:max_chars]}")
    if len(inputs) > max_inputs:
        parts.append(f"... and {len(inputs) - max_inputs} more input(s) omitted (cap {max_inputs})")
    return "\n".join(parts)


class SubprocessSynthesizer:
    """The model edge for the Synthesizer seam: shells to a configured CLI to infer a statement.

    This is the real synthesis path the seam was built for (the default NullSynthesizer only
    compiles). It satisfies the ``Synthesizer`` protocol with ``method="synthesized"``, so
    ``synthesize_item`` stamps its output a synthesis with ``derived_from`` set to the inputs, and
    the digest seal records the inference honestly.

    What ``synthesized`` attests is precisely that the configured edge produced this text, the same
    trust class as choosing the ``browser`` binary or the API ``auth_env``: that the edge is
    actually a model is the operator's responsibility. Point this at ``cat`` and you will get a
    verbatim echo wearing a ``synthesized`` receipt. The guarantee the method ladder enforces is
    only that a bare ``derive`` call cannot forge a synthesis; the seam does not verify the edge.

    ``derived_from`` records the inputs supplied to the edge, an upper bound on provenance: a model
    may ignore some inputs or generate beyond them, so the chain attests availability, not use.

    The command is operator-configured (e.g. ``["llm", "-m", "some-model"]``). The prompt, which is
    built from gathered (possibly untrusted) content, is written to the process's STDIN, never the
    argv, so no gathered text can be parsed as a flag. fetch-time only; needs the CLI on PATH.
    """

    method = "synthesized"

    def __init__(self, command: list[str], *, timeout: float = 120.0,
                 max_input_chars: int = DEFAULT_MAX_INPUT_CHARS,
                 max_inputs: int = DEFAULT_MAX_INPUTS) -> None:
        if not command:
            raise ValueError("SubprocessSynthesizer needs a non-empty command")
        self._command = list(command)
        self._timeout = timeout
        self._max_input_chars = max_input_chars
        self._max_inputs = max_inputs

    def synthesize(self, inputs: list[Item], prompt: str) -> str:
        body = build_prompt(inputs, prompt, max_chars=self._max_input_chars, max_inputs=self._max_inputs)
        proc = subprocess.run(
            self._command, input=body.encode("utf-8"), capture_output=True, timeout=self._timeout,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"synthesizer failed: {proc.stderr.decode('utf-8', 'replace').strip()[:200]}")
        statement = proc.stdout.decode("utf-8", "replace").strip()
        if not statement:
            raise RuntimeError("synthesizer produced no output")
        return statement
