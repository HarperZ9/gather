"""Source-checkout shim for module-mode Gather imports.

The package published from ``src/gather`` is the real implementation. This
shim lets source checkouts support host launchers such as
``python -m gather.cli`` without requiring an editable install first.
"""

from __future__ import annotations

from pathlib import Path

_SRC_PACKAGE = Path(__file__).resolve().parents[1] / "src" / "gather"
_SRC_INIT = _SRC_PACKAGE / "__init__.py"

if not _SRC_INIT.exists():
    raise ImportError(f"Gather source package not found at {_SRC_INIT}")

__path__ = [str(_SRC_PACKAGE)]
__file__ = str(_SRC_INIT)

exec(compile(_SRC_INIT.read_text(encoding="utf-8"), str(_SRC_INIT), "exec"), globals(), globals())
