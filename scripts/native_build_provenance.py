"""Record frozen native dependency origins and reject ambient DLL collection."""
import ast
import hashlib
from pathlib import Path


def dependencies(toc, runtime):
    root = Path(runtime).resolve(strict=True)
    records = []

    def visit(value):
        if isinstance(value, (tuple, list)):
            if (len(value) == 3 and isinstance(value[2], str)
                    and value[2] in ('BINARY', 'EXTENSION')):
                name, source, kind = value
                path = Path(source).resolve(strict=True)
                if root not in path.parents:
                    raise ValueError(f'native dependency outside Python runtime: {name}')
                records.append({'name': name, 'kind': kind, 'source': str(path),
                                'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
            else:
                for item in value:
                    visit(item)

    visit(ast.literal_eval(Path(toc).read_text(encoding='utf-8')))
    if not records:
        raise ValueError('native dependency inventory is empty')
    return sorted(records, key=lambda row: row['name'])
