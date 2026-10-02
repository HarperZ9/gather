"""Select the package files the client server can import, starting from serve.py.

The scan reads every import statement in each module, including imports inside
functions and relative imports, so a module that a call path can reach is kept
even if a plain launch never loads it. Package __init__ files of every kept
module are kept, and so are non-Python files in kept package folders, which
covers data a module loads at runtime.
"""
import ast
from pathlib import Path


def _module_file(src, name):
    path = src.joinpath(*name.split("."))
    if (path / "__init__.py").is_file():
        return path / "__init__.py"
    if path.with_suffix(".py").is_file():
        return path.with_suffix(".py")
    return None


def imported_names(source, package=""):
    """Absolute module names one file imports, at any depth in the file."""
    names = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                parts = package.split(".")
                anchor = parts[:len(parts) - node.level + 1]
                base = ".".join(anchor + ([base] if base else []))
            names.add(base)
            names.update(base + "." + alias.name for alias in node.names)
    return names


def closure(src, entry_source, package):
    """Relative paths under ``src`` reachable from the entry file's imports of ``package``."""
    src = Path(src)
    inside = lambda name: name == package or name.startswith(package + ".")  # noqa: E731
    todo = sorted(n for n in imported_names(entry_source) if inside(n))
    seen, files = set(), set()
    while todo:
        name = todo.pop()
        path = _module_file(src, name)
        if path is None or name in seen:
            continue
        seen.add(name)
        files.add(path)
        parts = name.split(".")
        todo.extend(".".join(parts[:i]) for i in range(1, len(parts)))
        owner = name if path.name == "__init__.py" else name.rpartition(".")[0]
        todo.extend(n for n in imported_names(path.read_bytes(), owner) if inside(n))
    folders = {path.parent for path in files}
    for folder in folders:
        files.update(p for p in folder.iterdir() if p.is_file() and p.suffix not in {".py", ".pyc", ".pyo"})
    return sorted(path.relative_to(src).as_posix() for path in files)
