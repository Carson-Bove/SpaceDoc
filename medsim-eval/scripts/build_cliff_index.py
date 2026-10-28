"""Rebuild library/conditions/imm.conditions.json from NASA's IMM documentation page.

Reads the "All Documentation Per Condition" table, downloads every 2023 CLiFF (the most recent
list), and takes each condition's code and name from the PDF itself, because some link labels
on the page point at a different condition. Table 4 of each CLiFF (the treated/untreated,
best/worst case course) is parsed into numbers for the digital twin; these are unreviewed until
the physiologist checks them.

Needs `pdftotext` (poppler-utils) and network access. Usage:
    python medsim-eval/scripts/build_cliff_index.py [--cache DIR]
"""

from __future__ import annotations

import argparse
import concurrent.futures
import html
import json
import re
import subprocess
import urllib.request
from datetime import date
from pathlib import Path

PAGE = "https://www.nasa.gov/integrated-medical-model-documentation/"
OUT = Path(__file__).resolve().parents[1] / "library" / "conditions" / "imm.conditions.json"
UA = {"User-Agent": "Mozilla/5.0"}

VAL = r"(N/A|-?\d+(?:\.\d+)?(?:E-?\d+)?)"
CASES = {
    "TBC": "treated_best",
    "TWC": "treated_worst",
    "UTBC": "untreated_best",
    "UTWC": "untreated_worst",
}


def fetch(url: str) -> bytes:
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120).read()


def page_rows(text: str) -> list[dict]:
    """(category, cliff100, cliff119, peer review) per table row; links are (url, label)."""
    t = text[text.find("All Documentation Per Condition") :]
    t = t[: t.find("</table>")]
    rows, category = [], None
    for tr in re.findall(r"<tr>(.*?)</tr>", t, re.S):
        tds = re.findall(r"<td>(.*?)</td>", tr, re.S)
        if len(tds) < 5:
            continue
        c = re.sub("<[^>]+>", "", tds[0]).strip()
        if c:
            category = html.unescape(c)

        def link(td: str):
            m = re.search(r'href="([^"?=]+\.pdf)[^"]*"[^>]*>(.*?)</a>', td, re.S)
            return (
                (m.group(1), html.unescape(re.sub("<[^>]+>", "", m.group(2)).strip()))
                if m
                else None
            )

        rows.append(
            {
                "category": category,
                "c100": link(tds[2]),
                "c119": link(tds[3]),
                "review": link(tds[4]),
            }
        )
    return rows


def pdf_text(path: Path) -> str:
    return subprocess.run(
        ["pdftotext", "-layout", str(path), "-"], capture_output=True, text=True, check=True
    ).stdout


def code_and_name(text: str) -> tuple[str, str]:
    m = re.search(r"(ICL\d+[A-Z]?)_(.+?)(?:\s{2,}|\s+Cliff\b|$)", text, re.M)
    if not m:
        raise ValueError("no ICL code found")
    return m.group(1), re.sub(r"\s+", " ", m.group(2)).strip()


def num(s: str) -> float | None:
    return None if s == "N/A" else float(s)


def rng(a: str, b: str) -> list[float] | None:
    return None if "N/A" in (a, b) else [float(a), float(b)]


def course(text: str) -> dict | None:
    """Parse Table 4. Returns None if the table isn't in the expected shape."""
    start = text.find("TABLE 4.")
    end = text.find("TABLE 4 KEY", start)
    if start < 0 or end < 0:
        return None
    lines = text[start:end].splitlines()
    rows = [i for i, line in enumerate(lines) if re.match(r"^\s*(Treated|Untreated)\b", line)]
    out: dict = {}
    for n, i in enumerate(rows):
        block = lines[i : rows[n + 1] if n + 1 < len(rows) else len(lines)]
        abbr = re.search(r"\((U?T[BW]C)\)", " ".join(block))
        vals = re.findall(VAL, lines[i])
        if not abbr or len(vals) < 10:
            return None
        cp = vals[-10:]
        line = lines[i]
        prob = re.search(r"(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)", line)
        out[CASES[abbr.group(1)]] = {
            "probability_pct": [float(prob.group(1)), float(prob.group(2))]
            if prob and abbr.group(1) in ("TBC", "TWC")
            else None,
            "cp1_ti_pct": num(cp[0]),
            "cp1_hours": num(cp[1]),
            "cp2_ti_pct": num(cp[2]),
            "cp2_hours": rng(cp[3], cp[4]),
            "cp3_ti_pct": num(cp[5]),
            "rtdc_pct": rng(cp[6], cp[7]),
            "locl_pct": rng(cp[8], cp[9]),
        }
        if abbr.group(1) == "TBC":
            # The incidence column: text left of the probability, across the block's lines.
            col = prob.start() if prob else len(line)
            words = " ".join(b[:col] for b in block)
            words = re.sub(r"\b(Treated|Untreated|Best|Worst|Case)\b|\(TBC\)", " ", words)
            words = re.sub(r"\s+", " ", words).strip()
            means = re.findall(r"mean\s*[:=]?\s*(\d+(?:\.\d+)?(?:E-?\d+)?)", words, re.I)
            sds = re.findall(r"SD\s*[:=]?\s*(\d+(?:\.\d+)?(?:E-?\d+)?)", words, re.I)
            out["incidence_mean"] = float(means[0]) if means else None
            out["incidence_sd"] = float(sds[0]) if sds else None
            out["incidence_text"] = words or None
    if len(out) < 4:
        return None
    return out | {"extraction": "automatic", "reviewed_by": None}


