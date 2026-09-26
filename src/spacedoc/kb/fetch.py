"""Download corpus files listed in a manifest and check their hashes."""

from __future__ import annotations

from pathlib import Path

import httpx

from spacedoc.kb.ingest import load_manifest, sha256_file


def fetch_corpus(manifest: Path, files_dir: Path, timeout_s: float = 120.0) -> list[str]:
    files_dir.mkdir(parents=True, exist_ok=True)
    report = []
    with httpx.Client(
        timeout=timeout_s,
        follow_redirects=True,
        headers={"User-Agent": "SpaceDoc-corpus-fetch/0.1 (research)"},
    ) as http:
        for meta in load_manifest(manifest):
            dest = files_dir / meta.file
            if dest.exists() and (not meta.sha256 or sha256_file(dest) == meta.sha256):
                report.append(f"ok       {meta.id} (already present)")
                continue
            if not meta.url:
                report.append(f"MISSING  {meta.id}: no URL; place {meta.file} manually")
                continue
            try:
                resp = http.get(meta.url)
                resp.raise_for_status()
            except httpx.HTTPError as e:
                report.append(f"FAILED   {meta.id}: {e}")
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(resp.content)
            if meta.sha256 and sha256_file(dest) != meta.sha256:
                report.append(
                    f"CHANGED  {meta.id}: downloaded file differs from the recorded sha256"
                )
            else:
                report.append(f"fetched  {meta.id}")
    return report
