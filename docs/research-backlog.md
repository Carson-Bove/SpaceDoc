# Research Backlog

These are sources I want to read but haven't been able to open in full yet. They are **not cited anywhere**. Each one moves into [references](references.md) or the corpus manifest only after it has been read in full.

**Status (Sept 2026):** the build environment's network policy blocks the hosts that serve these documents, including arxiv.org, pmc.ncbi.nlm.nih.gov, www.nasa.gov, standards.nasa.gov and huggingface.co. Once they are allowed:
1. Read each item in full.
2. Keep it in references if it is a paper or official document.
3. Add the open-access ones to `corpus/manifest.yaml`.
4. Remove the non-paper sources (news, blogs, vendor pages) from `references.md`.

## Candidate knowledge-base documents (Phase 1 corpus)

| Document | Why | Host |
|---|---|---|
| NASA-STD-3001 Vol 1 (Crew Health) and Vol 2 | Levels of care, medical requirements | standards.nasa.gov |
| HRP Evidence Report: medical conditions in mission | Core space-medicine evidence | humanresearchroadmap.nasa.gov |
| HRP Evidence Report: SANS | Top-priority spaceflight risk | ntrs.nasa.gov (later) |
| Exploration medical condition list reports | Seeds the differential engine | ntrs.nasa.gov (later) |
| Drug stability and ISS formulary expiration papers (PMC) | Formulary shelf-life | pmc.ncbi.nlm.nih.gov |
| Lunar and Martian dust toxicity reviews (PMC) | Surface-mission conditions | pmc.ncbi.nlm.nih.gov |
| Microgravity CPR scoping review | Emergency protocol variants | publisher or PMC copy |

## References awaiting full-text verification

Every entry currently in `references.md` marked **[S]** or **[K]** is here by definition. The priority items are the papers the design depends on most:
- MiniCheck (grounding checker)
- MedHallu (medical hallucination detection)
- Semantic entropy (Farquhar et al., *Nature* 2024)
- HealthBench (rubric-based evaluation)
- AMIE (OSCE-style evaluation)
- The NASA OSCE evaluation of the CMO-DA clinical decision support tool
- PTB-XL (ECG dataset)
- FDA Clinical Decision Support Software guidance (2026)
