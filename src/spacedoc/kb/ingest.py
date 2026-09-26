"""Turn source documents into metadata-rich chunks (component C-03, ingestion side).

Each source is described in corpus/manifest.yaml; see docs/04 §2.2 for the fields.
"""

from __future__ import annotations

import hashlib
import re
from html.parser import HTMLParser
from pathlib import Path

import yaml
from pydantic import BaseModel


class SourceMeta(BaseModel):
    id: str
    title: str
    file: str  # path relative to the manifest's files directory
    url: str | None = None
    sha256: str | None = None
    license: str = "unknown"
    tier: str = "C"  # A mission, B space-medicine evidence, C general clinical, D textbook
    environment_tags: list[str] = []
    topic_tags: list[str] = []
    published: str | None = None
    notes: str = ""


class Chunk(BaseModel):
    chunk_id: str
    source_id: str
    title: str
    text: str
    page: int | None = None
    tier: str = "C"
    environment_tags: list[str] = []
    topic_tags: list[str] = []
    url: str | None = None
    license: str = "unknown"


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "nav", "header", "footer"}:
            self._skip += 1

    def handle_endtag(self, tag):
        if tag in {"script", "style", "nav", "header", "footer"} and self._skip:
            self._skip -= 1
        if tag in {"p", "li", "h1", "h2", "h3", "h4", "tr", "div", "br"}:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def extract_pages(path: Path) -> list[tuple[int | None, str]]:
    """Return (page_number, text) pairs. Non-PDF files are a single page (None)."""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        return [(i + 1, page.extract_text() or "") for i, page in enumerate(reader.pages)]
    text = path.read_text(encoding="utf-8", errors="replace")
    if suffix in {".html", ".htm"}:
        parser = _TextExtractor()
        parser.feed(text)
        text = "".join(parser.parts)
    return [(None, text)]


def _clean(text: str) -> str:
    text = re.sub(r"-\n(\w)", r"\1", text)  # re-join hyphenated line breaks
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def chunk_words(text: str, size: int = 350, overlap: int = 60) -> list[str]:
    """Split into overlapping windows of ~size words.

    Overlap keeps a sentence that straddles a boundary retrievable from either side.
    """
    words = text.split()
    if not words:
        return []
    step = max(size - overlap, 1)
    return [" ".join(words[i : i + size]) for i in range(0, max(len(words) - overlap, 1), step)]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def load_manifest(manifest_path: Path) -> list[SourceMeta]:
    raw = yaml.safe_load(manifest_path.read_text()) or {}
    return [SourceMeta(**s) for s in raw.get("sources", [])]


def chunk_source(meta: SourceMeta, files_dir: Path, verify_hash: bool = True) -> list[Chunk]:
    path = files_dir / meta.file
    if not path.exists():
        raise FileNotFoundError(f"{meta.id}: {path} not found (run `spacedoc corpus fetch`?)")
    if verify_hash and meta.sha256 and sha256_file(path) != meta.sha256:
        raise ValueError(f"{meta.id}: sha256 mismatch for {path}; the file changed")
    chunks: list[Chunk] = []
    for page, text in extract_pages(path):
        for piece in chunk_words(_clean(text)):
            chunks.append(
                Chunk(
                    chunk_id=f"{meta.id}#{len(chunks):04d}",
                    source_id=meta.id,
                    title=meta.title,
                    text=piece,
                    page=page,
                    tier=meta.tier,
                    environment_tags=meta.environment_tags,
                    topic_tags=meta.topic_tags,
                    url=meta.url,
                    license=meta.license,
                )
            )
    return chunks
