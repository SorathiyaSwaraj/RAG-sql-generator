import pytest

from schema_rag.config import DatabaseConfig, load_settings
from schema_rag.ingestion.pipeline import ingest, load_catalog, save_catalog

DUMP = """
DROP TABLE IF EXISTS `b_orders`;
CREATE TABLE `b_orders` (
  `id` int NOT NULL,
  `c_id` int,
  PRIMARY KEY (`id`),
  CONSTRAINT `fk` FOREIGN KEY (`c_id`) REFERENCES `gone` (`id`)
) ENGINE=InnoDB;
CREATE TABLE `a_noise` (`id` int) ENGINE=InnoDB;
CREATE TABLE `a_users` (`id` int) ENGINE=InnoDB;
CREATE EVENT e ON SCHEDULE EVERY 1 DAY DO SELECT 1;
DELIMITER ;;
CREATE PROCEDURE `p`() BEGIN SELECT 1; END ;;
DELIMITER ;
"""


def config(tmp_path, **kwargs):
    dump = tmp_path / "dump.sql"
    dump.write_text(DUMP)
    return DatabaseConfig(dialect="mysql", dump_path=dump, **kwargs)


def test_ingest_sorts_excludes_and_reports(tmp_path):
    catalog, report = ingest("shop", config(tmp_path, exclude_tables=["a_noise"]))

    assert [table.name for table in catalog.tables] == ["a_users", "b_orders"]
    assert (report.tables, report.columns, report.foreign_keys, report.procedures) == (2, 3, 1, 1)
    assert report.excluded_tables == 1
    assert report.unrecognized == {"CREATE EVENT": 1}
    assert report.unresolved_references == ["gone"]


def test_saved_catalog_round_trips_and_is_byte_identical(tmp_path):
    first, second = tmp_path / "first", tmp_path / "second"
    for directory in (first, second):
        catalog, report = ingest("shop", config(tmp_path))
        save_catalog(catalog, report, directory)

    assert (first / "catalog.json").read_bytes() == (second / "catalog.json").read_bytes()
    assert load_catalog(first) == catalog


def test_load_settings_rejects_unknown_database(tmp_path):
    path = tmp_path / "databases.yaml"
    path.write_text("databases:\n  shop:\n    dialect: mysql\n    dump_path: a.sql\n")

    settings = load_settings(path)

    assert settings.database("shop").dialect == "mysql"
    with pytest.raises(KeyError):
        settings.database("other")
