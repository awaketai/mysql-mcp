# MySQL MCP Server - 技术设计文档

## 1. 技术栈总览

| 库 | 版本 | 用途 |
|---|---|---|
| **FastMCP** | 3.x | MCP Server 框架，提供 Tool 注册、Lifespan 管理、Context 注入 |
| **aiomysql** | 0.2.x | 异步 MySQL 驱动，提供连接池和异步查询执行 |
| **sqlglot** | 26.x | SQL 解析器，提供 AST 级别的 SQL 分析和安全校验 |
| **Pydantic** | 2.x（FastMCP 内置） | 数据模型定义、配置管理、请求/响应验证 |
| **OpenAI** | 1.x | AsyncOpenAI 客户端，用于 SQL 生成和结果验证 |

---

## 2. 架构设计

### 2.1 整体架构

```
┌─────────────────────────────────────────────────────┐
│                    MCP Client                        │
│           (Claude Desktop / Cursor / ...)            │
└────────────────────┬────────────────────────────────┘
                     │ MCP Protocol (stdio)
┌────────────────────▼────────────────────────────────┐
│                  FastMCP Server                      │
│  ┌───────────────────────────────────────────────┐  │
│  │              Lifespan Layer                    │  │
│  │  ┌──────────┐  ┌───────────┐  ┌───────────┐  │  │
│  │  │ DB Pool  │  │  Schema   │  │  LLM      │  │  │
│  │  │ (aiomysql)│  │  Cache    │  │  Client   │  │  │
│  │  └──────────┘  └───────────┘  └───────────┘  │  │
│  └───────────────────────────────────────────────┘  │
│  ┌───────────────────────────────────────────────┐  │
│  │              Tools Layer                       │  │
│  │  query │ list_databases │ describe_schema      │  │
│  │                │ execute_sql                   │  │
│  └───────────────┴───────────────────────────────┘  │
│  ┌───────────────────────────────────────────────┐  │
│  │           Processing Pipeline                  │  │
│  │  DB Identify → Prompt Build → LLM Generate    │  │
│  │  → SQL Validate → Test Execute → AI Verify    │  │
│  └───────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────┘
         │                              │
    ┌────▼────┐                  ┌──────▼──────┐
    │  MySQL  │                  │  OpenAI API │
    └─────────┘                  └─────────────┘
```

### 2.2 分层职责

| 层 | 职责 | 对应模块 |
|---|---|---|
| **Lifespan Layer** | 管理服务生命周期资源：连接池初始化/销毁、Schema 缓存加载/刷新、LLM 客户端初始化 | `server.py` |
| **Tools Layer** | MCP Tool 的注册和参数校验，调用 Processing Pipeline 处理业务逻辑 | `tools/` |
| **Processing Pipeline** | 自然语言到 SQL 的完整处理流水线 | `pipeline.py` |
| **DB Layer** | 数据库连接池管理、Schema 发现与缓存、SQL 执行 | `db/` |
| **LLM Layer** | OpenAI 客户端封装、Prompt 构建、SQL 生成、结果验证 | `llm/` |
| **Security Layer** | SQL AST 解析和安全校验 | `security/` |

---

## 3. 项目结构

```
mysql_mcp/
├── __init__.py              # 包初始化，暴露版本号
├── __main__.py              # python -m mysql_mcp 入口
├── server.py                # FastMCP 实例创建、Lifespan 定义、Tool 注册
├── config.py                # Pydantic Settings 配置模型
│
├── db/
│   ├── __init__.py
│   ├── pool.py              # aiomysql 连接池管理
│   └── schema.py            # Schema 发现、缓存、增量刷新
│
├── models/
│   ├── __init__.py
│   ├── schema.py            # Schema 数据的 Pydantic 模型
│   └── response.py          # MCP Tool 返回值的 Pydantic 模型
│
├── llm/
│   ├── __init__.py
│   ├── client.py            # AsyncOpenAI 客户端封装
│   ├── prompt.py            # Prompt 模板构建（含 Schema 筛选）
│   └── validator.py         # AI 辅助的结果验证
│
├── security/
│   ├── __init__.py
│   └── validator.py         # 基于 sqlglot 的 SQL 安全校验
│
└── tools/
    ├── __init__.py
    ├── query.py              # query tool
    ├── list_databases.py     # list_databases tool
    ├── describe_schema.py    # describe_schema tool
    └── execute_sql.py        # execute_sql tool
```

