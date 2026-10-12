"""`spacedoc models`: download the configured models and remove only SpaceDoc's old ones."""

import json

import httpx
import pytest
from typer.testing import CliRunner

import spacedoc.cli as cli
from spacedoc.config import Settings
from spacedoc.llm.client import LLMError, OllamaLLM
from spacedoc.models import ModelRecord, configured_models, old_models

GB = 10**9


def fake_server(client, handler):
    seen = []

    def wrapped(request):
        seen.append(request)
        return handler(request)

    client._client._http = httpx.Client(transport=httpx.MockTransport(wrapped))
    return seen


class FakeOllama:
    """Stands in for OllamaLLM: a dict of installed models and their sizes."""

    def __init__(self, installed, fail=()):
        self.installed = dict(installed)
        self.fail = set(fail)
        self.pulled, self.deleted = [], []

    def model_sizes(self):
        return dict(self.installed)

    def pull_model(self, name, progress=None):
        if name in self.fail:
            raise LLMError(f"pull {name}: file does not exist")
        if progress:
            progress({"status": "pulling manifest"})
            progress({"status": "pulling abc123", "total": 2 * GB, "completed": GB})
            progress({"status": "success"})
        self.pulled.append(name)
        self.installed.setdefault(name, GB)

    def delete_model(self, name):
        self.deleted.append(name)
        del self.installed[name]


@pytest.fixture
def setup(tmp_path, monkeypatch):
    """A spacedoc.toml in tmp_path, and a fake Ollama the CLI talks to."""

    def make(installed, toml="", fail=()):
        cfg = tmp_path / "spacedoc.toml"
        cfg.write_text(f'models_record_path = "models.json"\n{toml}')
        fake = FakeOllama(installed, fail)
        monkeypatch.setattr(cli, "_ollama_client", lambda settings: fake)
        return cfg, fake, ModelRecord(tmp_path / "models.json")

    return make


def run(*args, input=None):
    return CliRunner().invoke(cli.app, ["models", *args], input=input)


CURRENT = {
    "qwen3:8b": 5 * GB,
    "qwen3-embedding:0.6b": GB,
    "bespoke-minicheck:7b": 5 * GB,
}


def test_old_models_are_only_ones_spacedoc_used(tmp_path):
    record = ModelRecord(tmp_path / "models.json")
    record.add(["llama3.1:8b", "mymodel"])
    installed = {
        **CURRENT,
        "qwen3:4b": 3 * GB,  # named in the setup guide
        "llama3.1:8b": 5 * GB,  # SpaceDoc downloaded or compared it
        "mymodel:latest": GB,  # recorded without a tag
        "mistral:latest": 4 * GB,  # someone else's model: never touched
    }
    old = old_models(Settings(), installed, record)
    assert set(old) == {"qwen3:4b", "llama3.1:8b", "mymodel:latest"}
    # While qwen3:4b is the consult model, it stays.
    assert "qwen3:4b" not in old_models(Settings(consult_model="qwen3:4b"), installed, record)


def test_configured_models_cover_every_role():
    s = Settings(consult_model="qwen3:4b")
    assert configured_models(s) == [
        "qwen3:8b",
        "qwen3:4b",
        "qwen3-embedding:0.6b",
        "bespoke-minicheck:7b",
    ]
    assert configured_models(Settings(consult_model="qwen3:8b")).count("qwen3:8b") == 1


def test_pull_downloads_then_asks_before_removing(setup):
    cfg, fake, record = setup(
        {**CURRENT, "qwen3:8b": 5 * GB, "medgemma:4b": 3 * GB},
        toml='chat_model = "qwen3:4b"\n',
    )
    result = run("pull", "-c", str(cfg), input="y\n")
    assert result.exit_code == 0, result.output
    assert fake.pulled == ["qwen3:4b", "qwen3-embedding:0.6b", "bespoke-minicheck:7b"]
    assert "downloading 2.0 GB  50%" in result.output
    assert "qwen3:8b" in result.output and "medgemma:4b" in result.output
    assert "Remove them and free 8.0 GB?" in result.output
    assert sorted(fake.deleted) == ["medgemma:4b", "qwen3:8b"]
    assert "qwen3:4b" in record.names()


