# MySQL MCP Server - 实现计划

## 实现原则

1. **自底向上**：先实现无依赖的数据层，再逐层向上构建
2. **每步可验证**：每个 Task 完成后都应有明确的验证手段
3. **依赖关系明确**：被依赖的模块先实现，避免后续返工

---

## Phase 1: 项目骨架与数据模型

### Task 1.1: 初始化项目结构与依赖

**目标**：创建 `pyproject.toml`、包目录结构、`.gitignore`

**创建文件**：
- `pyproject.toml`
- `.gitignore`
- `src/__init__.py`
- `src/db/__init__.py`
- `src/models/__init__.py`
- `src/llm/__init__.py`
- `src/security/__init__.py`
- `src/tools/__init__.py`

**实现内容**：
- `pyproject.toml`：项目元数据、依赖声明（fastmcp, aiomysql, sqlglot[rs], openai, pydantic, pydantic-settings）、入口点 `mysql-mcp = "src.__main__:main"`
- `.gitignore`：Python 标准 gitignore + `.env`
- 各 `__init__.py`：空文件或 `__version__ = "0.1.0"`

**验证**：`pip install -e .` 成功，`python -c "import src"` 无报错

**依赖**：无

---

### Task 1.2: 配置模型 — `config.py`

**目标**：实现 `MySQLConfig`、`OpenAIConfig`、`AppConfig`

**创建文件**：
- `src/config.py`
- `tests/test_config.py`

**实现内容**：
- `MySQLConfig(BaseSettings)`：host/port/user/password/charset/ssl/pool_min_size/pool_max_size/pool_recycle，环境变量映射
- `OpenAIConfig(BaseSettings)`：api_key/model/base_url/max_retries/timeout，环境变量映射
- `AppConfig(BaseSettings)`：组合 mysql + openai 配置，加 allowed_databases/default_database/schema_refresh_interval/query_timeout/max_limit/schema_token_budget/log_level
- 所有 Field 带默认值和环境变量 alias
- `ALLOWED_DATABASES` 需支持 JSON 字符串解析（`'["a","b"]'`），用 `@field_validator` 处理

**验证**：
- 通过环境变量设置配置后 `AppConfig()` 能正确读取
- 缺少必需环境变量时抛出 `ValidationError`
- 默认值正确

**依赖**：Task 1.1

---

### Task 1.3: Schema 数据模型 — `models/schema.py`

**目标**：实现 Schema 缓存的全部 Pydantic 模型

**创建文件**：
- `src/models/schema.py`
- `tests/test_schema_models.py`

**实现内容**：
- `ColumnInfo`：name/type/default/nullable/auto_increment/comment
- `IndexInfo`：name/columns/unique/index_type
- `ForeignKeyInfo`：name/columns/ref_table/ref_columns/on_delete/on_update
- `TriggerInfo`：name/event/timing/statement
- `TableSchema`：name/columns/indexes/foreign_keys/triggers/comment/updated_at
- `ViewSchema`：name/columns/definition/comment
- `EnumTypeInfo`：name/column_name/table_name/values
- `DatabaseSchema`：name/tables(dict)/views(dict)/enums
- `SchemaCache`：databases(dict)/table_index(dict)

**验证**：
- 模型能正确实例化和序列化
- `SchemaCache.model_validate()` 能从嵌套 dict 反序列化
- `table_index` 字段可独立更新

**依赖**：Task 1.1

---

### Task 1.4: 响应数据模型 — `models/response.py`

**目标**：实现 MCP Tool 返回值的 Pydantic 模型

**创建文件**：
- `src/models/response.py`
- `tests/test_response_models.py`

**实现内容**：
- `SQLResult`：sql/database/columns/rows/row_count/truncated
- `SQLResponse`：sql/database/explanation
- `BothResponse`：组合 SQLResponse + SQLResult 的字段
- `ListDatabasesResponse`：databases
- `DescribeSchemaResponse`：database/tables/views/enums
- `ErrorResponse`：error/message/detail（统一的错误响应）

**验证**：
- 各模型能正确实例化和 `.model_dump()`
- 边界情况：空 rows、truncated=True

**依赖**：Task 1.1

---

## Phase 2: 核心基础设施

### Task 2.1: 数据库连接池 — `db/pool.py`

