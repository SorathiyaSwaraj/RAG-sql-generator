import pytest
from pydantic import ValidationError

from schema_rag.models import Column, ColumnPair, ForeignKey, SchemaCatalog, Table


def make_table(name="orders", **kwargs):
    columns = (Column(name="id", data_type="int"), Column(name="region", data_type="varchar(8)"))
    return Table(name=name, columns=columns, **kwargs)


def composite_key():
    return ForeignKey(
        referenced_table="customers",
        column_pairs=(
            ColumnPair(source="region", target="customer_region"),
            ColumnPair(source="id", target="customer_id"),
        ),
    )


def test_composite_key_keeps_source_and_target_paired_in_order():
    pairs = make_table(foreign_keys=(composite_key(),)).foreign_keys[0].column_pairs

    assert [(p.source, p.target) for p in pairs] == [
        ("region", "customer_region"),
        ("id", "customer_id"),
    ]


def test_foreign_key_requires_a_column_pair():
    with pytest.raises(ValidationError):
        ForeignKey(referenced_table="customers", column_pairs=())


@pytest.mark.parametrize(
    "keys",
    [
        {"primary_key": ("missing",)},
        {
            "foreign_keys": (
                ForeignKey(
                    referenced_table="customers",
                    column_pairs=(ColumnPair(source="missing", target="id"),),
                ),
            )
        },
    ],
)
def test_table_rejects_keys_on_unknown_columns(keys):
    with pytest.raises(ValidationError, match="unknown columns"):
        make_table(**keys)


def test_foreign_key_may_reference_a_table_outside_the_catalog():
    catalog = SchemaCatalog(
        database="shop", dialect="mysql", tables=(make_table(foreign_keys=(composite_key(),)),)
    )

    assert catalog.tables[0].foreign_keys[0].referenced_table == "customers"


def test_catalog_rejects_duplicate_table_names():
    with pytest.raises(ValidationError, match="duplicate table names"):
        SchemaCatalog(database="shop", dialect="mysql", tables=(make_table(), make_table()))


def test_catalog_rejects_unknown_dialect():
    with pytest.raises(ValidationError):
        SchemaCatalog(database="shop", dialect="sqlite")


def test_catalog_round_trips_through_json():
    catalog = SchemaCatalog(
        database="shop", dialect="mysql", tables=(make_table(foreign_keys=(composite_key(),)),)
    )

    assert SchemaCatalog.model_validate_json(catalog.model_dump_json()) == catalog


def test_models_are_immutable():
    with pytest.raises(ValidationError):
        make_table().name = "renamed"
