# MySQL MCP Server - Product Requirements Document (PRD)

## 1. 概述

### 1.1 产品名称

MySQL MCP Server（以下简称 "mysql-mcp"）

### 1.2 产品定位

一个基于 Python 的 MCP (Model Context Protocol) Server，将用户的自然语言查询需求转化为 SQL 语句或直接返回查询结果。通过在启动时缓存数据库 schema 信息，并结合 OpenAI 大模型能力，实现安全、准确的自然语言到 SQL 的转换。

### 1.3 目标用户

- 需要查询 MySQL 数据库但不熟悉 SQL 的业务人员
- 希望快速获取数据的开发人员
- 通过 MCP 客户端（如 Claude Desktop、Cursor 等）与数据库交互的用户

### 1.4 核心价值

1. **降低使用门槛**：自然语言直接查询，无需编写 SQL
2. **安全可控**：只允许 SELECT 查询，杜绝数据篡改风险
3. **智能校验**：多层校验确保 SQL 正确性和结果有效性
4. **灵活返回**：按需返回 SQL 语句或查询结果

---

## 2. 功能需求

### 2.1 数据库 Schema 缓存

#### 2.1.1 启动时 Schema 发现

服务启动时，自动执行以下操作：

1. **连接 MySQL 实例**：根据配置的连接信息建立数据库连接
2. **发现可访问数据库**：查询当前用户有权限访问的所有数据库列表
3. **缓存 Schema 信息**：对每个可访问数据库，缓存以下元数据：
   - **Tables**：表名、列名、列类型、列默认值、是否可空、是否自增、注释
   - **Views**：视图名、视图定义（SELECT 语句）、列信息
   - **Indexes**：索引名、所属表、索引列、索引类型（PRIMARY / UNIQUE /普通）、是否可空
   - **Foreign Keys**：外键名、所属表、引用表、关联列
   - **Triggers**：触发器名、关联表、事件、时机、定义
   - **Enums/Types**：自定义类型名称及其允许值列表
4. **定期刷新**：支持配置定时刷新间隔，以感知数据库结构变更

#### 2.1.2 配置要求

| 配置项 | 说明 | 示例 |
|--------|------|------|
| `MYSQL_HOST` | MySQL 主机地址 | `localhost` |
| `MYSQL_PORT` | MySQL 端口 | `3306` |
| `MYSQL_USER` | 数据库用户名 | `readonly_user` |
| `MYSQL_PASSWORD` | 数据库密码 | `********` |
| `ALLOWED_DATABASES` | 允许访问的数据库列表（可选，为空则访问所有有权限的库） | `["shop", "analytics"]` |
| `SCHEMA_REFRESH_INTERVAL` | Schema 刷新间隔（秒，可选，默认 0 表示不刷新） | `3600` |
| `OPENAI_API_KEY` | OpenAI API Key | `sk-...` |
| `OPENAI_MODEL` | 使用的模型名称（可选，默认 `gpt-4o`） | `gpt-4o` |
| `OPENAI_BASE_URL` | OpenAI API 基础 URL（可选，用于兼容第三方服务） | `https://api.openai.com/v1` |

#### 2.1.3 Schema 缓存数据结构

缓存的 Schema 应组织为如下层次结构：

```
Schema Cache
├── database_1
│   ├── tables
│   │   ├── table_a
│   │   │   ├── columns: [{name, type, default, nullable, auto_increment, comment}]
│   │   │   ├── indexes: [{name, columns, type, unique}]
│   │   │   ├── foreign_keys: [{name, ref_table, ref_columns, on_delete, on_update}]
│   │   │   └── triggers: [{name, event, timing, statement}]
│   │   └── table_b
│   │       └── ...
│   ├── views
│   │   ├── view_x
│   │   │   ├── columns: [{name, type}]
│   │   │   └── definition: "SELECT ..."
│   │   └── ...
│   └── enums
│       └── status_enum: ["active", "inactive", "archived"]
├── database_2
│   └── ...
```

### 2.2 自然语言到 SQL 转换

#### 2.2.1 核心流程

```
用户输入（自然语言）
    │
    ▼
识别目标数据库（从用户描述或默认配置中推断）
    │
    ▼
构建 Prompt（用户输入 + 相关 Schema + Few-shot 示例）
    │
    ▼
调用 OpenAI 生成 SQL
    │
    ▼
SQL 安全校验（只允许 SELECT）
    │
    ▼
SQL 试执行（EXPLAIN 或 LIMIT 预查询）
    │
    ▼
结果验证（可选：调用 OpenAI 确认结果相关性）
    │
    ▼
返回 SQL 语句 或 返回查询结果
```

