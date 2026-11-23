"""Reading YAML for editing and writing it back without losing what a person wrote.

The hub and the validators read files with PyYAML and never write them. The studio does
write, and a file that comes back with its comments gone and its layout changed is a file
nobody wants to edit by hand again. `load` returns a structure that remembers comments,
key order, quoting and flow style; `save` writes it back.

What is guaranteed (and tested for every catalog and example file):
- the hub reads the same data from the saved file as from the original;
- every comment survives;
- saving a second time changes nothing.
What is not: byte-for-byte identity. The first save may normalise spacing.
"""

from __future__ import annotations

import io
from pathlib import Path

from ruamel.yaml import YAML


def _yaml() -> YAML:
    yaml = YAML(typ="rt")
    yaml.preserve_quotes = True         # "off" must stay quoted, or YAML 1.1 readers see a boolean
    yaml.width = 4096                   # never re-wrap a long line
    yaml.indent(mapping=2, sequence=4, offset=2)
    return yaml


def load(path: Path):
    """The document as an editable structure (dict-like and list-like, with comments attached)."""
    with open(path, encoding="utf-8") as handle:
        return _yaml().load(handle)


def loads(text: str):
    return _yaml().load(text)


def dumps(document) -> str:
    out = io.StringIO()
    _yaml().dump(document, out)
    return out.getvalue()


def save(document, path: Path) -> None:
    """Write through a temporary file, so a crash never leaves half a file where the hub will read it."""
    path = Path(path)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(dumps(document), encoding="utf-8", newline="\n")
    temporary.replace(path)