**目标**：实现 aiomysql 连接池的创建、关闭和查询执行

**创建文件**：
- `src/db/pool.py`
- `tests/test_pool.py`

**实现内容**：
- `create_pool(config: MySQLConfig) -> aiomysql.Pool`：根据配置创建连接池
- `close_pool(pool: aiomysql.Pool)`：优雅关闭连接池
- `execute_query(pool, sql, database?, timeout?) -> tuple[list[str], list[tuple]]`：执行查询，先 `SET SESSION max_execution_time`，返回列名和行数据
- 连接失败时抛出 `ConnectionError` 并包含原始异常信息

**验证**：
- 单元测试：mock aiomysql，验证 `create_pool` 传入了正确参数
- 集成测试（可选）：连接真实 MySQL，执行 `SELECT 1`

**依赖**：Task 1.2

---

### Task 2.2: SQL 安全校验 — `security/validator.py`

**目标**：实现基于 sqlglot 的 SQL 安全校验器

**创建文件**：
- `src/security/validator.py`
- `tests/test_sql_validator.py`

**实现内容**：
- `SQLValidationError(Exception)`：带 `reason` 属性的自定义异常
- `SQLValidator` 类：
  - `validate(sql, max_limit=1000) -> str`：完整校验流程，返回清洗后的 SQL
  - `_parse_single(sql) -> exp.Expression`：解析单条语句，多条则报错
  - `_check_statement_type(tree)`：确保根节点是 `exp.Select`，AST 中无禁止节点
  - `_check_forbidden_functions(tree)`：扫描 `exp.Anonymous` 和 `exp.Var`，拦截危险函数
  - `_ensure_limit(tree, max_limit) -> exp.Expression`：无 LIMIT 则自动追加 `LIMIT max_limit`，有则检查不超过上限
  - `_check_into_clause(tree)`：检查是否有 `INTO OUTFILE` / `INTO DUMPFILE`
- `FORBIDDEN_STATEMENTS` 集合：Insert/Update/Delete/Replace/Create/Alter/Drop/Truncate/Grant/Revoke

**验证**（关键测试用例）：
- 合法 SELECT 通过
- `SELECT * FROM t` 自动追加 LIMIT
- `INSERT INTO t VALUES (1)` → 拒绝
- `UPDATE t SET a=1` → 拒绝
- `DELETE FROM t` → 拒绝
- `DROP TABLE t` → 拒绝
- `SELECT * FROM t INTO OUTFILE '/tmp/a'` → 拒绝
- `SELECT LOAD_FILE('/etc/passwd')` → 拒绝
- `SELECT 1; DROP TABLE t` → 拒绝（多语句）
- `SELECT * FROM t LIMIT 5000`（max_limit=1000）→ LIMIT 被修正为 1000
- 带子查询的复杂 SELECT 通过
- 带 JOIN / GROUP BY / HAVING 的 SELECT 通过

**依赖**：Task 1.1

---

### Task 2.3: Schema 管理器 — `db/schema.py`

**目标**：实现 Schema 发现、缓存、增量刷新和候选表筛选

**创建文件**：
- `src/db/schema.py`
- `tests/test_schema_manager.py`

**实现内容**：
- 定义 INFORMATION_SCHEMA 查询常量：
  - `_GET_ACCESSIBLE_DATABASES`：获取可访问数据库列表
  - `_GET_TABLES`：获取表名、注释、更新时间戳
  - `_GET_COLUMNS`：获取列信息
  - `_GET_INDEXES`：获取索引信息（GROUP_CONCAT 聚合）
  - `_GET_FOREIGN_KEYS`：获取外键信息
  - `_GET_VIEWS`：获取视图定义
  - `_GET_ENUMS`：获取 ENUM 类型信息