---

## 4. 核心数据模型（Pydantic）

### 4.1 配置模型 — `config.py`

```python
from pydantic_settings import BaseSettings
from pydantic import Field


class MySQLConfig(BaseSettings):
    """MySQL 连接配置"""

    host: str = Field(default="localhost", alias="MYSQL_HOST")
    port: int = Field(default=3306, alias="MYSQL_PORT")
    user: str = Field(alias="MYSQL_USER")
    password: str = Field(alias="MYSQL_PASSWORD")
    charset: str = Field(default="utf8mb4", alias="MYSQL_CHARSET")
    ssl: bool = Field(default=False, alias="MYSQL_SSL")

    # 连接池配置
    pool_min_size: int = Field(default=2, alias="MYSQL_POOL_MIN_SIZE")
    pool_max_size: int = Field(default=10, alias="MYSQL_POOL_MAX_SIZE")
    pool_recycle: int = Field(default=3600, alias="MYSQL_POOL_RECYCLE")

    model_config = {"env_prefix": ""}


class OpenAIConfig(BaseSettings):
    """OpenAI API 配置"""

    api_key: str = Field(alias="OPENAI_API_KEY")
    model: str = Field(default="gpt-4o", alias="OPENAI_MODEL")
    base_url: str | None = Field(default=None, alias="OPENAI_BASE_URL")
    max_retries: int = Field(default=3, alias="OPENAI_MAX_RETRIES")
    timeout: int = Field(default=60, alias="OPENAI_TIMEOUT")

    model_config = {"env_prefix": ""}


class AppConfig(BaseSettings):
    """应用全局配置"""

    mysql: MySQLConfig = MySQLConfig()
    openai: OpenAIConfig = OpenAIConfig()

    allowed_databases: list[str] = Field(default_factory=list, alias="ALLOWED_DATABASES")
    default_database: str | None = Field(default=None, alias="DEFAULT_DATABASE")
    schema_refresh_interval: int = Field(default=0, alias="SCHEMA_REFRESH_INTERVAL")
    query_timeout: int = Field(default=30, alias="QUERY_TIMEOUT")
    max_limit: int = Field(default=1000, alias="MAX_LIMIT")
    schema_token_budget: int = Field(default=4000, alias="SCHEMA_TOKEN_BUDGET")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    model_config = {"env_prefix": ""}
```

### 4.2 Schema 数据模型 — `models/schema.py`

```python
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
    index_type: str = "BTREE"  # BTREE | HASH | FULLTEXT | SPATIAL


class ForeignKeyInfo(BaseModel):
    name: str
    columns: list[str]
    ref_table: str
    ref_columns: list[str]
    on_delete: str = "RESTRICT"
    on_update: str = "RESTRICT"


class TriggerInfo(BaseModel):
    name: str
    event: str       # INSERT | UPDATE | DELETE
    timing: str      # BEFORE | AFTER
    statement: str


class TableSchema(BaseModel):
    name: str
    columns: list[ColumnInfo] = Field(default_factory=list)
    indexes: list[IndexInfo] = Field(default_factory=list)
    foreign_keys: list[ForeignKeyInfo] = Field(default_factory=list)
    triggers: list[TriggerInfo] = Field(default_factory=list)
    comment: str | None = None
    updated_at: float = 0.0  # INFORMATION_SCHEMA 更新时间戳，用于增量刷新


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
    """全局 Schema 缓存，key 为数据库名"""

    databases: dict[str, DatabaseSchema] = Field(default_factory=dict)
    # 全局表名索引：table_name -> [database_name]，用于快速推断目标数据库
    table_index: dict[str, list[str]] = Field(default_factory=dict)
```

### 4.3 响应数据模型 — `models/response.py`

