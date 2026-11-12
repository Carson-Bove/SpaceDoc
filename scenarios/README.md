# Scenarios

Evaluation scenarios for MedSim Eval ([design](../docs/11-evaluation-system.md), [guide for clerks](../docs/scenario-builder-guide.md)).

| Folder | What goes here |
|---|---|
| `inbox/` | New and revised scenarios from the Scenario Builder: a `.scenario.json` and a `.rubric.json` per scenario |
| `approved/` | Scenarios that passed peer review (and physiology review, if requested) |

Check everything before moving it:

```bash
medsim validate scenarios/
```

A worked example is in [`medsim-eval/examples/`](../medsim-eval/examples/).