- `SchemaManager` 类：
  - `__init__(pool, config)`：初始化缓存和配置
  - `cache` property：返回 SchemaCache
  - `load_all()`：启动时全量加载所有数据库 Schema
  - `refresh_incremental()`：对比 UPDATE_TIME 增量刷新
  - `start_refresh_if_configured() -> asyncio.Task | None`：启动定时刷新
  - `_get_accessible_databases() -> list[str]`：执行 SQL 获取库列表，受 `allowed_databases` 过滤
  - `_load_database_schema(db_name) -> DatabaseSchema`：加载单库完整 Schema（tables + views + enums）
  - `_load_table_columns(db_name, table_name) -> list[ColumnInfo]`
  - `_load_table_indexes(db_name, table_name) -> list[IndexInfo]`
  - `_load_table_foreign_keys(db_name, table_name) -> list[ForeignKeyInfo]`
  - `_load_table_triggers(db_name, table_name) -> list[TriggerInfo]`（MySQL 5.7+ 用 `information_schema.TRIGGERS`）
  - `_load_view_columns(db_name, view_name) -> list[ColumnInfo]`
  - `_fetch_current_table_timestamps(db_name) -> dict[str, tuple[float, str]]`
  - `_refresh_table(db_name, table_name, comment, updated_at)`：刷新单张表
  - `_rebuild_table_index()`：重建全局表名 → 数据库名映射
  - `find_candidate_tables(user_input, database) -> list[str]`：两阶段筛选
- `_parse_enum_values(column_type: str) -> list[str]`：从 `enum('a','b','c')` 解析值列表

**验证**：
- 单元测试：mock 数据库查询，验证 Schema 解析和缓存构建
- 验证 `find_candidate_tables` 的匹配逻辑：直接匹配、关键词匹配、外键扩展
- 验证增量刷新：新表/修改表/删除表
- 验证 `_rebuild_table_index` 正确性

**依赖**：Task 1.2, Task 1.3, Task 2.1

---

## Phase 3: LLM 集成

### Task 3.1: LLM 客户端 — `llm/client.py`

**目标**：封装 AsyncOpenAI，提供 SQL 生成和结果验证接口

**创建文件**：
- `src/llm/client.py`
- `tests/test_llm_client.py`

**实现内容**：
- `LLMClient` 类：
  - `__init__(config: OpenAIConfig)`：初始化 `AsyncOpenAI` 客户端
  - `generate_sql(system_prompt, user_input) -> str`：调用 `chat.completions.create`，temperature=0，返回去 markdown 代码块包裹后的纯 SQL
  - `verify_result(user_input, sql, sample_rows?) -> bool`：发送验证请求，解析返回的 yes/no
  - `close()`：关闭客户端
- SQL 提取逻辑：LLM 可能返回 ````sql\n...\n```` 或 ````...\n````，需要提取其中的纯 SQL 文本

**验证**：
- Mock OpenAI 响应，验证 `generate_sql` 正确提取 SQL
- 测试各种返回格式：纯 SQL、带 markdown 包裹、带解释文本
- 验证 `verify_result` 对 yes/no 的解析

**依赖**：Task 1.2

---

### Task 3.2: Prompt 构建 — `llm/prompt.py`

**目标**：实现两阶段 Schema 筛选和分层 Prompt 组装

**创建文件**：
- `src/llm/prompt.py`
- `tests/test_prompt_builder.py`

**实现内容**：
- `SYSTEM_TEMPLATE` 常量：系统角色 + 规则 + Few-shot 占位符
- `PromptBuilder` 类：
  - `__init__(schema_cache, max_limit=1000)`
  - `find_candidate_tables(user_input, database) -> list[str]`：
    1. 从用户输入中提取 token（按空格/标点分词，保留英文单词和中文词组）
    2. 直接匹配：token 是否匹配表名/列名（大小写不敏感）
    3. 关键词匹配：token 是否出现在表 comment/列 comment 中
    4. 外键扩展：候选表通过 foreign_keys 关联的表也纳入
    5. 兜底：候选为空时返回所有表名
  - `build_system_prompt(database, candidate_tables?) -> str`：
    1. 获取 `DatabaseSchema`
    2. 候选表 ≤ 20 → 详细层（完整 Schema 文本）
    3. 候选表 > 20 → 概要层（仅列名和类型）
    4. 始终附加索引层（所有表名列表）
    5. 拼接 SYSTEM_TEMPLATE + Schema 上下文
  - `_format_detailed_schema(tables, db) -> str`：`CREATE TABLE` 风格的 DDL 文本
  - `_format_summary_schema(tables, db) -> str`：`table_name(col1, col2, ...)` 格式
  - `_format_table_index(db) -> str`：逗号分隔的表名列表
  - `_estimate_tokens(text) -> int`：简单估算（chars / 4）