```python
from pydantic import BaseModel, Field


class SQLResult(BaseModel):
    """查询结果"""

    sql: str
    database: str
    columns: list[str] = Field(default_factory=list)
    rows: list[list] = Field(default_factory=list)
    row_count: int = 0
    truncated: bool = False


class SQLResponse(BaseModel):
    """SQL 模式返回"""

    sql: str
    database: str
    explanation: str


class BothResponse(BaseModel):
    """Both 模式返回"""

    sql: str
    database: str
    explanation: str
    columns: list[str] = Field(default_factory=list)
    rows: list[list] = Field(default_factory=list)
    row_count: int = 0
    truncated: bool = False


class ListDatabasesResponse(BaseModel):
    databases: list[str]


class DescribeSchemaResponse(BaseModel):
    database: str
    tables: dict[str, dict] = Field(default_factory=dict)
    views: dict[str, dict] = Field(default_factory=dict)
    enums: list[dict] = Field(default_factory=list)
```

---

## 5. 核心模块设计

### 5.1 生命周期管理 — `server.py`

使用 FastMCP 的 Lifespan 机制在服务启动时初始化所有资源，在关闭时清理。

```python
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastmcp import FastMCP, Context
from mysql_mcp.config import AppConfig
from mysql_mcp.db.pool import create_pool, close_pool
from mysql_mcp.db.schema import SchemaManager
from mysql_mcp.llm.client import LLMClient


@asynccontextmanager
async def app_lifespan(server: FastMCP) -> AsyncIterator[dict]:
    """服务生命周期管理

    Yields:
        包含所有共享资源的 dict，通过 ctx.lifespan_context 访问
    """
    config = AppConfig()

    # 1. 初始化 MySQL 连接池
    pool = await create_pool(config.mysql)

    # 2. 初始化 Schema 管理器，加载并缓存 Schema
    schema_manager = SchemaManager(pool, config)
    await schema_manager.load_all()

    # 3. 初始化 LLM 客户端
    llm_client = LLMClient(config.openai)

    # 4. 启动定时刷新任务（如果配置了刷新间隔）
    refresh_task = await schema_manager.start_refresh_if_configured()

    try:
        yield {
            "config": config,
            "pool": pool,
            "schema_manager": schema_manager,
            "llm_client": llm_client,
        }
    finally:
        # 清理顺序：停止刷新 → 关闭 LLM → 关闭连接池
        if refresh_task:
            refresh_task.cancel()
        await llm_client.close()
        await close_pool(pool)


mcp = FastMCP("MySQL MCP Server", lifespan=app_lifespan)
```

### 5.2 数据库连接池 — `db/pool.py`

基于 aiomysql 的连接池管理，所有数据库操作通过连接池执行。

```python
import aiomysql
from mysql_mcp.config import MySQLConfig


async def create_pool(config: MySQLConfig) -> aiomysql.Pool:
    """创建 aiomysql 连接池"""
    pool = await aiomysql.create_pool(
        host=config.host,
        port=config.port,
        user=config.user,
        password=config.password,
        charset=config.charset,
        minsize=config.pool_min_size,
        maxsize=config.pool_max_size,
        pool_recycle=config.pool_recycle,
        autocommit=True,
    )
    return pool


async def close_pool(pool: aiomysql.Pool) -> None:
    """关闭连接池"""
    pool.close()
    await pool.wait_closed()


async def execute_query(
    pool: aiomysql.Pool,
    sql: str,
    database: str | None = None,
    timeout: int = 30,
) -> tuple[list[str], list[tuple]]:
    """执行 SQL 查询并返回列名和行数据"""
    async with pool.acquire() as conn:
        if database:
            await conn.select_db(database)
        async with conn.cursor() as cur:
            await cur.execute(f"SET SESSION max_execution_time = {timeout * 1000}")
            await cur.execute(sql)
            columns = [desc[0] for desc in cur.description] if cur.description else []
            rows = await cur.fetchall()
            return columns, list(rows)
```

### 5.3 Schema 管理器 — `db/schema.py`

