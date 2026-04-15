"""Tests for mysql_mcp.llm.prompt."""

from __future__ import annotations

import pytest

from mysql_mcp.llm.prompt import PromptBuilder
from mysql_mcp.models.schema import (
    ColumnInfo,
    DatabaseSchema,
    ForeignKeyInfo,
    IndexInfo,
    SchemaCache,
    TableSchema,
)


def _sample_cache() -> SchemaCache:
    return SchemaCache(
        databases={
            "shop": DatabaseSchema(
                name="shop",
                tables={
                    "users": TableSchema(
                        name="users",
                        columns=[
                            ColumnInfo(name="id", type="int", auto_increment=True),
                            ColumnInfo(name="name", type="varchar(100)", comment="user name"),
                            ColumnInfo(name="email", type="varchar(255)"),
                            ColumnInfo(name="status", type="enum('active','inactive')"),
                        ],
                        indexes=[
                            IndexInfo(name="PRIMARY", columns=["id"], unique=True),
                            IndexInfo(name="idx_email", columns=["email"], unique=True),
                        ],
                        comment="user table",
                    ),
                    "orders": TableSchema(
                        name="orders",
                        columns=[
                            ColumnInfo(name="id", type="int", auto_increment=True),
                            ColumnInfo(name="user_id", type="int"),
                            ColumnInfo(name="total", type="decimal(10,2)"),
                            ColumnInfo(name="created_at", type="datetime"),
                        ],
                        foreign_keys=[
                            ForeignKeyInfo(
                                name="fk_user",
                                columns=["user_id"],
                                ref_table="users",
                                ref_columns=["id"],
                            )
                        ],
                        comment="order table",
                    ),
                    "products": TableSchema(
                        name="products",
                        columns=[
                            ColumnInfo(name="id", type="int"),
                            ColumnInfo(name="name", type="varchar(200)"),
                            ColumnInfo(name="price", type="decimal(10,2)"),
                        ],
                        comment="product catalog",
                    ),
                },
            ),
        },
        table_index={"users": ["shop"], "orders": ["shop"], "products": ["shop"]},
    )


@pytest.fixture()
def cache() -> SchemaCache:
    return _sample_cache()


@pytest.fixture()
def builder(cache: SchemaCache) -> PromptBuilder:
    return PromptBuilder(cache, max_limit=1000)


class TestFindCandidateTables:
    def test_direct_table_match(self, builder: PromptBuilder) -> None:
        assert "users" in builder.find_candidate_tables("show all users", "shop")

    def test_column_name_match(self, builder: PromptBuilder) -> None:
        candidates = builder.find_candidate_tables("show email addresses", "shop")
        assert "users" in candidates  # 'email' column is in users

    def test_comment_match(self, builder: PromptBuilder) -> None:
        candidates = builder.find_candidate_tables("product data", "shop")
        assert "products" in candidates  # 'product' in comment

    def test_fk_expansion(self, builder: PromptBuilder) -> None:
        candidates = builder.find_candidate_tables("show all orders", "shop")
        assert "orders" in candidates
        assert "users" in candidates  # expanded via FK

    def test_reverse_fk_expansion(self, builder: PromptBuilder) -> None:
        candidates = builder.find_candidate_tables("show all users", "shop")
        assert "users" in candidates
        assert "orders" in candidates  # orders references users via FK

    def test_fallback_all_tables(self, builder: PromptBuilder) -> None:
        candidates = builder.find_candidate_tables("xyzzy nothing", "shop")
        assert set(candidates) == {"users", "orders", "products"}

    def test_nonexistent_database(self, builder: PromptBuilder) -> None:
        assert builder.find_candidate_tables("users", "nonexistent") == []


class TestBuildSystemPrompt:
    def test_contains_schema_context(self, builder: PromptBuilder) -> None:
        prompt = builder.build_system_prompt("shop", ["users"])
        assert "CREATE TABLE users" in prompt
        assert "id" in prompt
        assert "varchar" in prompt

    def test_contains_rules(self, builder: PromptBuilder) -> None:
        prompt = builder.build_system_prompt("shop")
        assert "LIMIT" in prompt
        assert "SELECT" in prompt
        assert "1000" in prompt

    def test_table_index_included(self, builder: PromptBuilder) -> None:
        prompt = builder.build_system_prompt("shop")
        assert "users" in prompt
        assert "orders" in prompt
        assert "products" in prompt

    def test_detailed_layer_for_few_candidates(self, builder: PromptBuilder) -> None:
        prompt = builder.build_system_prompt("shop", ["users"])
        assert "CREATE TABLE users" in prompt
        assert "NOT NULL" in prompt or "AUTO_INCREMENT" in prompt

    def test_summary_layer_for_many_candidates(self, cache: SchemaCache) -> None:
        # Add more tables to exceed 20
        for i in range(25):
            cache.databases["shop"].tables[f"extra_table_{i}"] = TableSchema(
                name=f"extra_table_{i}",
                columns=[ColumnInfo(name="id", type="int")],
            )

        builder = PromptBuilder(cache)
        candidates = [f"extra_table_{i}" for i in range(21)]
        prompt = builder.build_system_prompt("shop", candidates)
        # Summary format: table_name(col1, col2)
        assert "extra_table_0(id)" in prompt

    def test_nonexistent_database(self, builder: PromptBuilder) -> None:
        prompt = builder.build_system_prompt("nonexistent")
        assert "nonexistent" in prompt
        # Should still have the template, just no schema
        assert "SELECT" in prompt

    def test_includes_index_info(self, builder: PromptBuilder) -> None:
        prompt = builder.build_system_prompt("shop", ["users"])
        assert "UNIQUE INDEX idx_email" in prompt

    def test_includes_fk_info(self, builder: PromptBuilder) -> None:
        prompt = builder.build_system_prompt("shop", ["orders"])
        assert "FOREIGN KEY" in prompt
        assert "REFERENCES users" in prompt