**验证**：
- 给定 SchemaCache，验证 `find_candidate_tables` 的匹配结果
- 验证 `build_system_prompt` 包含正确的 Schema 信息
- 验证分层逻辑：≤20 表用详细层，>20 用概要层
- 验证兜底：无匹配时返回全部表名

**依赖**：Task 1.3

---

### Task 3.3: AI 结果验证器 — `llm/validator.py`

**目标**：实现 AI 辅助的 SQL 和结果验证

**创建文件**：
- `src/llm/validator.py`
- `tests/test_ai_validator.py`

**实现内容**：
- `AIResultValidator` 类：
  - `__init__(llm_client: LLMClient)`
  - `verify_sql_relevance(user_input, sql) -> bool`：发送 SQL 和用户输入给 LLM，判断语义是否匹配
  - `verify_result_quality(user_input, sql, sample_rows) -> bool`：发送前 5 行结果 + 用户输入，判断结果是否合理
- 验证 Prompt 模板：简洁的 yes/no 判断格式

**验证**：
- Mock LLM 返回 "yes" / "no"，验证解析正确

**依赖**：Task 3.1

---

## Phase 4: MCP Tools 与 Server

### Task 4.1: 简单 Tools — `list_databases` + `describe_schema`

**目标**：实现两个无复杂处理逻辑的 Tool

**创建文件**：
- `src/tools/list_databases.py`
- `src/tools/describe_schema.py`
- `tests/test_tools_simple.py`

**实现内容**：

`list_databases`：
- 从 `ctx.lifespan_context["schema_manager"].cache` 读取数据库列表
- 返回 `ListDatabasesResponse`

`describe_schema`：
- 参数：`database: str`, `table: str | None = None`
- 从 SchemaCache 中读取对应数据库的 schema
- 如果指定了 table，返回单表详细 Schema
- 如果未指定 table，返回该库所有表名 + views + enums 的概览
- 数据库不存在时返回友好错误

**验证**：
- Mock lifespan context，验证返回数据结构正确
- 验证数据库不存在的错误处理

**依赖**：Task 1.3, Task 1.4, Task 2.3

---

### Task 4.2: execute_sql Tool

**目标**：实现用户直接提供 SQL 执行的 Tool

**创建文件**：
- `src/tools/execute_sql.py`
- `tests/test_execute_sql.py`

**实现内容**：
- 参数：`sql: str`, `database: str | None = None`
- 流程：SQLValidator.validate → execute_query → 构造 SQLResult
- 校验失败时返回 `ErrorResponse`，包含具体违规原因
- 执行失败时返回 `ErrorResponse`，包含数据库错误信息

**验证**：
- 合法 SQL 执行成功
- 非法 SQL（INSERT/DELETE 等）被拦截
- 数据库不存在时的错误处理

**依赖**：Task 2.1, Task 2.2, Task 1.4

---

### Task 4.3: query Tool（核心流水线）

**目标**：实现完整的自然语言查询流水线

**创建文件**：
- `src/tools/query.py`
- `tests/test_query.py`

**实现内容**：
- 参数：`natural_language: str`, `database: str | None = None`, `return_type: str = "result"`
- 流程：
  1. `_resolve_database()`：从用户输入或配置推断目标数据库
     - 显式指定 → 使用
     - 从输入中提取表名 → 查 `table_index` 匹配唯一数据库
     - 兜底 → `config.default_database` 或报错
  2. `prompt_builder.find_candidate_tables()` → 候选表
  3. `prompt_builder.build_system_prompt()` → System Prompt
  4. `llm_client.generate_sql()` → raw SQL
  5. `sql_validator.validate()` → 安全 SQL
  6. `execute_query()` → 试执行
  7. （可选）`ai_validator.verify_sql_relevance()` + `verify_result_quality()`
  8. 根据 `return_type` 构造响应：sql → SQLResponse / result → SQLResult / both → BothResponse
- LLM 生成失败重试：最多 3 次，每次失败重新生成
- SQL 校验失败重试：将校验错误反馈给 LLM 重新生成，最多 3 次
- 试执行失败重试：将执行错误反馈给 LLM 重新生成，最多 3 次

**验证**：
- Mock 全部依赖（schema_manager/llm_client/pool），验证完整流程
- 测试三种 return_type 的响应格式
- 测试数据库推断逻辑
- 测试重试逻辑：LLM 返回非法 SQL → 反馈后重新生成 → 最终成功