负责 Schema 的发现、缓存、增量刷新和两阶段筛选。

```python
import asyncio
import logging
from datetime import UTC, datetime

import aiomysql

from mysql_mcp.config import AppConfig
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

logger = logging.getLogger(__name__)

# 用于增量刷新的 SQL 查询
_GET_ACCESSIBLE_DATABASES = """
    SELECT SCHEMA_NAME FROM information_schema.SCHEMATA
    WHERE SCHEMA_NAME NOT IN ('information_schema', 'mysql', 'performance_schema', 'sys')
"""

_GET_TABLES = """
    SELECT TABLE_NAME, TABLE_COMMENT,
           COALESCE(UNIX_TIMESTAMP(UPDATE_TIME), 0) as updated_at
    FROM information_schema.TABLES
    WHERE TABLE_SCHEMA = %s AND TABLE_TYPE = 'BASE TABLE'
"""

_GET_COLUMNS = """
    SELECT COLUMN_NAME, COLUMN_TYPE, COLUMN_DEFAULT, IS_NULLABLE,
           EXTRA, COLUMN_COMMENT
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s
    ORDER BY ORDINAL_POSITION
"""

_GET_INDEXES = """
    SELECT INDEX_NAME, GROUP_CONCAT(COLUMN_NAME ORDER BY SEQ_IN_INDEX) as columns,
           NOT NON_UNIQUE as is_unique, INDEX_TYPE
    FROM information_schema.STATISTICS
    WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s
    GROUP BY INDEX_NAME, NON_UNIQUE, INDEX_TYPE
"""

_GET_FOREIGN_KEYS = """
    SELECT CONSTRAINT_NAME, GROUP_CONCAT(COLUMN_NAME) as columns,
           REFERENCED_TABLE_NAME, GROUP_CONCAT(REFERENCED_COLUMN_NAME) as ref_columns,
           DELETE_RULE, UPDATE_RULE
    FROM information_schema.KEY_COLUMN_USAGE
    WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s
      AND REFERENCED_TABLE_NAME IS NOT NULL
    GROUP BY CONSTRAINT_NAME, REFERENCED_TABLE_NAME, DELETE_RULE, UPDATE_RULE
"""

_GET_VIEWS = """
    SELECT TABLE_NAME, VIEW_DEFINITION, VIEW_DEFINITION as definition
    FROM information_schema.VIEWS
    WHERE TABLE_SCHEMA = %s
"""

_GET_ENUMS = """
    SELECT COLUMN_NAME, TABLE_NAME, COLUMN_TYPE
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = %s AND DATA_TYPE = 'enum'
"""


class SchemaManager:
    """Schema 缓存管理器"""

    def __init__(self, pool: aiomysql.Pool, config: AppConfig) -> None:
        self._pool = pool
        self._config = config
        self._cache = SchemaCache()
        self._refresh_task: asyncio.Task | None = None

    @property
    def cache(self) -> SchemaCache:
        return self._cache

    async def load_all(self) -> None:
        """启动时加载所有可访问数据库的 Schema"""
        databases = await self._get_accessible_databases()
        for db_name in databases:
            db_schema = await self._load_database_schema(db_name)
            self._cache.databases[db_name] = db_schema
        self._rebuild_table_index()
        logger.info(
            "Schema loaded: %d databases, %d tables total",
            len(self._cache.databases),
            sum(len(db.tables) for db in self._cache.databases.values()),
        )

    async def refresh_incremental(self) -> None:
        """增量刷新：对比 UPDATE_TIME，只更新发生变更的表"""
        for db_name, db_schema in self._cache.databases.items():
            current_tables = await self._fetch_current_table_timestamps(db_name)
            for table_name, (new_ts, comment) in current_tables.items():
                cached = db_schema.tables.get(table_name)
                if cached is None or cached.updated_at < new_ts:
                    await self._refresh_table(db_name, table_name, comment, new_ts)
            # 检测被删除的表
            removed = set(db_schema.tables.keys()) - set(current_tables.keys())
            for table_name in removed:
                del db_schema.tables[table_name]
        self._rebuild_table_index()

    async def start_refresh_if_configured(self) -> asyncio.Task | None:
        """如果配置了刷新间隔，启动后台定时刷新任务"""
        interval = self._config.schema_refresh_interval
        if interval <= 0:
            return None

        async def _refresh_loop() -> None:
            while True:
                await asyncio.sleep(interval)
                try:
                    await self.refresh_incremental()
                    logger.info("Schema incremental refresh completed")
                except Exception:
                    logger.exception("Schema refresh failed")

        self._refresh_task = asyncio.create_task(_refresh_loop())
        return self._refresh_task

    # --- 以下为内部方法，省略部分实现细节 ---

    async def _get_accessible_databases(self) -> list[str]:
        """获取可访问的数据库列表"""
        ...

    async def _load_database_schema(self, db_name: str) -> DatabaseSchema:
        """加载单个数据库的完整 Schema"""
        ...

    async def _fetch_current_table_timestamps(
        self, db_name: str
    ) -> dict[str, tuple[float, str]]:
        """获取当前所有表的更新时间戳"""
        ...

    async def _refresh_table(
        self, db_name: str, table_name: str, comment: str, updated_at: float
    ) -> None:
        """刷新单张表的 Schema"""
        ...

    def _rebuild_table_index(self) -> None:
        """重建全局表名索引"""
        ...

    def find_candidate_tables(
        self, user_input: str, database: str
    ) -> list[str]:
        """两阶段筛选：根据用户输入匹配候选表（用于 Prompt 构建）"""
        ...
```