def test_answering_no_keeps_everything(setup):
    cfg, fake, _ = setup({**CURRENT, "qwen3:4b": 3 * GB})
    result = run("pull", "-c", str(cfg), input="n\n")
    assert result.exit_code == 0, result.output
    assert fake.deleted == [] and "Kept them." in result.output


def test_yes_skips_the_question(setup):
    cfg, fake, _ = setup({**CURRENT, "qwen3:4b": 3 * GB})
    result = run("clean", "--yes", "-c", str(cfg))
    assert result.exit_code == 0, result.output
    assert fake.deleted == ["qwen3:4b"] and "Remove them" not in result.output


def test_failed_download_removes_nothing(setup):
    cfg, fake, _ = setup(CURRENT, toml='chat_model = "qwen3:14b"\n', fail={"qwen3:14b"})
    result = run("pull", "--yes", "-c", str(cfg))
    assert result.exit_code == 1
    assert fake.deleted == []  # the old qwen3:8b stays until the new model is in place
    assert "because qwen3:14b did not download" in result.output


def test_clean_waits_until_new_models_are_downloaded(setup):
    cfg, fake, _ = setup(CURRENT, toml='chat_model = "qwen3:4b"\n')
    result = run("clean", "--yes", "-c", str(cfg))
    assert fake.deleted == []
    assert "qwen3:4b is not downloaded yet" in result.output


def test_other_models_are_never_offered(setup):
    cfg, fake, _ = setup({**CURRENT, "mistral:latest": 4 * GB, "llava:7b": 4 * GB})
    result = run("clean", "--yes", "-c", str(cfg))
    assert fake.deleted == [] and "No old models to remove" in result.output


def test_bench_models_count_as_spacedoc_models(setup, monkeypatch):
    import spacedoc.eval.bench as bench_mod

    cfg, fake, record = setup({**CURRENT, "phi4:14b": 9 * GB})
    monkeypatch.setattr(bench_mod, "bench_models", lambda *a, **k: [])
    monkeypatch.setattr(bench_mod, "bench_markdown", lambda table: "")
    CliRunner().invoke(cli.app, ["bench", "qwen3:8b", "phi4:14b", "-c", str(cfg)])
    assert "phi4:14b" in record.names()
    result = run("clean", "--yes", "-c", str(cfg))
    assert fake.deleted == ["phi4:14b"]  # qwen3:8b is still the chat model
    assert result.exit_code == 0


def test_list_shows_sizes_and_old_models(setup):
    cfg, _, _ = setup({**CURRENT, "qwen3:4b": 3 * GB}, toml='consult_model = "qwen3:1.7b"\n')
    out = run("list", "-c", str(cfg)).output
    assert "qwen3:8b" in out and "5.0 GB" in out
    assert "qwen3:1.7b" in out and "not downloaded" in out
    assert "No longer used" in out and "qwen3:4b" in out


def test_client_pull_streams_progress_and_raises_errors():
    llm = OllamaLLM("http://localhost:11434", "qwen3:8b")
    lines = [{"status": "pulling manifest"}, {"status": "success"}]
    body = "\n".join(json.dumps(x) for x in lines).encode()
    seen = fake_server(llm, lambda r: httpx.Response(200, content=body))
    got = []
    llm.pull_model("qwen3:4b", got.append)
    assert seen[0].url.path == "/api/pull"
    assert json.loads(seen[0].content) == {"model": "qwen3:4b", "stream": True}
    assert got == lines

    error = json.dumps({"error": "pull model manifest: file does not exist"}).encode()
    fake_server(llm, lambda r: httpx.Response(200, content=error))
    with pytest.raises(LLMError, match="file does not exist"):
        llm.pull_model("qwen3:99b")


def test_client_delete_and_sizes():
    llm = OllamaLLM("http://localhost:11434", "qwen3:8b")
    tags = {"models": [{"name": "qwen3:8b", "size": 5_225_388_164}]}
    seen = fake_server(llm, lambda r: httpx.Response(200, json=tags if r.method == "GET" else {}))
    assert llm.model_sizes() == {"qwen3:8b": 5_225_388_164}
    llm.delete_model("qwen3:4b")
    assert seen[1].method == "DELETE" and seen[1].url.path == "/api/delete"
    assert json.loads(seen[1].content) == {"model": "qwen3:4b"}

    fake_server(llm, lambda r: httpx.Response(404, json={"error": "model not found"}))
    with pytest.raises(LLMError, match="model not found"):
        llm.delete_model("qwen3:4b")