def summary(text: str) -> str | None:
    """The CLiFF's opening description: the paragraph between the ICL title and the incidence data."""
    m = re.search(r"ICL\d+[A-Z]?_[^\n]*\n(.*?)\n\s*INCIDENCE DATA", text, re.S)
    if not m:
        return None
    para = re.sub(r"\s+", " ", m.group(1)).strip()
    return para or None


# Segment (CLiFF Table 1) -> where and when, in our five environments. EVAs happen at the ISS
# and on the lunar and Mars surfaces; space adaptation happens in the first days of microgravity.
SEGMENTS = {
    "All": (["T1", "T2", "T3", "T4", "T5"], "any", False),
    "EVA All": (["T1", "T3", "T5"], "any", True),
    "EVA Surface": (["T3", "T5"], "any", True),
    "EVA Habitat": (["T3", "T5"], "any", True),
    "Space Adaptation": (["T1", "T2", "T4"], "early_flight", False),
    "Surface": (["T3", "T5"], "any", False),
    "Gravity Well Transition": (["T3", "T5"], "surface_arrival", False),
}


def applicability(text: str, name: str) -> dict:
    start = text.find("TABLE 1. INCIDENCE MODEL")
    block = text[start : text.find("TABLE 2", start)] if start >= 0 else ""
    # One cell per line; drop page footers that land inside the table.
    cells = [c.strip() for c in block.splitlines() if c.strip() and "page:" not in c]

    def values(label: str) -> list[str]:
        return [cells[i + 1] for i, c in enumerate(cells) if c == label and i + 1 < len(cells)]

    segment = next(iter(values("Segment")), None)
    kind = next(iter(values("Incidence Type")), None)
    sexes = set(values("Sex"))
    envs, timing, eva = SEGMENTS.get(segment or "All", SEGMENTS["All"])
    if "lunar" in name.lower():
        envs = ["T3"]
    # A condition is sex-specific only when every incidence row names the same sex.
    sex = {"Female": "F", "Male": "M"}.get(next(iter(sexes)), "any") if len(sexes) == 1 else "any"
    out = {
        "incidence_type": kind,
        "segment": segment,
        "envs": envs,
        "timing": timing,
        "eva": eva,
        "sex": sex,
        "mapped": "automatic",
    }
    onset = re.search(
        r"Onset Timing \(Hours\).*?\(Min\):\s*([\d.]+).*?\(Max\):\s*([\d.]+)", block, re.S
    )
    if onset:
        out["onset_hours"] = [float(onset.group(1)), float(onset.group(2))]
        if out["onset_hours"][1] > 7 * 24:
            out["timing"] = "any"  # e.g. SANS develops over weeks to months, not on arrival
    return out


def slug(s: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", s.lower())).strip("-")


def tokens(s: str) -> set[str]:
    stop = {"cliff", "2023", "pdf", "peer", "review", "and", "the", "of", "to", "acute"}
    return {t for t in re.findall(r"[a-z0-9]+", s.lower()) if t not in stop}


def best_match(target: str, candidates: list[tuple[str, str]], floor: float = 0.5):
    """The candidate (url, label) whose url and label share the most words with target."""
    scored = []
    for url, label in candidates:
        cand = tokens(url.rsplit("/", 1)[-1]) | tokens(label)
        t = tokens(target)
        scored.append((len(t & cand) / max(1, len(t)), url, label))
    scored.sort(reverse=True)
    return scored[0] if scored and scored[0][0] >= floor else None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--cache", type=Path, default=Path(".cliff-cache"), help="Folder for downloaded PDFs"
    )
    args = ap.parse_args()
    args.cache.mkdir(parents=True, exist_ok=True)
    rows = page_rows(fetch(PAGE).decode("utf-8"))
    current = [(r["c119"], r["category"]) for r in rows if r["c119"]]
    legacy = [r["c100"] for r in rows if r["c100"]]
    reviews = [r["review"] for r in rows if r["review"]]

    def download(url: str) -> Path:
        path = args.cache / url.rsplit("/", 1)[-1]
        if not path.exists():
            path.write_bytes(fetch(url))
        return path

    with concurrent.futures.ThreadPoolExecutor(8) as ex:
        paths = list(ex.map(download, [c[0][0] for c in current]))

    conditions, unparsed, used_ids = [], [], set()
    for ((url, label), category), path in zip(current, paths, strict=True):
        text = pdf_text(path)
        icl, name = code_and_name(text)
        cid = slug(name)
        if cid in used_ids:
            cid = f"{cid}-{icl.lower()}"
        used_ids.add(cid)
        entry = {
            "cliff_id": cid,
            "icl": icl,
            "name": name,
            "category": category,
            "cliff": {"label": label, "url": url, "list": "cliff119_2023"},
        }
        old = best_match(name, legacy, floor=0.75)
        if old:
            entry["legacy"] = {"label": old[2], "url": old[1], "list": "cliff100"}
        rev = best_match(
            url.rsplit("/", 1)[-1].replace("-cliff-2023.pdf", "") + " " + name, reviews, floor=0.6
        )
        if rev:
            entry["peer_review"] = {"label": rev[2], "url": rev[1], "list": "cliff119_2023"}
        entry["summary"] = summary(text)
        entry["applicability"] = applicability(text, name)
        c = course(text)
        if c:
            entry["course"] = c
        else:
            unparsed.append(f"{icl} {name}")
        conditions.append(entry)
    conditions.sort(key=lambda e: (int(re.sub(r"\D", "", e["icl"])), e["icl"]))
    doc = {
        "schema_version": "0.1",
        "source_url": PAGE,
        "retrieved": date.today().isoformat(),
        "conditions": conditions,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        f"wrote {OUT}: {len(conditions)} conditions; Table 4 not parsed for {len(unparsed)}: {unparsed}"
    )


if __name__ == "__main__":
    main()