### 5.4 LLM 客户端 — `llm/client.py`

封装 AsyncOpenAI，提供 SQL 生成和结果验证两个核心方法。

```python
from openai import AsyncOpenAI

from mysql_mcp.config import OpenAIConfig


class LLMClient:
    """OpenAI 客户端封装"""

    def __init__(self, config: OpenAIConfig) -> None:
        self._config = config
        self._client = AsyncOpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
            max_retries=config.max_retries,
            timeout=config.timeout,
        )

    async def generate_sql(self, system_prompt: str, user_input: str) -> str:
        """调用 LLM 生成 SQL"""
        response = await self._client.chat.completions.create(
            model=self._config.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_input},
            ],
            temperature=0,
        )
        return response.choices[0].message.content.strip()

    async def verify_result(
        self, user_input: str, sql: str, sample_rows: list[list] | None = None
    ) -> bool:
        """调用 LLM 验证生成的 SQL 或结果是否与用户意图匹配"""
        ...

    async def close(self) -> None:
        await self._client.close()
```

### 5.5 Prompt 构建 — `llm/prompt.py`

实现两阶段 Schema 筛选和分层 Prompt 构建。

```python
from mysql_mcp.models.schema import DatabaseSchema, SchemaCache


SYSTEM_TEMPLATE = """You are an expert MySQL SQL generator. Given a natural language query \
and the database schema below, generate a single SELECT statement.

Rules:
- Only generate SELECT statements
- Never use INTO OUTFILE or INTO DUMPFILE
- Always include a LIMIT clause (max {max_limit})
- Use standard MySQL syntax
- Respond with ONLY the SQL statement, no explanation

Database: {database}
"""


class PromptBuilder:
    """Prompt 构建器，负责两阶段 Schema 筛选和 Prompt 组装"""

    def __init__(self, schema_cache: SchemaCache, max_limit: int = 1000) -> None:
        self._cache = schema_cache
        self._max_limit = max_limit

    def build_system_prompt(
        self, database: str, candidate_tables: list[str] | None = None
    ) -> str:
        """构建系统 Prompt，包含分层 Schema 上下文"""
        ...

    def find_candidate_tables(self, user_input: str, database: str) -> list[str]:
        """第一阶段：从用户输入提取关键词，匹配候选表

        匹配策略：
        1. 直接匹配：用户输入中出现的表名/列名
        2. 关键词匹配：业务关键词 vs 表注释/列名/列注释
        3. 外键扩展：候选表关联的其他表
        """
        ...

    def _format_detailed_schema(self, tables: list[str], db: DatabaseSchema) -> str:
        """详细层：完整 Schema 文本（列名、类型、注释、索引、外键）"""
        ...

    def _format_summary_schema(self, tables: list[str], db: DatabaseSchema) -> str:
        """概要层：简化 Schema 文本（仅列名和类型）"""
        ...

    def _format_table_index(self, db: DatabaseSchema) -> str:
        """索引层：所有表名列表"""
        ...
```

