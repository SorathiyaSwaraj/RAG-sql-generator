import pytest

from schema_rag import cli
from schema_rag.generation.llm import Completion, LLMError

DUMP = """CREATE TABLE `orders` (`id` int NOT NULL, `amount` int) ENGINE=InnoDB;
DELIMITER ;;
CREATE PROCEDURE `order_report`()
BEGIN
  SELECT id FROM orders;
END ;;
DELIMITER ;
"""


@pytest.fixture
def config(tmp_path, embedder, monkeypatch):
    (tmp_path / "d.sql").write_text(DUMP)
    path = tmp_path / "databases.yaml"
    path.write_text(
        f"data_dir: {tmp_path / 'data'}\n"
        f"databases:\n  shop:\n    dialect: mysql\n    dump_path: {tmp_path / 'd.sql'}\n"
    )
    monkeypatch.setattr(cli, "FastEmbedEmbedder", lambda _: embedder)
    assert cli.main(["--config", str(path), "ingest", "shop"]) == 0
    return str(path)


class Cloud:
    name = "cloud"
    sends_data_off_machine = True
    calls = 0

    def complete(self, prompt):
        Cloud.calls += 1
        return Completion("SELECT id FROM orders", "cloud")


@pytest.fixture
def cloud(monkeypatch):
    Cloud.calls = 0
    monkeypatch.setattr(cli, "build_provider", lambda _: Cloud())


def test_ingest_prints_report(config, capsys):
    assert cli.main(["--config", config, "ingest", "shop"]) == 0
    assert '"tables": 1' in capsys.readouterr().out


def test_retrieve_prints_tables(config, capsys):
    assert cli.main(["--config", config, "retrieve", "shop", "order amount"]) == 0
    assert "orders" in capsys.readouterr().out


def test_dry_run_prints_prompt_and_sends_nothing(config, cloud, capsys):
    assert cli.main(["--config", config, "generate", "query", "shop", "ids", "--dry-run"]) == 0
    assert "SCHEMA" in capsys.readouterr().out
    assert Cloud.calls == 0


def test_cloud_generation_requires_confirmation(config, cloud, monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda _: "n")

    assert cli.main(["--config", config, "generate", "query", "shop", "ids"]) == 1
    assert Cloud.calls == 0
    assert "cancelled" in capsys.readouterr().err


def test_generation_prints_honest_status(config, cloud, capsys):
    assert cli.main(["--config", config, "generate", "query", "shop", "ids", "--yes"]) == 0
    assert "statically validated, not executed" in capsys.readouterr().out


def test_validate_returns_failure_code(config, tmp_path, capsys):
    bad = tmp_path / "bad.sql"
    bad.write_text("SELECT nope FROM orders")

    assert cli.main(["--config", config, "validate", "query", "shop", str(bad)]) == 2
    assert "unknown column" in capsys.readouterr().out


def test_missing_key_is_a_clean_error(config, monkeypatch, capsys):
    def fail(_):
        raise LLMError("GEMINI_API_KEY is not set")

    monkeypatch.setattr(cli, "build_provider", fail)

    assert cli.main(["--config", config, "generate", "query", "shop", "ids", "--yes"]) == 1
    assert "GEMINI_API_KEY" in capsys.readouterr().err
