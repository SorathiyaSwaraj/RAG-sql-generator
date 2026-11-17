from schema_rag.ingestion.oracle_parser import parse_oracle_statements
from schema_rag.ingestion.splitter import split_oracle_statements
from schema_rag.models import ColumnPair

BANNER = "-" * 56
DUMP = f"""{BANNER}
--  File created - today
{BANNER}
DROP TABLE "APP"."ORDERS" cascade constraints;
{BANNER}
--  DDL for Table ORDERS
{BANNER}

  CREATE TABLE "APP"."ORDERS"
   (    "ID" RAW(16) NOT NULL ENABLE,
    "REGION" VARCHAR2(8 CHAR),
    "AMOUNT" NUMBER(12,2) DEFAULT 0,
    "PLACED_ON" TIMESTAMP (6) NOT NULL ENABLE,
    CHECK ("AMOUNT" IN (0, 1)) ENABLE,
     CONSTRAINT "FK_INLINE" FOREIGN KEY ("REGION", "ID")
      REFERENCES "APP"."CUSTOMERS" ("C_REGION", "C_ID") ENABLE
   ) PCTFREE 10 STORAGE(INITIAL 65536)
  TABLESPACE "USERS"
   COMMENT ON COLUMN "APP"."ORDERS"."AMOUNT" IS 'Total; it''s net'
   COMMENT ON TABLE "APP"."ORDERS"  IS 'Customer orders'
  CREATE TABLE "APP"."LOGMNR_X" SHARING=METADATA
   ("A" NUMBER)
{BANNER}
--  DDL for Index PK_ORDERS
{BANNER}

  CREATE UNIQUE INDEX "APP"."PK_ORDERS" ON "APP"."ORDERS" ("ID")
{BANNER}
--  DDL for View V_ORDERS
{BANNER}

  CREATE OR REPLACE FORCE NONEDITIONABLE VIEW "APP"."V_ORDERS" ("ID") AS
  SELECT "ID" FROM ORDERS;
{BANNER}
--  DDL for Procedure DAILY_SALES
{BANNER}
set define off;

  CREATE OR REPLACE EDITIONABLE PROCEDURE "APP"."DAILY_SALES" (cur OUT SYS_REFCURSOR)
AS
BEGIN
  OPEN cur FOR SELECT 1 FROM dual;
  COMMIT;
END;

/
{BANNER}
--  Constraints for Table ORDERS
{BANNER}

  ALTER TABLE "APP"."ORDERS" MODIFY ("REGION" NOT NULL ENABLE)
  ALTER TABLE "APP"."ORDERS" ADD CONSTRAINT "PK_ORDERS" PRIMARY KEY ("ID")
  USING INDEX PCTFREE 10 ENABLE
  ALTER TABLE "APP"."ORDERS" ADD CONSTRAINT "U_R" UNIQUE ("REGION") ENABLE
  ALTER TABLE "APP"."LOGMNR_X" MODIFY ("A" NOT NULL ENABLE)
{BANNER}
--  Ref Constraints for Table ORDERS
{BANNER}

  ALTER TABLE "APP"."ORDERS" ADD CONSTRAINT "FK_INLINE" FOREIGN KEY ("REGION", "ID")
      REFERENCES "APP"."CUSTOMERS" ("C_REGION", "C_ID") ENABLE
  ALTER TABLE "APP"."ORDERS" ADD CONSTRAINT "FK_S" FOREIGN KEY ("AMOUNT")
      REFERENCES "APP"."AMOUNTS" ("A_ID") ENABLE
"""


def parse():
    return parse_oracle_statements(split_oracle_statements(DUMP))


def test_splitter_keeps_procedure_whole_without_set_define():
    statements = split_oracle_statements(DUMP)
    procedure = next(s for s in statements if "PROCEDURE" in s)

    assert procedure.startswith("CREATE OR REPLACE EDITIONABLE PROCEDURE")
    assert "COMMIT;\nEND;" in procedure


def test_parses_columns_and_excludes_system_tables():
    parsed = parse()

    assert parsed.unrecognized == []
    assert parsed.excluded_system_tables == 1
    assert [table.name for table in parsed.tables] == ["ORDERS"]
    columns = {column.name: column for column in parsed.tables[0].columns}
    assert columns["ID"].data_type == "RAW(16)"
    assert columns["ID"].nullable is False
    assert columns["AMOUNT"].data_type == "NUMBER(12,2)"
    assert columns["PLACED_ON"].data_type == "TIMESTAMP (6)"


def test_applies_alter_constraints_and_modify():
    table = parse().tables[0]
    columns = {column.name: column for column in table.columns}

    assert table.primary_key == ("ID",)
    assert columns["REGION"].nullable is False


def test_repeated_foreign_key_is_deduplicated_and_pairs_kept():
    keys = {key.name: key for key in parse().tables[0].foreign_keys}

    assert set(keys) == {"FK_INLINE", "FK_S"}
    assert keys["FK_INLINE"].column_pairs == (
        ColumnPair(source="REGION", target="C_REGION"),
        ColumnPair(source="ID", target="C_ID"),
    )


def test_applies_comments():
    table = parse().tables[0]
    columns = {column.name: column for column in table.columns}

    assert table.comment == "Customer orders"
    assert columns["AMOUNT"].comment == "Total; it''s net"


def test_extracts_views_and_procedures():
    parsed = parse()

    assert [view.name for view in parsed.views] == ["V_ORDERS"]
    assert [procedure.name for procedure in parsed.procedures] == ["DAILY_SALES"]


def test_reports_unknown_statement_by_keyword_only():
    parsed = parse_oracle_statements(["CREATE DIRECTORY secret_dir AS '/private'"])

    assert parsed.unrecognized == ["CREATE DIRECTORY"]