#### 2.2.2 Prompt 构建

在调用 OpenAI 时，构建的 Prompt 应包含以下内容：

1. **系统角色描述**：你是一个 MySQL SQL 专家，根据用户的自然语言描述生成准确的 SELECT 查询语句
2. **Schema 上下文**：相关数据库的表结构、列信息、关联关系、索引信息
3. **用户输入**：用户的自然语言查询需求
4. **约束规则**：
   - 只生成 SELECT 语句
   - 不使用 INTO OUTFILE / INTO DUMPFILE
   - 不使用子查询修改数据（INSERT/UPDATE/DELETE 子查询）
   - 添加合理的 LIMIT（防止返回过多数据）
   - 使用标准 MySQL 语法
5. **Few-shot 示例**：提供 2-3 个典型查询的输入输出示例

#### 2.2.3 目标数据库识别

- 如果用户在输入中明确指定了数据库名称，使用指定的数据库
- 如果用户输入中包含的表名只存在于一个数据库中，自动推断该数据库
- 如果无法推断且配置了默认数据库，使用默认数据库
- 如果无法推断且没有默认数据库，返回错误提示用户指定数据库

### 2.3 SQL 安全校验

#### 2.3.1 校验规则

生成的 SQL **必须**满足以下全部条件，否则拒绝执行：

| 规则 | 说明 |
|------|------|
| 仅允许 SELECT | 解析 SQL 语句，确保只包含 SELECT 操作 |
| 禁止写入操作 | 不允许 INSERT / UPDATE / DELETE / REPLACE / LOAD DATA |
| 禁止 DDL | 不允许 CREATE / ALTER / DROP / TRUNCATE / RENAME |
| 禁止 DCL | 不允许 GRANT / REVOKE |
| 禁止文件操作 | 不允许 INTO OUTFILE / INTO DUMPFILE / LOAD_FILE() |
| 禁止系统命令 | 不允许 SYSTEM / \! 命令 |
| 强制 LIMIT | 必须包含 LIMIT 子句，且上限不超过配置的最大值（默认 1000） |
| 禁止多语句 | 只允许单条 SQL 语句，禁止分号分隔的多语句执行 |

#### 2.3.2 校验方式

1. **语法解析校验**：使用 SQL 解析器（如 sqlglot）进行 AST 级别的语法分析，确保只包含 SELECT 语句
2. **关键词黑名单**：对解析后的 AST 进行关键词过滤，拦截所有禁止的操作
3. **白名单函数**：只允许使用安全的内置函数（聚合函数、字符串函数、日期函数等）

### 2.4 SQL 试执行与结果验证

#### 2.4.1 试执行

校验通过的 SQL 在正式返回前进行试执行：

1. **EXPLAIN 验证**：先执行 `EXPLAIN` 确认执行计划合理，不存在全表扫描等性能问题
2. **LIMIT 预查询**：带 LIMIT 执行 SQL，验证：
   - SQL 语法正确，可正常执行
   - 不抛出异常或错误
   - 返回结果集非空（如果用户没有明确要求可能为空的情况）
3. **超时保护**：设置查询超时时间（可配置，默认 30 秒），超时则终止并提示用户

#### 2.4.2 结果验证（AI 辅助）

可选地调用 OpenAI 对生成结果进行二次验证：

1. **SQL 相关性验证**：将用户原始输入和生成的 SQL 发送给 OpenAI，确认 SQL 语义与用户意图一致
2. **结果合理性验证**：将查询结果（前 N 行）和用户原始输入发送给 OpenAI，确认结果符合预期
3. **验证失败处理**：
   - 如果 SQL 相关性验证失败，重新生成 SQL（最多重试 3 次）
   - 如果结果合理性验证失败，尝试优化 SQL 或向用户说明可能的问题

### 2.5 结果返回

#### 2.5.1 返回模式

根据用户的输入意图，支持两种返回模式：

| 模式 | 说明 | 适用场景 |
|------|------|----------|
| `sql` | 只返回生成的 SQL 语句 | 用户想自己执行 SQL，或需要在其他工具中使用 |
| `result` | 返回 SQL 执行后的查询结果 | 用户想直接看到数据 |
| `both` | 同时返回 SQL 语句和查询结果 | 用户既想看 SQL 又想看结果 |

#### 2.5.2 返回格式

