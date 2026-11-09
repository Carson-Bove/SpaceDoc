"""Printable scoring sheet: a PDF a rater fills in by pen while reading one run's transcript.

`medsim sheet` writes a blank sheet for any scenario, or one pre-filled from a scenario and its
rubric. It follows the four layers of docs/11 §5: critical errors, checklist (with the base
rubric's standard items), global ratings and outcome. Needs the optional `pdf` extra (reportlab).
"""

from __future__ import annotations

import html
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    Flowable,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from medsim_eval.models import BaseRubric, Scenario, ScenarioRubric
from medsim_eval.models.condition import Condition
from medsim_eval.models.crew import CrewTwin

INK = colors.HexColor("#1F2328")
HEAD = colors.HexColor("#2E3A42")
MUTED = colors.HexColor("#56636D")
TINT = colors.HexColor("#EDF0F2")
RULE = colors.HexColor("#8796A3")

S = {
    "title": ParagraphStyle(
        "title", fontName="Helvetica-Bold", fontSize=17, leading=21, textColor=HEAD
    ),
    "sub": ParagraphStyle(
        "sub", fontName="Helvetica", fontSize=10, leading=13, textColor=MUTED, spaceAfter=6
    ),
    "h": ParagraphStyle(
        "h",
        fontName="Helvetica-Bold",
        fontSize=12,
        leading=15,
        textColor=HEAD,
        spaceBefore=10,
        spaceAfter=3,
    ),
    "note": ParagraphStyle(
        "note", fontName="Helvetica", fontSize=8.5, leading=11, textColor=MUTED, spaceAfter=4
    ),
    "cell": ParagraphStyle("cell", fontName="Helvetica", fontSize=9, leading=11.5, textColor=INK),
    "small": ParagraphStyle(
        "small", fontName="Helvetica", fontSize=7.5, leading=9.5, textColor=MUTED
    ),
    "cellb": ParagraphStyle(
        "cellb", fontName="Helvetica-Bold", fontSize=9, leading=11.5, textColor=INK
    ),
    "th": ParagraphStyle(
        "th", fontName="Helvetica-Bold", fontSize=8, leading=10, textColor=colors.white
    ),
}

# The built-in PDF fonts cover Latin-1 and a few extras; map the rest to plain text.
_PLAIN = {"−": "-", "→": "->", "≤": "<=", "≥": ">=", "≈": "~", "κ": "kappa", "₂": "2", "⁹": "9"}


def _t(text: object) -> str:
    s = str(text)
    for a, b in _PLAIN.items():
        s = s.replace(a, b)
    return html.escape(s, quote=False)


def P(text: object, style: str = "cell") -> Paragraph:
    return Paragraph(_t(text), S[style])


def PM(markup: str, style: str = "cell") -> Paragraph:
    """A paragraph whose markup is already safe (built here, not from file content)."""
    return Paragraph(markup, S[style])


class Choices(Flowable):
    """Tick boxes with labels, drawn so they print cleanly: [ ] Done  [ ] Not done."""

    def __init__(self, labels: list[str], size: float = 8, gap: float = 6, font_size: float = 7.5):
        super().__init__()
        self.labels, self.size, self.gap, self.font_size = labels, size, gap, font_size

    def wrap(self, aw, ah):
        self.width = aw
        return aw, self.size + 2

    def draw(self):
        c, x = self.canv, 0
        c.setLineWidth(0.7)
        c.setStrokeColor(INK)
        c.setFont("Helvetica", self.font_size)
        for label in self.labels:
            c.rect(x, 1, self.size, self.size)
            c.setFillColor(INK)
            c.drawString(x + self.size + 2, 2, label)
            x += self.size + 4 + c.stringWidth(label, "Helvetica", self.font_size) + self.gap