### 5.6 SQL 安全校验 — `security/validator.py`

基于 sqlglot 的 AST 分析，确保只允许安全的 SELECT 语句。

```python
import sqlglot
from sqlglot import exp


class SQLValidationError(Exception):
    """SQL 校验失败时抛出"""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(f"SQL validation failed: {reason}")


class SQLValidator:
    """基于 sqlglot 的 SQL 安全校验器"""

    # 禁止的 AST 节点类型
    FORBIDDEN_STATEMENTS = {
        exp.Insert, exp.Update, exp.Delete, exp.Replace,
        exp.Create, exp.Alter, exp.Drop, exp.Truncate,
        exp.Grant, exp.Revoke,
    }

    # 禁止的函数名
    FORBIDDEN_FUNCTIONS = {"LOAD_FILE", "INTO OUTFILE", "INTO DUMPFILE"}

    def validate(self, sql: str, max_limit: int = 1000) -> str:
        """校验 SQL，通过则返回清洗后的 SQL，否则抛出 SQLValidationError

        校验步骤：
        1. 解析 SQL → AST（使用 MySQL 方言）
        2. 确保只解析出一条语句
        3. 确保是 SELECT 语句
        4. 检查 AST 中是否包含禁止的节点类型
        5. 检查是否包含禁止的函数调用
        6. 确保 LIMIT 存在且不超过 max_limit
        """
        ...

    def _parse_single(self, sql: str) -> exp.Expression:
        """解析 SQL，确保只有一条语句"""
        statements = sqlglot.parse(sql, read="mysql")
        if len(statements) != 1 or statements[0] is None:
            raise SQLValidationError("Only single SQL statement is allowed")
        return statements[0]

    def _check_statement_type(self, tree: exp.Expression) -> None:
        """确保是 SELECT 语句且不含禁止的子句"""
        if not isinstance(tree, exp.Select):
            raise SQLValidationError("Only SELECT statements are allowed")

        for forbidden_type in self.FORBIDDEN_STATEMENTS:
            if tree.find(forbidden_type):
                raise SQLValidationError(
                    f"Forbidden statement type: {forbidden_type.__name__}"
                )

    def _check_forbidden_functions(self, tree: exp.Expression) -> None:
        """检查是否包含禁止的函数"""
        for func in tree.find_all(exp.Anonymous):
            if func.name.upper() in self.FORBIDDEN_FUNCTIONS:
                raise SQLValidationError(f"Forbidden function: {func.name}")

    def _ensure_limit(self, tree: exp.Expression, max_limit: int) -> exp.Expression:
        """确保 LIMIT 存在且不超过上限，不存在则自动添加 LIMIT max_limit"""
        ...
```

### 5.7 AI 结果验证 — `llm/validator.py`

```python
from mysql_mcp.llm.client import LLMClient


class AIResultValidator:
    """AI 辅助的结果验证器"""

    def __init__(self, llm_client: LLMClient) -> None:
        self._client = llm_client

    async def verify_sql_relevance(
        self, user_input: str, sql: str
    ) -> bool:
        """验证生成的 SQL 与用户意图的相关性"""
        ...

    async def verify_result_quality(
        self, user_input: str, sql: str, sample_rows: list[list]
    ) -> bool:
        """验证查询结果是否与用户意图匹配"""
        ...
```

---

## 6. MCP Tools 实现

### 6.1 Tool 注册模式

所有 Tool 在各自模块中定义为独立函数，在 `server.py` 中统一注册。

```python
# server.py 中的注册方式
from mysql_mcp.tools import query, list_databases, describe_schema, execute_sql

mcp.tool(query)
mcp.tool(list_databases)
mcp.tool(describe_schema)
mcp.tool(execute_sql)
```

