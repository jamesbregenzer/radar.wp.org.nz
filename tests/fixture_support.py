from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch


@contextmanager
def ambiguous_collection_listing(
    root: Path,
    identity: str,
    query_slug: str,
):
    """Expose two real query artifacts to selection on every filesystem.

    A default macOS volume cannot store case-only filename variants in one
    directory. Keep both artifacts real, but control the collection directory's
    listing so selector behavior receives the same two-candidate input on
    case-sensitive and case-insensitive filesystems.
    """
    collection = root / "manual" / identity
    collection.mkdir(parents=True)
    candidates = []
    for name in ("candidate-a", "candidate-b"):
        candidate_dir = root / name
        candidate_dir.mkdir()
        candidate = candidate_dir / f"{query_slug}.csv"
        candidate.write_text("id,summary\n1,A\n", encoding="utf-8")
        candidates.append(candidate)

    original_iterdir = Path.iterdir

    def controlled_iterdir(path: Path):
        if path == collection:
            return iter((*candidates, *tuple(original_iterdir(path))))
        return original_iterdir(path)

    with patch.object(Path, "iterdir", controlled_iterdir):
        yield collection