**SQL 模式返回：**

```json
{
  "sql": "SELECT id, name, email FROM users WHERE status = 'active' LIMIT 100;",
  "database": "shop",
  "explanation": "查询所有活跃状态的用户 ID、姓名和邮箱"
}
```

**Result 模式返回：**

```json
{
  "sql": "SELECT id, name, email FROM users WHERE status = 'active' LIMIT 100;",
  "database": "shop",
  "columns": ["id", "name", "email"],
  "rows": [
    [1, "Alice", "alice@example.com"],
    [2, "Bob", "bob@example.com"]
  ],
  "row_count": 2,
  "truncated": false
}
```

**Both 模式返回：**

```json
{
  "sql": "SELECT id, name, email FROM users WHERE status = 'active' LIMIT 100;",
  "database": "shop",
  "explanation": "查询所有活跃状态的用户 ID、姓名和邮箱",
  "columns": ["id", "name", "email"],
  "rows": [
    [1, "Alice", "alice@example.com"],
    [2, "Bob", "bob@example.com"]
  ],
  "row_count": 2,
  "truncated": false
}
```

### 2.6 MCP Tools 定义

#### 2.6.1 `query`

自然语言查询，返回 SQL 或查询结果。

**参数：**

| 参数名 | 类型 | 必需 | 说明 |
|--------|------|------|------|
| `natural_language` | string | 是 | 用户的自然语言查询描述 |
| `database` | string | 否 | 目标数据库名（不提供则自动推断） |
| `return_type` | string | 否 | 返回类型：`sql` / `result` / `both`（默认 `result`） |

**返回值：** 见 2.5.2

#### 2.6.2 `list_databases`

列出当前可访问的所有数据库。

**参数：** 无

**返回值：**

```json
{
  "databases": ["shop", "analytics", "logs"]
}
```

#### 2.6.3 `describe_schema`

描述指定数据库的 schema 信息。

**参数：**

| 参数名 | 类型 | 必需 | 说明 |
|--------|------|------|------|
| `database` | string | 是 | 数据库名 |
| `table` | string | 否 | 表名（不提供则返回该库所有表概览） |

**返回值：** 对应数据库或表的 schema 信息

#### 2.6.4 `execute_sql`

直接执行用户提供的 SQL（经过安全校验后执行）。

**参数：**

| 参数名 | 类型 | 必需 | 说明 |
|--------|------|------|------|
| `sql` | string | 是 | 要执行的 SQL 语句 |
| `database` | string | 否 | 目标数据库名 |

**返回值：** 同 Result 模式的返回格式

---

## 3. 非功能需求

### 3.1 安全性

| 需求 | 说明 |
|------|------|
| SQL 注入防护 | 通过 AST 解析确保只允许 SELECT，防止通过自然语言诱导生成恶意 SQL |
| 只读连接 | 推荐使用只读数据库用户连接，从数据库层面确保安全性 |
| 连接加密 | 支持 SSL/TLS 连接到 MySQL |
| API Key 保护 | OpenAI API Key 和 MySQL 密码等敏感信息通过环境变量注入，不硬编码 |
| 结果脱敏 | 可选配置：对包含敏感字段（如 password、secret、token）的列进行脱敏处理 |
| 访问控制 | 通过 `ALLOWED_DATABASES` 配置限制可访问的数据库范围 |

### 3.2 性能

| 需求 | 目标 |
|------|------|
| Schema 缓存加载 | 启动时 10 秒内完成所有数据库 Schema 缓存（100 张表以内） |
| SQL 生成 | OpenAI 调用到 SQL 生成的端到端时间 < 10 秒 |
| 查询执行 | 单次查询执行超时默认 30 秒，可配置 |
| 并发支持 | 支持异步处理，可同时处理多个查询请求 |
| 结果集大小 | 默认 LIMIT 1000，可配置，防止返回过多数据导致性能问题 |

### 3.3 可靠性

| 需求 | 说明 |
|------|------|
| 错误处理 | 对数据库连接失败、OpenAI 调用失败、SQL 执行失败等场景提供清晰的错误信息 |
| 重试机制 | OpenAI 调用支持重试（指数退避，最多 3 次） |
| 连接池 | 使用连接池管理数据库连接，避免频繁创建和销毁连接 |
| 日志记录 | 记录关键操作日志（查询历史、错误信息、性能指标） |
| 优雅关闭 | 收到终止信号时，等待进行中的请求完成后关闭 |

### 3.4 可维护性

