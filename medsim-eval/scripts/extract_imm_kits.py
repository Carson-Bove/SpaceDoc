"""Rebuild library/sources/imm-medkits.json from two public IMM service-request reports.

  * Orion Medical Kit Contents (S-20180815-406), Table 2: the optimized Orion kits.
  * 2024 Lunar (S-20190528-412), Table 3: the ISS reference quantities, the volume-constrained
    Orion kit and the 7.5-day lunar kit, side by side.

Both tables list the same ~226 IMM resources in the same order. Table 2 has the cleanest names,
so its names are canonical and Table 3 rows are aligned to them.

Needs `pdftotext` (poppler-utils). Usage:
    python medsim-eval/scripts/extract_imm_kits.py [--pdf-dir DIR]
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import tempfile
import urllib.request
from datetime import date
from pathlib import Path

BASE = "https://www.nasa.gov/wp-content/uploads/2026/08/"
ORION = "orion-medical-kit-contents.pdf"
LUNAR = "2024-lunar.pdf"
OUT = Path(__file__).resolve().parents[1] / "library" / "sources" / "imm-medkits.json"

NUM = r"(\d+(?:\.\d+)?(?: \(\d+\))?)"
FOOTER = re.compile(r"^\d+\s+\d+ [A-Z]+ \d{4}$")

# Resources that are treatments rather than things, in the IMM's list.
INTERVENTIONS = {"PSYCHOTHERAPY", "HEIMLICH MANEUVER"}
DRUG = re.compile(
    r"\b(\d+(\.\d+)? ?(MG|MCG|GM)\b|MG/ML|TABLETS?|CAPSULES?|INJECTABLE|INHALER|OINTMENT|CREAM|"
    r"DROPS|SPRAY|UNITS/GM|EPIPEN|ADRENALINE|ATROPINE|KETAMINE|LIDOCAINE|CYCLOPENTOLATE|TROPICAMIDE|"
    r"FLUORESCEIN|SILVER NITRATE|BENZOCAINE|EUGENOL|ERTAPENEM|ROCEPHIN|DEBROX|AFRIN|CIPRODEX|"
    r"TOBRAMYCIN|MOXIFLOXACIN|REFRESH|ZIPRASIDONE|ABILIFY|VALIUM|DILAUDID|ROBINUL|PROMETHAZINE)",
    re.I,
)
NOT_DRUG = re.compile(
    r"\b(SYRINGE \(|ADHESIVE \(|DERMABOND|ULTRASOUND GEL|ILMA SYRINGE|LIDOCAINE JELLY)", re.I
)
FLUID = re.compile(r"^(IV FLUID|STERILE WATER|WATER$)", re.I)


def category(name: str) -> str:
    if name in INTERVENTIONS:
        return "intervention"
    if FLUID.search(name):
        return "fluid"
    if name.startswith("LIDOCAINE JELLY"):
        return "drug"
    if DRUG.search(name) and not NOT_DRUG.search(name):
        return "drug"
    return "equipment"


def text_of(pdf: Path) -> list[str]:
    out = subprocess.run(
        ["pdftotext", "-layout", str(pdf), "-"], capture_output=True, text=True, check=True
    )
    return out.stdout.splitlines()


def clean(name: str) -> str:
    return re.sub(r"\s+", " ", name.replace("–", "-")).strip()


def orion_table(lines: list[str]) -> list[list[str]]:
    """Rows of [name, mass-only qty, mass+volume qty] from Table 2."""
    start = next(
        i for i, line in enumerate(lines) if line.strip().startswith("Table 2: Generated optimized")
    )
    rows, pending = [], ""
    for line in lines[start + 8 :]:
        s = line.strip()
        if not s or "IMM Service Request" in s or FOOTER.match(re.sub(r"\s+", " ", s)):
            continue
        if s.startswith(("Table 3", "Results")):
            break
        m = re.match(r"^(.*?)\s{2,}" + NUM + r"\s{2,}" + NUM + r"\s*$", s)
        n = re.match(r"^" + NUM + r"\s{2,}" + NUM + r"$", s)
        if m:
            rows.append([clean(f"{pending} {m.group(1)}"), m.group(2), m.group(3)])
            pending = ""
        elif n:
            rows.append([pending, n.group(1), n.group(2)])
            pending = "\0"  # the next text line continues this row's name
        elif pending == "\0" and rows:
            rows[-1][0] = clean(f"{rows[-1][0]} {s}")
            pending = ""
        else:
            pending = clean(f"{pending} {s}")
    return rows


def lunar_table(lines: list[str]) -> list[tuple[str, list[str]]]:
    """Rows of (name fragment, [ISS, S-406 optimized, 7.5-day lunar]) from Table 3."""
    start = next(
        i for i, line in enumerate(lines) if line.strip().startswith("Table 3: The ISS medical kit")
    )
    end = next(
        i for i, line in enumerate(lines) if i > start and line.strip().startswith("Table 4")
    )
    rows: list[tuple[str, list[str]]] = []
    pending = ""
    for line in lines[start + 1 : end]:
        s = line.strip()
        if (
            not s
            or "IMM Service Request" in s
            or FOOTER.match(re.sub(r"\s+", " ", s))
            or s == "Resource"
        ):
            continue
        if re.search(r"Quantity|\(Reference\)|Optimized", s):
            pending = ""  # column headers repeated on a new page
            continue
        m = re.match(r"^(.*?\S)\s{2,}" + NUM + r"\s+" + NUM + r"\s+" + NUM + r"$", s)
        n = re.match(r"^" + NUM + r"\s+" + NUM + r"\s+" + NUM + r"$", s)
        if m:
            rows.append((clean(f"{pending} {m.group(1)}"), [m.group(2), m.group(3), m.group(4)]))
            pending = ""
        elif n:
            rows.append((pending, [n.group(1), n.group(2), n.group(3)]))
            pending = ""
        else:
            pending = clean(f"{pending} {s}")
    return rows


def tokens(s: str) -> set[str]:
    return set(re.findall(r"[A-Z0-9]+", s.upper()))


def align(canon: list[str], rows: list[tuple[str, list[str]]]) -> dict[str, list[str]]:
    """Match each Table 3 row to the nearest canonical name ahead of the last match."""
    out: dict[str, list[str]] = {}
    j = 0
    for name, qty in rows:
        window = range(j, min(len(canon), j + 4))
        best = max(
            window,
            key=lambda k: (
                len(tokens(name) & tokens(canon[k])) / max(1, len(tokens(name) | tokens(canon[k])))
            ),
        )
        if canon[best] not in out:
            out[canon[best]] = qty
        j = best + 1
    return out


def qty(cell: str | None) -> dict | None:
    """'0.85 (1)' -> {'qty': 1, 'optimizer': 0.85}; '12' -> {'qty': 12}."""
    if cell is None:
        return None
    m = re.match(r"^(\d+(?:\.\d+)?)(?: \((\d+)\))?$", cell)
    raw = float(m.group(1))
    if m.group(2):
        return {"qty": int(m.group(2)), "optimizer": raw}
    return {"qty": int(raw) if raw.is_integer() else raw}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf-dir", type=Path, help="Folder that already holds the two PDFs")
    args = ap.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        folder = args.pdf_dir or Path(tmp)
        for name in (ORION, LUNAR):
            if not (folder / name).exists():
                req = urllib.request.Request(BASE + name, headers={"User-Agent": "Mozilla/5.0"})
                (folder / name).write_bytes(urllib.request.urlopen(req, timeout=60).read())
        orion = orion_table(text_of(folder / ORION))
        lunar = align([r[0] for r in orion], lunar_table(text_of(folder / LUNAR)))
    missing = [r[0] for r in orion if r[0] not in lunar]
    resources = []
    for name, mass_only, mass_vol in orion:
        iss, s406, lunar75 = lunar.get(name, [None, None, None])
        if s406 is not None and qty(s406) != qty(mass_vol):
            raise SystemExit(
                f"tables disagree on the S-406 volume-constrained kit for {name!r}: {s406} vs {mass_vol}"
            )
        resources.append(
            {
                "name": name,
                "category": category(name),
                "iss": qty(iss),
                "orion_mass_only": qty(mass_only),
                "orion_mass_volume": qty(mass_vol),
                "lunar_7_5d": qty(lunar75),
            }
        )
    doc = {
        "retrieved": date.today().isoformat(),
        "sources": {
            "orion_mass_only": "IMM SR S-20180815-406 (Orion Medical Kit Contents), Table 2: 20 lb, no volume limit; ~9.25 kg, 23,594 cm3",
            "orion_mass_volume": "IMM SR S-20180815-406, Table 2: 20 lb and 13,721 cm3 limits; ~7.75 kg, 13,895 cm3",
            "iss": "IMM SR S-20190528-412 (2024 Lunar), Table 3: ISS quantity (reference)",
            "lunar_7_5d": "IMM SR S-20190528-412, Table 3: 7.5-day lunar optimized kit; 2.37 kg, 6,430 cm3",
            "url": "https://www.nasa.gov/integrated-medical-model-documentation/",
        },
        "note": "Quantities are IMM modelling inputs and optimizer outputs, not flight manifests. "
        "Decimal optimizer values were rounded up by NASA for simulation; 'optimizer' keeps the raw value.",
        "unaligned": missing,
        "resources": resources,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        f"wrote {OUT}: {len(resources)} resources, {len(missing)} without ISS/lunar quantities: {missing}"
    )


if __name__ == "__main__":
    main()