### 6.2 `query` Tool — `tools/query.py`

```python
from fastmcp import Context

from mysql_mcp.models.response import BothResponse, SQLResponse, SQLResult


async def query(
    natural_language: str,
    database: str | None = None,
    return_type: str = "result",
    ctx: Context = None,
) -> dict:
    """将自然语言查询转换为 SQL 并执行。

    Args:
        natural_language: 用户的自然语言查询描述
        database: 目标数据库名（可选，不提供则自动推断）
        return_type: 返回类型 sql/result/both，默认 result
    """
    config = ctx.lifespan_context["config"]
    pool = ctx.lifespan_context["pool"]
    schema_manager = ctx.lifespan_context["schema_manager"]
    llm_client = ctx.lifespan_context["llm_client"]

    # 1. 识别目标数据库
    db_name = _resolve_database(database, natural_language, schema_manager, config)

    # 2. 两阶段筛选候选表
    prompt_builder = PromptBuilder(schema_manager.cache, config.max_limit)
    candidates = prompt_builder.find_candidate_tables(natural_language, db_name)

    # 3. 构建 Prompt 并调用 LLM 生成 SQL
    system_prompt = prompt_builder.build_system_prompt(db_name, candidates)
    raw_sql = await llm_client.generate_sql(system_prompt, natural_language)

    # 4. SQL 安全校验
    validator = SQLValidator()
    sql = validator.validate(raw_sql, config.max_limit)

    # 5. 试执行
    columns, rows = await execute_query(pool, sql, db_name, config.query_timeout)

    # 6. AI 结果验证（可选，基于配置）
    ...

    # 7. 根据返回模式构造响应
    ...
```

### 6.3 `list_databases` Tool — `tools/list_databases.py`

```python
async def list_databases(ctx: Context) -> dict:
    """列出当前可访问的所有数据库。"""
    schema_manager = ctx.lifespan_context["schema_manager"]
    return {"databases": list(schema_manager.cache.databases.keys())}
```

### 6.4 `describe_schema` Tool — `tools/describe_schema.py`

```python
async def describe_schema(
    database: str,
    table: str | None = None,
    ctx: Context = None,
) -> dict:
    """描述指定数据库或表的 schema 信息。

    Args:
        database: 数据库名
        table: 表名（可选，不提供则返回该库所有表概览）
    """
    schema_manager = ctx.lifespan_context["schema_manager"]
    ...
```

### 6.5 `execute_sql` Tool — `tools/execute_sql.py`

```python
async def execute_sql(
    sql: str,
    database: str | None = None,
    ctx: Context = None,
) -> dict:
    """直接执行用户提供的 SQL（经过安全校验后执行）。

    Args:
        sql: 要执行的 SQL 语句
        database: 目标数据库名（可选）
    """
    config = ctx.lifespan_context["config"]
    pool = ctx.lifespan_context["pool"]

    validator = SQLValidator()
    validated_sql = validator.validate(sql, config.max_limit)
    columns, rows = await execute_query(pool, validated_sql, database, config.query_timeout)
    ...
```

---

## 7. 处理流程详解

### 7.1 Query 处理流水线

```
query(natural_language, database?, return_type?)
│
├─ Step 1: 数据库识别
│  ├─ 显式指定 → 使用指定数据库
│  ├─ 表名唯一 → 自动推断
│  └─ 无法推断 → 使用 default_database 或报错
│
├─ Step 2: 候选表筛选（两阶段）
│  ├─ 提取关键词 → 匹配表名/列名/注释
│  ├─ 外键扩展 → 纳入关联表
│  └─ 兜底 → 全部表名列表
│
├─ Step 3: Prompt 构建 + LLM 调用
│  ├─ 分层 Schema：详细层 + 概要层 + 索引层
│  ├─ System Prompt：角色 + Schema + 规则
│  └─ AsyncOpenAI.chat.completions.create(temperature=0)
│
├─ Step 4: SQL 安全校验（sqlglot AST）
│  ├─ 解析 → 单语句检查
│  ├─ 类型检查 → 仅允许 SELECT
│  ├─ 禁止节点 → INSERT/UPDATE/DELETE/DDL/DCL
│  ├─ 禁止函数 → LOAD_FILE/INTO OUTFILE
│  └─ LIMIT 检查 → 确保存在且 ≤ max_limit
│
├─ Step 5: 试执行
│  ├─ EXPLAIN → 检查执行计划
│  ├─ 执行查询 → 验证语法正确
│  └─ 超时保护 → max_execution_time
│
├─ Step 6: AI 结果验证（可选）
│  ├─ SQL 相关性 → 重试最多 3 次
│  └─ 结果合理性 → 说明或优化
│
└─ Step 7: 构造响应
   ├─ sql → SQLResponse
   ├─ result → SQLResult
   └─ both → BothResponse
```

