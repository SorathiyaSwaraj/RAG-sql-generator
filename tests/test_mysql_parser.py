import pytest

from schema_rag.ingestion.mysql_parser import parse_mysql_statements
from schema_rag.ingestion.splitter import split_mysql_statements
from schema_rag.models import ColumnPair

ORDERS = """CREATE TABLE `orders` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT COMMENT 'Order number; unique',
  `region` varchar(8) NOT NULL,
  `amount` decimal(12,2) DEFAULT NULL,
  `status` enum('new','paid') DEFAULT 'new',
  PRIMARY KEY (`id`,`region`),
  UNIQUE KEY `u_region` (`region`),
  KEY `k_amount` (`amount`),
  CONSTRAINT `fk_customer` FOREIGN KEY (`region`, `id`)
    REFERENCES `customers` (`customer_region`, `customer_id`) ON DELETE CASCADE,
  CONSTRAINT `fk_status` FOREIGN KEY (`status`) REFERENCES `statuses` (`code`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"""


def parse_orders():
    parsed = parse_mysql_statements([ORDERS])
    assert parsed.unrecognized == []
    return parsed.tables[0]


def test_parses_table_name_and_column_order():
    table = parse_orders()

    assert table.name == "orders"
    assert [column.name for column in table.columns] == ["id", "region", "amount", "status"]


def test_parses_column_types_nullability_and_comments():
    columns = {column.name: column for column in parse_orders().columns}

    assert columns["id"].data_type == "BIGINT UNSIGNED"
    assert columns["amount"].data_type == "DECIMAL(12, 2)"
    assert columns["status"].data_type == "ENUM('new', 'paid')"
    assert columns["region"].nullable is False
    assert columns["amount"].nullable is True
    assert columns["id"].comment == "Order number; unique"
    assert columns["region"].comment is None


def test_parses_composite_primary_key_in_order():
    assert parse_orders().primary_key == ("id", "region")


def test_parses_table_comment():
    parsed = parse_mysql_statements(
        ["CREATE TABLE t (id int) ENGINE=InnoDB COMMENT='Sales; daily'"]
    )

    assert parsed.tables[0].comment == "Sales; daily"
    assert parse_orders().comment is None


def test_parses_inline_primary_key():
    parsed = parse_mysql_statements(["CREATE TABLE t (id int PRIMARY KEY, name text)"])

    assert parsed.tables[0].primary_key == ("id",)


def test_composite_foreign_key_pairs_columns_in_declared_order():
    composite, single = parse_orders().foreign_keys

    assert composite.name == "fk_customer"
    assert composite.referenced_table == "customers"
    assert composite.column_pairs == (
        ColumnPair(source="region", target="customer_region"),
        ColumnPair(source="id", target="customer_id"),
    )
    assert single.column_pairs == (ColumnPair(source="status", target="code"),)


def test_parses_unnamed_foreign_key():
    parsed = parse_mysql_statements(
        ["CREATE TABLE t (a int, FOREIGN KEY (a) REFERENCES other (b))"]
    )

    foreign_key = parsed.tables[0].foreign_keys[0]
    assert foreign_key.name is None
    assert foreign_key.referenced_table == "other"


@pytest.mark.parametrize(
    "statement",
    [
        "DROP TABLE IF EXISTS `orders`",
        "SET NAMES utf8",
        "/*!40101 SET character_set_client = utf8mb4 */",
        "USE `shop`",
        "LOCK TABLES `orders` WRITE",
        "UNLOCK TABLES",
        "INSERT INTO `orders` VALUES (1,'private')",
        "/*!40000 ALTER TABLE `orders` DISABLE KEYS */",
        "/*!40000 CREATE DATABASE `shop` */",
    ],
)
def test_ignores_known_irrelevant_statements(statement):
    parsed = parse_mysql_statements([statement])

    assert parsed.tables == []
    assert parsed.unrecognized == []


@pytest.mark.parametrize(
    ("statement", "label"),
    [
        ("ALTER TABLE `orders` ADD CONSTRAINT x FOREIGN KEY (a) REFERENCES b (c)", "ALTER TABLE"),
        ("CREATE EVENT nightly ON SCHEDULE EVERY 1 DAY DO SELECT 1", "CREATE EVENT"),
        ("/*!50003 GRANT SELECT ON a TO b */", "GRANT SELECT"),
    ],
)
def test_reports_unknown_statements_by_keyword_only(statement, label):
    parsed = parse_mysql_statements([statement])

    assert parsed.tables == []
    assert parsed.unrecognized == [label]


def test_reports_table_that_fails_to_parse():
    parsed = parse_mysql_statements(["CREATE TABLE broken ((("])

    assert parsed.tables == []
    assert parsed.unrecognized == ["CREATE TABLE (parse failed)"]


def test_parses_table_from_split_dump():
    dump = f"-- comment\nDROP TABLE IF EXISTS `orders`;\n{ORDERS};\nUNLOCK TABLES;\n"

    parsed = parse_mysql_statements(split_mysql_statements(dump))

    assert [table.name for table in parsed.tables] == ["orders"]
    assert parsed.unrecognized == []