| 需求 | 说明 |
|------|------|
| 配置化 | 所有可调参数（模型、超时、LIMIT 等）通过环境变量或配置文件管理 |
| 日志级别 | 支持 DEBUG / INFO / WARNING / ERROR 日志级别 |
| 健康检查 | 提供 health check 端点，检查数据库连接和 OpenAI 连接状态 |

---

## 4. 约束与假设

### 4.1 约束

1. **MySQL 版本**：支持 MySQL 5.7+ 和 MySQL 8.0+
2. **Python 版本**：Python 3.11+
3. **MCP 协议版本**：遵循最新的 MCP 协议规范
4. **只读操作**：本服务只提供数据查询能力，不提供任何数据修改能力
5. **网络要求**：需要能同时访问 MySQL 实例和 OpenAI API

### 4.2 假设

1. 用户使用的自然语言以中文和英文为主
2. 数据库 Schema 信息可以被完整读取（用户有 INFORMATION_SCHEMA 的访问权限）
3. OpenAI API 的响应时间和可用性满足基本使用需求
4. MCP 客户端（Claude Desktop 等）已正确配置并支持调用本服务

---

## 5. 里程碑

| 阶段 | 内容 | 交付物 |
|------|------|--------|
| M1: 核心功能 | Schema 缓存 + 自然语言转 SQL + 安全校验 + 结果返回 | 可运行的 MCP Server |
| M2: 智能增强 | AI 结果验证 + 重试优化 + Prompt 优化 | 更准确的查询结果 |
| M3: 生产就绪 | 日志 + 错误处理 + 健康检查 + 配置完善 | 可部署的服务 |
| M4: 测试与文档 | 单元测试 + 集成测试 + 使用文档 | 完整的测试覆盖和文档 |

---

## 6. 开放问题

| 编号 | 问题 | 状态 |
|------|------|------|
| Q1 | 是否需要支持多租户（多个 MySQL 实例）？ | **已确认：不需要。** 只需连接单个 MySQL 实例，通过 USE db 或全限定名查询不同数据库 |
| Q2 | 查询历史是否需要持久化存储？ | **已确认：不需要。** |
| Q3 | 是否需要支持 SQL 生成结果的流式返回？ | **已确认：不需要。** 查询最多返回 1000 条数据，非流式返回即可 |
| Q4 | 是否需要支持用户反馈机制（对生成结果打分）？ | **已确认：不需要。** |
| Q5 | Schema 缓存刷新策略：全量刷新 vs 增量刷新？ | **已确认：增量刷新。** 通过对比 `INFORMATION_SCHEMA` 的更新时间戳，只刷新发生变更的部分 |
| Q6 | 对于大型数据库（1000+ 张表），如何控制 Prompt 中 Schema 信息的大小？ | **已确认：采用两阶段 Schema 筛选。** 见 6.1 |
| Q7 | 是否需要支持存储过程和自定义函数的调用？ | **已确认：不需要。** |

### 6.1 大型数据库 Schema 筛选策略（Q6 详细方案）

当数据库表数量较多时，将全部 Schema 放入 Prompt 会导致 token 爆炸和生成质量下降。采用以下两阶段策略：

#### 第一阶段：候选表筛选

从用户输入中提取关键信息，匹配相关的表：

1. **直接匹配**：用户输入中提到的表名、列名，直接标记为候选
2. **关键词匹配**：从用户输入中提取业务关键词（如 "订单"、"用户"、"商品"），与表的 COMMENT、列名、列 COMMENT 进行模糊匹配
3. **关联扩展**：候选表通过外键关联的其他表也纳入候选列表
4. **兜底**：如果候选表数量为 0，则取该数据库下所有表名列表（仅表名，无详细 Schema）

#### 第二阶段：分层 Prompt 构建

根据候选结果，将 Schema 信息分层放入 Prompt：

| 层级 | 内容 | 条件 |
|------|------|------|
| 详细层 | 候选表的完整 Schema（列名、类型、注释、索引、外键） | 候选表数量 ≤ 20 |
| 概要层 | 候选表的简化 Schema（仅列名和类型） | 候选表数量 > 20 |
| 索引层 | 所有表的名称列表（仅表名） | 始终包含，供 LLM 了解全局结构 |

当详细层 + 概要层 + 索引层的总 token 数超过预设阈值（默认 4000 tokens）时，优先保留详细层，对概要层进行截断，并在 Prompt 中提示 LLM 可以通过 `describe_schema` 工具获取更多表的详细信息。