class Circles(Flowable):
    """Numbers in circles for a 1-5 rating: the rater circles one."""

    def __init__(self, values=(1, 2, 3, 4, 5), r: float = 6.5, gap: float = 6):
        super().__init__()
        self.values, self.r, self.gap = values, r, gap

    def wrap(self, aw, ah):
        return len(self.values) * (2 * self.r + self.gap), 2 * self.r + 2

    def draw(self):
        c = self.canv
        c.setLineWidth(0.7)
        c.setStrokeColor(INK)
        c.setFont("Helvetica-Bold", 8)
        for i, v in enumerate(self.values):
            cx = self.r + i * (2 * self.r + self.gap)
            c.circle(cx, self.r + 1, self.r)
            c.drawCentredString(cx, self.r - 1.8, str(v))


def _table(rows, widths, header=True, zebra=True, pad=3):
    t = Table(rows, colWidths=widths, repeatRows=1 if header else 0)
    style = [
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), pad),
        ("BOTTOMPADDING", (0, 0), (-1, -1), pad + 1),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, RULE),
    ]
    if header:
        style += [("BACKGROUND", (0, 0), (-1, 0), HEAD)]
    if zebra:
        style += [("ROWBACKGROUNDS", (0, 1 if header else 0), (-1, -1), [colors.white, TINT])]
    t.setStyle(TableStyle(style))
    return t


def _fields(pairs, widths):
    """Label + blank line to write on, laid out in a grid."""
    rows = [[x for label, w in row for x in (PM(f"<b>{label}</b>"), "")] for row in pairs]
    t = Table(rows, colWidths=widths)
    style = [
        ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
    ]
    for r, row in enumerate(pairs):
        for i in range(len(row)):
            style.append(("LINEBELOW", (2 * i + 1, r), (2 * i + 1, r), 0.6, INK))
    t.setStyle(TableStyle(style))
    return t