**依赖**：Task 2.2, Task 2.3, Task 3.1, Task 3.2, Task 3.3, Task 4.2

---

### Task 4.4: Server 组装 — `server.py` + `__main__.py`

**目标**：组装 FastMCP Server，接入 Lifespan 和 Tool 注册

**创建文件**：
- `src/server.py`
- `src/__main__.py`
- `tests/test_server.py`

**实现内容**：

`server.py`：
- `app_lifespan(server)` async context manager：
  1. `AppConfig()` 加载配置
  2. `create_pool(config.mysql)` 创建连接池
  3. `SchemaManager(pool, config)` + `load_all()` 加载 Schema
  4. `LLMClient(config.openai)` 初始化 LLM
  5. `schema_manager.start_refresh_if_configured()` 启动定时刷新
  6. yield 上下文字典
  7. finally: 停止刷新 → 关闭 LLM → 关闭连接池
- `mcp = FastMCP("MySQL MCP Server", lifespan=app_lifespan)`
- 注册四个 tools：`mcp.tool(query)`, `mcp.tool(list_databases)`, `mcp.tool(describe_schema)`, `mcp.tool(execute_sql)`

`__main__.py`：
- `main()` 函数：初始化 logging → `mcp.run()`
- `if __name__ == "__main__": main()`

**验证**：
- 启动服务 `python -m src`，通过 MCP Client 调用各 Tool
- 验证 Lifespan 正确初始化和清理
- 验证 `Ctrl+C` 能优雅关闭

**依赖**：Task 4.1, Task 4.2, Task 4.3

---

## Phase 5: 集成测试与优化

### Task 5.1: 集成测试

**目标**：端到端测试，使用真实 MySQL 和 Mock OpenAI

**创建文件**：
- `tests/conftest.py`：pytest fixtures（MySQL 连接池、测试数据库初始化）
- `tests/integration/test_query_e2e.py`
- `tests/integration/test_schema_discovery.py`
- `tests/integration/test_sql_security.py`

**实现内容**：
- `conftest.py`：
  - `mysql_pool` fixture：连接测试 MySQL
  - `test_db` fixture：创建/清理测试数据库和表
  - `mock_llm_client` fixture：返回预设 SQL
- 端到端测试场景：
  - 自然语言 → 正确 SQL → 查询结果
  - 涉及 JOIN 的复杂查询
  - 涉及聚合（GROUP BY + COUNT/AVG）的查询
  - 跨数据库查询
  - SQL 安全校验全部拒绝场景
  - Schema 发现和增量刷新
- 使用 `pytest-asyncio` 运行异步测试

**验证**：`pytest tests/integration/` 全部通过

**依赖**：Task 4.4

---

### Task 5.2: 错误处理与日志完善

**目标**：统一错误处理，完善日志记录

**修改文件**：
- `src/tools/query.py`
- `src/tools/execute_sql.py`
- `src/db/pool.py`
- `src/server.py`

**实现内容**：
- 定义统一的错误响应格式（`ErrorResponse`）
- 在 tool 函数中用 try/except 捕获异常并转换为 `ErrorResponse`
- 在关键路径添加 `logging.info/debug/warning`：
  - Schema 加载：数据库数量、表数量、耗时
  - SQL 生成：用户输入摘要、生成耗时、重试次数
  - SQL 执行：SQL 文本、执行耗时、行数
  - Schema 刷新：变更的表列表
- 确保 OpenAI 调用的指数退避重试（已有 `max_retries` 配置）

**验证**：
- 模拟各种异常，验证返回 `ErrorResponse` 格式一致
- 验证日志输出包含关键信息

**依赖**：Task 4.4

---

### Task 5.3: 健康检查与 graceful shutdown

**目标**：添加健康检查能力，确保优雅关闭

**修改文件**：
- `src/server.py`
- `src/__main__.py`

**实现内容**：
- 添加 `health_check` MCP Tool：
  - 检查 MySQL 连接：执行 `SELECT 1`
  - 检查 OpenAI 连接：可选（不实际调用，仅检查配置完整）
  - 返回状态信息
- 优雅关闭：
  - `__main__.py` 中注册 `SIGINT`/`SIGTERM` handler
  - Lifespan 的 finally 块确保所有资源清理
  - 日志记录关闭过程

