"""Tests for mysql_mcp.models.schema."""

from __future__ import annotations

from mysql_mcp.models.schema import (
    ColumnInfo,
    DatabaseSchema,
    EnumTypeInfo,
    ForeignKeyInfo,
    IndexInfo,
    SchemaCache,
    TableSchema,
    TriggerInfo,
    ViewSchema,
)


def _sample_table() -> TableSchema:
    return TableSchema(
        name="users",
        columns=[
            ColumnInfo(name="id", type="int", auto_increment=True),
            ColumnInfo(name="name", type="varchar(100)", comment="user name"),
            ColumnInfo(name="status", type="enum('active','inactive')"),
        ],
        indexes=[
            IndexInfo(name="PRIMARY", columns=["id"], unique=True),
            IndexInfo(name="idx_name", columns=["name"]),
        ],
        foreign_keys=[],
        triggers=[
            TriggerInfo(
                name="before_users_insert",
                event="INSERT",
                timing="BEFORE",
                statement="SET NEW.created_at = NOW()",
            )
        ],
        comment="user table",
        updated_at=1713000000.0,
    )


class TestColumnInfo:
    def test_defaults(self) -> None:
        col = ColumnInfo(name="id", type="int")
        assert col.nullable is True
        assert col.auto_increment is False
        assert col.default is None
        assert col.comment is None


class TestTableSchema:
    def test_sample_table(self) -> None:
        table = _sample_table()
        assert table.name == "users"
        assert len(table.columns) == 3
        assert len(table.indexes) == 2
        assert table.indexes[0].unique is True
        assert len(table.triggers) == 1

    def test_empty_table(self) -> None:
        table = TableSchema(name="empty")
        assert table.columns == []
        assert table.updated_at == 0.0


class TestDatabaseSchema:
    def test_with_tables(self) -> None:
        db = DatabaseSchema(
            name="shop",
            tables={"users": _sample_table()},
            enums=[
                EnumTypeInfo(
                    name="status_enum",
                    column_name="status",
                    table_name="users",
                    values=["active", "inactive"],
                )
            ],
        )
        assert "users" in db.tables
        assert len(db.enums) == 1


class TestSchemaCache:
    def test_build_and_access(self) -> None:
        cache = SchemaCache(
            databases={
                "shop": DatabaseSchema(
                    name="shop",
                    tables={"users": _sample_table()},
                ),
                "analytics": DatabaseSchema(name="analytics"),
            },
            table_index={"users": ["shop"], "orders": ["shop", "analytics"]},
        )
        assert set(cache.databases.keys()) == {"shop", "analytics"}
        assert cache.table_index["users"] == ["shop"]
        assert cache.table_index["orders"] == ["shop", "analytics"]

    def test_empty_cache(self) -> None:
        cache = SchemaCache()
        assert cache.databases == {}
        assert cache.table_index == {}

    def test_model_validate_roundtrip(self) -> None:
        cache = SchemaCache(
            databases={
                "shop": DatabaseSchema(
                    name="shop",
                    tables={"users": _sample_table()},
                ),
            },
            table_index={"users": ["shop"]},
        )
        data = cache.model_dump()
        restored = SchemaCache.model_validate(data)
        assert restored.databases["shop"].tables["users"].name == "users"
        assert restored.table_index == cache.table_index


class TestViewSchema:
    def test_basic_view(self) -> None:
        view = ViewSchema(
            name="active_users",
            columns=[ColumnInfo(name="id", type="int"), ColumnInfo(name="name", type="varchar(100)")],
            definition="SELECT id, name FROM users WHERE status = 'active'",
        )
        assert view.name == "active_users"
        assert len(view.columns) == 2
        assert "active" in (view.definition or "")
