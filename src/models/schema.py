"""Pydantic models for cached database schema metadata."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ColumnInfo(BaseModel):
    name: str
    type: str
    default: str | None = None
    nullable: bool = True
    auto_increment: bool = False
    comment: str | None = None


class IndexInfo(BaseModel):
    name: str
    columns: list[str]
    unique: bool = False
    index_type: str = "BTREE"


class ForeignKeyInfo(BaseModel):
    name: str
    columns: list[str]
    ref_table: str
    ref_columns: list[str]
    on_delete: str = "RESTRICT"
    on_update: str = "RESTRICT"


class TriggerInfo(BaseModel):
    name: str
    event: str  # INSERT | UPDATE | DELETE
    timing: str  # BEFORE | AFTER
    statement: str


class TableSchema(BaseModel):
    name: str
    columns: list[ColumnInfo] = Field(default_factory=list)
    indexes: list[IndexInfo] = Field(default_factory=list)
    foreign_keys: list[ForeignKeyInfo] = Field(default_factory=list)
    triggers: list[TriggerInfo] = Field(default_factory=list)
    comment: str | None = None
    updated_at: float = 0.0


class ViewSchema(BaseModel):
    name: str
    columns: list[ColumnInfo] = Field(default_factory=list)
    definition: str | None = None
    comment: str | None = None


class EnumTypeInfo(BaseModel):
    name: str
    column_name: str
    table_name: str
    values: list[str]


class DatabaseSchema(BaseModel):
    name: str
    tables: dict[str, TableSchema] = Field(default_factory=dict)
    views: dict[str, ViewSchema] = Field(default_factory=dict)
    enums: list[EnumTypeInfo] = Field(default_factory=list)


class SchemaCache(BaseModel):
    """Global schema cache. Keyed by database name."""

    databases: dict[str, DatabaseSchema] = Field(default_factory=dict)
    # table_name → [database_names] for quick DB resolution
    table_index: dict[str, list[str]] = Field(default_factory=dict)