def build_sheet(
    out: Path,
    base: BaseRubric,
    scenario: Scenario | None = None,
    rubric: ScenarioRubric | None = None,
    conditions: dict[str, Condition] | None = None,
    crew: dict[str, CrewTwin] | None = None,
    blank_rows: int = 8,
) -> Path:
    conditions, crew = conditions or {}, crew or {}
    sid = scenario.scenario_id if scenario else "any scenario"
    W = letter[0] - 1.2 * inch

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(MUTED)
        canvas.drawString(
            doc.leftMargin,
            0.4 * inch,
            f"MedSim Eval scoring sheet · {sid} · base rubric {base.ref}",
        )
        canvas.drawRightString(letter[0] - doc.rightMargin, 0.4 * inch, f"Page {doc.page}")
        canvas.restoreState()

    doc = SimpleDocTemplate(
        str(out),
        pagesize=letter,
        leftMargin=0.6 * inch,
        rightMargin=0.6 * inch,
        topMargin=0.55 * inch,
        bottomMargin=0.65 * inch,
        title=f"Scoring sheet: {sid}",
        author="MedSim Eval",
    )
    story: list = []

    # ---------- header ----------
    if scenario:
        story.append(P(f"Scoring sheet · {scenario.scenario_id}: {scenario.title}", "title"))
    else:
        story.append(P("Scoring sheet · blank, for any scenario", "title"))
    story.append(
        P(f"Score one run from its transcript. Base rubric {base.ref} ({base.status}).", "sub")
    )
    story.append(
        _fields(
            [
                [("Rater", 0), ("Date", 0)],
                [("Assistant and version", 0), ("Run ID / seed", 0)],
                [
                    ("Transcript or log file", 0),
                    ("Scenario ID", 0) if not scenario else ("Run length", 0),
                ],
            ],
            [1.3 * inch, 2.35 * inch, 1.3 * inch, 2.35 * inch],
        )
    )
    story.append(Spacer(1, 6))
    env_course = Table(
        [
            [
                PM("<b>Environment</b>"),
                Choices(
                    [
                        "T1 LEO",
                        "T2 Cislunar",
                        "T3 Lunar surface",
                        "T4 Mars transit",
                        "T5 Mars surface",
                    ]
                ),
            ],
            [
                PM("<b>Course</b>"),
                Choices(["Best", "Worst", "CLiFF odds", "Manual / hand-run"]),
            ],
        ],
        colWidths=[1.3 * inch, W - 1.3 * inch],
    )
    env_course.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 2),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.append(env_course)
    story.append(
        P(
            "How to score: tick one box per item from the transcript alone. Under Evidence, write the turn number "
            "or simulated time that shows it. Leave an item N/A only where the sheet says it may be "
            "(equipment not aboard, or a complication that did not occur).",
            "note",
        )
    )

    # ---------- scenario at a glance ----------
    if scenario:
        p = scenario.patients[0]
        cond = conditions.get(p.condition)
        twin = crew.get(p.crew_id)
        speaker = crew.get(scenario.speaker.crew_id)
        g = p.ground_truth
        role = {"patient": "the patient", "cmo": "the CMO", "crew": "a bystander crewmember"}[
            scenario.speaker.role
        ]
        lines = [
            (
                "Patient",
                f"{twin.name}, {twin.sex}, {twin.age} ({p.crew_id})" if twin else p.crew_id,
            ),
            (
                "Presented by",
                f"{speaker.name if speaker else scenario.speaker.crew_id}, {role}; "
                f"historian reliability {scenario.speaker.input_quality}/5",
            ),
            ("Diagnosis", g.diagnosis or (cond.name if cond else p.condition)),
            ("Etiology", g.etiology),
        ]
        if g.synonyms:
            lines.append(
                (
                    "Accepted wording",
                    "; ".join(f"{k}: {', '.join(v)}" for k, v in g.synonyms.items()),
                )
            )
        if g.differential:
            lines.append(("Differential", ", ".join(g.differential)))
        if g.must_not_miss:
            lines.append(("Can't-miss", ", ".join(g.must_not_miss)))
        for tc in p.time_critical:
            lines.append(
                ("Time-critical", f"{tc.action.text or ', '.join(tc.action.refs)} by {tc.by}")
            )
        for x in p.complications:
            lines.append((f"Complication {x.id}", f"{x.name}: {_trigger(x)}"))
        if scenario.complicators:
            lines.append(("Complicating factors", scenario.complicators))
        box = _table(
            [[P(k, "cellb"), P(v)] for k, v in lines],
            [1.35 * inch, W - 1.35 * inch],
            header=False,
            pad=2,
        )
        story += [P("Scenario at a glance", "h"), box]

    # ---------- A. critical errors ----------
    gates = list(base.gates) + (list(rubric.gates) if rubric else [])
    rows = [
        [PM("ID", "th"), PM("Critical error", "th"), PM("Occurred?", "th"), PM("Evidence", "th")]
    ]
    rows += [[P(g.id, "cellb"), P(g.text), Choices(["No", "Yes"]), ""] for g in gates]
    if not rubric:
        rows += [
            [
                "",
                P("Scenario-specific (from the scenario's rubric):", "small"),
                Choices(["No", "Yes"]),
                "",
            ]
            for _ in range(2)
        ]
    story.append(
        KeepTogether(
            [
                P("A. Critical errors: any one fails the run", "h"),
                _table(rows, [0.45 * inch, W - 2.85 * inch, 1.1 * inch, 1.3 * inch]),
            ]
        )
    )

    # ---------- B. checklist ----------
    story.append(P("B. Checklist", "h"))
    story.append(
        P(
            "Standard items are scored in every scenario. Complication items are scored only in runs where "
            "that complication occurred; their deadlines count from its onset. Weights: + expected action, "
            "- error (tick Done if the error happened).",
            "note",
        )
    )
    cw = [0.45 * inch, W - 4.1 * inch, 0.4 * inch, 0.85 * inch, 1.5 * inch, 0.9 * inch]
    hdr = [
        PM("ID", "th"),
        PM("Observable behaviour", "th"),
        PM("Wt", "th"),
        PM("Deadline", "th"),
        PM("Result", "th"),
        PM("Evidence", "th"),
    ]
    done = ["Done", "Not done", "N/A"]

    std = [s for s in base.standard_items if s.scope == "scenario"]
    cx_std = [s for s in base.standard_items if s.scope == "complication"]
    rows = [hdr]
    for s in std:
        text = s.text + (f" (only if {s.depends_on} is done)" if s.depends_on else "")
        rows.append(
            [P(s.id, "cellb"), P(text), P(f"+{s.weight}"), "", Choices(["Done", "Not done"]), ""]
        )
    story.append(_table(rows, cw))

    complications = scenario.patients[0].complications if scenario else []
    cx_list = [(x.id, x.name, x.recognise_within) for x in complications] or [
        ("X__", "", None),
        ("X__", "", None),
    ]
    for cid, name, window in cx_list:
        label = f"Complication {cid}" + (
            f": {name}" if name else ":  ______________________________"
        )
        occurred = Table(
            [
                [
                    P(label, "cellb"),
                    Choices(["Did not occur", "Occurred"]),
                    PM("<b>Onset</b> ________"),
                ]
            ],
            colWidths=[W - 3.4 * inch, 2.0 * inch, 1.4 * inch],
        )
        occurred.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 4),
                    ("BACKGROUND", (0, 0), (-1, -1), TINT),
                ]
            )
        )
        rows = [hdr]
        for s in cx_std:
            due = f"onset + {window}" if (window and s.id == "SCR") else ""
            rows.append([P(s.id, "cellb"), P(s.text), P(f"+{s.weight}"), P(due), Choices(done), ""])
        if rubric:
            for it in [i for i in rubric.items if i.complication == cid]:
                rows.append(_item_row(it, done))
        else:
            rows += [
                ["", P("Item tied to this complication:", "small"), "", "", Choices(done), ""]
                for _ in range(2)
            ]
        story.append(KeepTogether([Spacer(1, 4), occurred, _table(rows, cw)]))

    rows = [hdr]
    if rubric:
        for it in [i for i in rubric.items if not i.complication]:
            rows.append(_item_row(it, done))
            if it.type == "rating" and it.anchors:
                rows.append(
                    [
                        "",
                        P(
                            f"1: {it.anchors.one}  ·  3: {it.anchors.three}  ·  5: {it.anchors.five}",
                            "small",
                        ),
                        "",
                        "",
                        "",
                        "",
                    ]
                )
    else:
        rows += [["", "", "", "", Choices(done), ""] for _ in range(blank_rows)]
    story.append(Spacer(1, 4))
    story.append(
        P(
            "Scenario checklist items"
            + (
                ""
                if rubric
                else ": copy each item, its weight and deadline from the scenario's rubric"
            ),
            "cellb",
        )
    )
    story.append(_table(rows, cw, pad=3 if rubric else 7))

    if rubric is None or rubric.must_not_miss_tested:
        mnm = scenario.patients[0].ground_truth.must_not_miss if scenario else []
        rows = [[PM("Can't-miss diagnosis", "th"), PM("Result", "th"), PM("Evidence", "th")]]
        rows += [
            [P(d), Choices(["Considered or excluded", "Not addressed"]), ""]
            for d in (mnm or ["", ""])
        ]
        story.append(Spacer(1, 6))
        story.append(_table(rows, [W - 4.0 * inch, 2.7 * inch, 1.3 * inch], pad=3 if mnm else 7))

    story.append(Spacer(1, 6))
    story.append(
        KeepTogether(
            [
                P("Checklist score", "cellb"),
                _fields(
                    [
                        [
                            ("P: weights of expected items done", 0),
                            ("N: weights of errors that occurred (negative)", 0),
                        ],
                        [
                            ("T: weights of all applicable expected items", 0),
                            ("Score = (P + N) / T", 0),
                        ],
                    ],
                    [2.15 * inch, 1.5 * inch, 2.15 * inch, 1.5 * inch],
                ),
                P(
                    "Include standard items. Leave N/A items, and items for complications that did not occur, out of T. "
                    "The score can fall below 0. Rated (1-5) items are recorded on their own and are not part of P or T.",
                    "note",
                ),
            ]
        )
    )

    # ---------- C. global ratings ----------
    story.append(P("C. Global ratings: circle one per domain", "h"))
    story.append(P("Anchors describe 1, 3 and 5; 2 and 4 fall between them.", "note"))
    for d in base.domains:
        anchors = _table(
            [
                [
                    P("1", "cellb"),
                    P(d.anchors.one),
                    P("3", "cellb"),
                    P(d.anchors.three),
                    P("5", "cellb"),
                    P(d.anchors.five),
                ]
            ],
            [0.2 * inch, (W - 0.6 * inch) / 3] * 3,
            header=False,
            zebra=False,
            pad=2,
        )
        head = Table(
            [[P(f"{d.id} {d.name}", "cellb"), Circles(), PM("<b>Evidence</b> __________________")]],
            colWidths=[W - 3.75 * inch, 1.6 * inch, 2.15 * inch],
        )
        head.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 4),
                    ("BACKGROUND", (0, 0), (-1, -1), TINT),
                ]
            )
        )
        story.append(KeepTogether([Spacer(1, 5), head, P(d.description, "small"), anchors]))

    # ---------- D. outcome ----------
    story.append(
        KeepTogether(
            [
                P("D. Outcome", "h"),
                P(
                    "From the simulation log when there is one; for a hand-run scenario, record what the transcript shows.",
                    "note",
                ),
                _table(
                    [
                        [
                            P("O1 Course reached", "cellb"),
                            Choices(
                                [
                                    "Treated, best",
                                    "Treated, worst",
                                    "Untreated, best",
                                    "Untreated, worst",
                                ]
                            ),
                        ],
                        [
                            P("Removal to definitive care", "cellb"),
                            Choices(["Not recommended", "Recommended"]),
                        ],
                        [P("Loss of crew life", "cellb"), Choices(["No", "Yes"])],
                        [
                            P("O2 Time to correct leading diagnosis", "cellb"),
                            PM("________ h after T+0"),
                        ],
                        [
                            P("O3 Time to first indicated treatment", "cellb"),
                            PM("________ h after T+0"),
                        ],
                        [
                            P("O4 Task impairment", "cellb"),
                            PM("________ impairment-hours (simulated runs)"),
                        ],
                        [
                            P("O5 Resources used or wasted", "cellb"),
                            PM("____________________________________________"),
                        ],
                    ],
                    [2.3 * inch, W - 2.3 * inch],
                    header=False,
                    pad=5,
                ),
            ]
        )
    )

    # ---------- notes ----------
    story.append(P("Notes and anomalies", "h"))
    story.append(
        P(
            "Anything unusual: a dose that differs from other runs, a claim not supported by the transcript, "
            "a reply that broke off. Give the turn or time.",
            "note",
        )
    )
    lines = Table([[""] for _ in range(6)], colWidths=[W], rowHeights=[0.3 * inch] * 6)
    lines.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 0.5, RULE)]))
    story.append(lines)
    story.append(Spacer(1, 10))
    story.append(
        _fields(
            [[("Rater signature", 0), ("Second rater (if any)", 0)]],
            [1.3 * inch, 2.35 * inch, 1.4 * inch, 2.25 * inch],
        )
    )

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return out


def _item_row(it, done):
    wt = f"{'+' if it.weight > 0 else ''}{it.weight}"
    deadline = it.by or ""
    if it.complication and it.by:
        deadline = f"onset + {it.by.removeprefix('T+')}"
    text = it.text + (" (rated 1-5)" if it.type == "rating" else "")
    result = Circles() if it.type == "rating" else Choices(done)
    return [P(it.id, "cellb"), P(text), P(wt), P(deadline), result, ""]


def _trigger(x) -> str:
    what = x.action.text or ", ".join(x.action.refs) if x.action else ""
    if x.trigger == "untreated":
        s = f"occurs at {x.by} unless treated ({what})"
    elif x.trigger == "action":
        s = f"occurs {x.after + ' after' if x.after else 'on'}: {what}"
    else:
        s = f"occurs at {x.at}"
    if x.chance < 1:
        s += f", in {round(x.chance * 100)}% of runs"
    if x.worst_course_only:
        s += ", worst-course runs only"
    if x.recognise_within:
        s += f"; recognise within {x.recognise_within}"
    return s