### 7.2 错误处理策略

| 场景 | 处理方式 |
|---|---|
| 数据库连接失败 | 启动时失败并退出，运行时返回错误信息 |
| OpenAI 调用失败 | 指数退避重试 3 次，仍失败则返回错误信息 |
| SQL 校验失败 | 返回具体违规原因，不执行 SQL |
| SQL 执行超时 | 终止查询，返回超时提示 |
| SQL 执行报错 | 返回数据库原始错误信息 |
| Schema 刷新失败 | 记录日志，继续使用缓存数据 |

---

## 8. 入口与运行

### 8.1 `__main__.py`

```python
import logging

from mysql_mcp.server import mcp
from mysql_mcp.config import AppConfig


def main() -> None:
    config = AppConfig()
    logging.basicConfig(
        level=getattr(logging, config.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    mcp.run()


if __name__ == "__main__":
    main()
```

### 8.2 MCP Client 配置示例

```json
{
  "mcpServers": {
    "mysql": {
      "command": "python",
      "args": ["-m", "mysql_mcp"],
      "env": {
        "MYSQL_HOST": "localhost",
        "MYSQL_PORT": "3306",
        "MYSQL_USER": "readonly",
        "MYSQL_PASSWORD": "secret",
        "OPENAI_API_KEY": "sk-...",
        "ALLOWED_DATABASES": "[\"shop\", \"analytics\"]"
      }
    }
  }
}
```

---

## 9. 依赖管理 — `pyproject.toml`

```toml
[project]
name = "mysql-mcp"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "fastmcp>=3.0",
    "aiomysql>=0.2",
    "sqlglot[rs]>=26.0",
    "openai>=1.0",
    "pydantic>=2.0",
    "pydantic-settings>=2.0",
]

[project.scripts]
mysql-mcp = "mysql_mcp.__main__:main"
```

> 注：`sqlglot[rs]` 使用 Rust 加速的解析器后端，提升 SQL 解析性能。Pydantic 2.x 已是 FastMCP 的依赖，无需重复安装，但为了语义明确保留声明。

---

## 10. 关键设计决策

| 决策 | 选择 | 理由 |
|---|---|---|
| 异步 vs 同步 | 全异步 | aiomysql + AsyncOpenAI + FastMCP 原生支持异步，避免阻塞事件循环 |
| 连接池 vs 单连接 | 连接池 | 支持并发查询，避免频繁创建/销毁连接的开销 |
| AST 校验 vs 正则匹配 | AST（sqlglot） | 正则无法可靠识别 SQL 语义，AST 可以准确判断语句类型 |
| 两阶段 Prompt vs 全量 Prompt | 两阶段筛选 | 大型数据库全量 Schema 导致 token 爆炸，两阶段有效控制 Prompt 大小 |
| Pydantic 模型 vs 原生 dict | Pydantic 模型 | 类型安全、自动校验、IDE 友好，与 FastMCP 的 schema 生成无缝集成 |
| 环境变量 vs 配置文件 | 环境变量（Pydantic Settings） | MCP 标准做法，敏感信息不落盘，与 Claude Desktop 配置格式一致 |
| 温度参数 | temperature=0 | SQL 生成需要确定性的输出，不应有随机性 |