**验证**：
- 调用 `health_check` 返回正确状态
- 强制终止时资源正确清理

**依赖**：Task 4.4

---

## Phase 6: 文档与发布

### Task 6.1: README 与使用文档

**目标**：编写 README 和使用说明

**修改文件**：
- `README.md`

**实现内容**：
- 项目介绍和功能说明
- 安装方式（pip / uv）
- 配置说明（环境变量列表）
- MCP Client 配置示例（Claude Desktop / Cursor）
- 开发指南（安装 dev 依赖、运行测试）

**依赖**：Task 5.3

---

## 依赖关系图

```
Phase 1 (骨架与模型)
  1.1 项目结构 ──┬── 1.2 config ──────┬── 2.1 连接池 ──────┬── 2.3 Schema管理器 ──┐
                 ├── 1.3 schema模型 ──┤                     │                       │
                 └── 1.4 响应模型 ────┘                     │                       │
                                                         │                       │
Phase 2 (核心基础设施)                                     │                       │
  2.2 SQL校验 ────────────────────────────────────────────┼───────────────────────┤
                                                         │                       │
Phase 3 (LLM 集成)                                       │                       │
  3.1 LLM客户端 ─── 3.3 AI验证器                         │                       │
  3.2 Prompt构建                                         │                       │
       │                                                │                       │
Phase 4 (Tools & Server)                                 │                       │
  4.1 简单Tools ─────────────────────────────────────────┼───────────────────────┤
  4.2 execute_sql ───────────────────────────────────────┘                       │
  4.3 query ─────────────────────────────────────────────┘───────────────────────┤
  4.4 Server组装 ────────────────────────────────────────────────────────────────┘
       │
Phase 5 (集成测试与优化)
  5.1 集成测试 ─── 5.2 错误处理 ─── 5.3 健康检查
       │
Phase 6 (文档)
  6.1 README
```

---

## Task 总览

| Task | 文件 | 预估复杂度 | 依赖 |
|------|------|-----------|------|
| 1.1 项目结构 | pyproject.toml, 包目录 | 低 | — |
| 1.2 配置模型 | config.py | 低 | 1.1 |
| 1.3 Schema 模型 | models/schema.py | 低 | 1.1 |
| 1.4 响应模型 | models/response.py | 低 | 1.1 |
| 2.1 连接池 | db/pool.py | 低 | 1.2 |
| 2.2 SQL 校验 | security/validator.py | **高** | 1.1 |
| 2.3 Schema 管理器 | db/schema.py | **高** | 1.2, 1.3, 2.1 |
| 3.1 LLM 客户端 | llm/client.py | 中 | 1.2 |
| 3.2 Prompt 构建 | llm/prompt.py | **高** | 1.3 |
| 3.3 AI 验证器 | llm/validator.py | 低 | 3.1 |
| 4.1 简单 Tools | tools/list_databases.py, tools/describe_schema.py | 低 | 1.3, 1.4, 2.3 |
| 4.2 execute_sql | tools/execute_sql.py | 中 | 2.1, 2.2, 1.4 |
| 4.3 query | tools/query.py | **高** | 2.2, 2.3, 3.1, 3.2, 3.3, 4.2 |
| 4.4 Server 组装 | server.py, __main__.py | 中 | 4.1, 4.2, 4.3 |
| 5.1 集成测试 | tests/integration/ | **高** | 4.4 |
| 5.2 错误处理 | 多文件修改 | 中 | 4.4 |
| 5.3 健康检查 | server.py, __main__.py | 低 | 4.4 |
| 6.1 README | README.md | 低 | 5.3 |

**高复杂度 Task**（建议重点关注）：2.2 SQL 校验、2.3 Schema 管理器、3.2 Prompt 构建、4.3 query 流水线、5.1 集成测试

---

## 开发顺序建议

按以下顺序实现，每组内的 Task 可并行：

```
1.1 → (1.2 ‖ 1.3 ‖ 1.4) → (2.1 ‖ 2.2 ‖ 3.1 ‖ 3.2) → 2.3 → (3.3 ‖ 4.1) → 4.2 → 4.3 → 4.4 → (5.1 ‖ 5.2 ‖ 5.3) → 6.1
```

`‖` 表示可并行，`→` 表示串行依赖。
