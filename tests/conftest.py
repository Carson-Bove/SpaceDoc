import pytest

from spacedoc.config import REPO_ROOT, Settings
from spacedoc.env.context import load_environment
from spacedoc.system import build_system
from spacedoc.tools.formulary import Formulary

DATA = REPO_ROOT / "data"


@pytest.fixture
def settings(tmp_path):
    return Settings(db_path=tmp_path / "kb.db", audit_path=tmp_path / "audit" / "audit.jsonl")


@pytest.fixture
def formulary():
    return Formulary.load("example-transit", DATA)


@pytest.fixture
def env_t4():
    return load_environment("T4", DATA)


@pytest.fixture
def demo_system(settings):
    return build_system(settings, demo=True)


def exposure(engine, **answers):
    """Exposure-check answers as the card sends them: every item No unless named, e.g.
    exposure(engine, EXP_ATMOS="Yes")."""
    named = {k.replace("_", "-"): v for k, v in answers.items()}
    from spacedoc.consult.engine import Answer

    return [
        Answer(kind="screen", question=i.question, answer=named.get(i.id, "No"), screen_id=i.id)
        for i in engine.screen.items
    ]
