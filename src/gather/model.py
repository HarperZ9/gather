from __future__ import annotations

import subprocess

from gather.item import Item

DEFAULT_MAX_INPUT_CHARS = 8000


def build_prompt(inputs: list[Item], prompt: str, *, max_chars: int = DEFAULT_MAX_INPUT_CHARS) -> str:
    """Assemble the text handed to a model: the instruction, then each input bounded to ``max_chars``.
    Pure and deterministic; preserves input order."""
    parts = [prompt.strip()] if prompt.strip() else []
    parts.append("Sources:")
    for it in inputs:
        head = it.title.strip() or f"{it.provenance.source}:{it.id}"
        parts.append(f"- {head}: {it.text.strip()[:max_chars]}")
    return "\n".join(parts)


class SubprocessSynthesizer:
    """The model edge for the Synthesizer seam: shells to a model CLI to infer a statement.

    This is the real synthesis path the seam was built for (the default NullSynthesizer only
    compiles). It satisfies the ``Synthesizer`` protocol with ``method="synthesized"``, so
    ``synthesize_item`` stamps its output a synthesis with ``derived_from`` set to the inputs, and
    the digest seal records the inference honestly.

    The command is operator-configured (e.g. ``["llm", "-m", "some-model"]``). The prompt, which is
    built from gathered (possibly untrusted) content, is written to the process's STDIN, never the
    argv, so no gathered text can be parsed as a flag. fetch-time only; needs the model CLI on PATH.
    """

    method = "synthesized"

    def __init__(self, command: list[str], *, timeout: float = 120.0,
                 max_input_chars: int = DEFAULT_MAX_INPUT_CHARS) -> None:
        if not command:
            raise ValueError("SubprocessSynthesizer needs a non-empty command")
        self._command = list(command)
        self._timeout = timeout
        self._max_input_chars = max_input_chars

    def synthesize(self, inputs: list[Item], prompt: str) -> str:
        body = build_prompt(inputs, prompt, max_chars=self._max_input_chars)
        proc = subprocess.run(
            self._command, input=body.encode("utf-8"), capture_output=True, timeout=self._timeout,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"synthesizer failed: {proc.stderr.decode('utf-8', 'replace').strip()[:200]}")
        statement = proc.stdout.decode("utf-8", "replace").strip()
        if not statement:
            raise RuntimeError("synthesizer produced no output")
        return statement
