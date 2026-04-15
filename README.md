# mysql-mcp

MySQL MCP Server — 通过自然语言查询 MySQL 数据库，基于 OpenAI 将自然语言转换为 SQL 并执行。

## 功能

- 自然语言转 SQL，支持 SELECT 查询执行
- 自动数据库 schema 发现与缓存（支持增量刷新）
- SQL 安全校验：仅允许 SELECT，禁止写入操作，自动限制 LIMIT
- 两阶段 schema 过滤，优化 LLM prompt token 消耗
- 失败自动重试（最多 3 次），将错误反馈给 LLM 修正
- MCP 工具：query / execute_sql / list_databases / describe_schema / health_check

## 要求

- Python 3.11+
- MySQL 5.7+
- OpenAI API Key（或兼容接口）

## 安装

```bash
pip install -e ".[dev]"
```

## 配置

通过环境变量配置：

| 变量 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `MYSQL_HOST` | 否 | `localhost` | MySQL 地址 |
| `MYSQL_PORT` | 否 | `3306` | MySQL 端口 |
| `MYSQL_USER` | 是 | — | MySQL 用户名 |
| `MYSQL_PASSWORD` | 是 | — | MySQL 密码 |
| `MYSQL_CHARSET` | 否 | `utf8mb4` | 字符集 |
| `MYSQL_SSL` | 否 | `false` | 是否启用 SSL |
| `MYSQL_POOL_MIN_SIZE` | 否 | `2` | 连接池最小连接数 |
| `MYSQL_POOL_MAX_SIZE` | 否 | `10` | 连接池最大连接数 |
| `MYSQL_POOL_RECYCLE` | 否 | `3600` | 连接回收时间（秒） |
| `OPENAI_API_KEY` | 是 | — | OpenAI API Key |
| `OPENAI_MODEL` | 否 | `gpt-4o` | 模型名称 |
| `OPENAI_BASE_URL` | 否 | `None` | 自定义 API 地址（代理/自建服务） |
| `OPENAI_MAX_RETRIES` | 否 | `3` | API 最大重试次数 |
| `OPENAI_TIMEOUT` | 否 | `60` | API 超时（秒） |
| `ALLOWED_DATABASES` | 否 | `[]`（全部） | 允许访问的数据库，JSON 数组格式，如 `'["shop","analytics"]'` |
| `DEFAULT_DATABASE` | 否 | `None` | 默认数据库 |
| `SCHEMA_REFRESH_INTERVAL` | 否 | `0`（禁用） | Schema 自动刷新间隔（秒） |
| `QUERY_TIMEOUT` | 否 | `30` | 查询超时（秒） |
| `MAX_LIMIT` | 否 | `1000` | 返回行数上限 |
| `LOG_LEVEL` | 否 | `INFO` | 日志级别 |

## 启动

```bash
# 设置必填环境变量
export MYSQL_USER=root
export MYSQL_PASSWORD=admin123
export OPENAI_API_KEY=sk-xxx

# 如果使用自定义 OpenAI 接口
export OPENAI_BASE_URL=https://your-proxy.com/v1

# 启动服务（stdio 模式）
python -m src
```

## 在 Claude Desktop 中使用

在 `claude_desktop_config.json` 中添加：

```json
{
  "mcpServers": {
    "mysql": {
      "command": "python",
      "args": ["-m", "src"],
      "cwd": "/path/to/mysql-mcp",
      "env": {
        "MYSQL_USER": "root",
        "MYSQL_PASSWORD": "admin123",
        "OPENAI_API_KEY": "sk-xxx",
        "OPENAI_BASE_URL": "https://api.openai.com/v1"
      }
    }
  }
}
```

## MCP 工具说明

### query

自然语言查询，自动生成 SQL 并执行。

```
参数:
  natural_language: 自然语言查询（必填）
  database: 目标数据库（可选，自动推断）
  return_type: 返回类型 — "result"（默认）/ "sql" / "both"
```

### execute_sql

直接执行用户提供的 SQL（仅限 SELECT）。

```
参数:
  sql: SQL 语句（必填）
  database: 目标数据库（可选）
```

### list_databases

列出所有可访问的数据库。

### describe_schema

查看数据库或表的 schema 信息。

```
参数:
  database: 数据库名（必填）
  table: 表名（可选，省略则返回所有表概览）
```

### health_check

检查 MySQL 连接和 OpenAI 配置状态。

## 测试

```bash
# 运行全部测试
pytest

# 运行单个测试文件
pytest tests/test_sql_validator.py

# 运行指定测试
pytest tests/test_sql_validator.py -k "test_rejects_insert"
```

## 项目结构

```
src/
├── __init__.py
├── __main__.py         # 入口
├── config.py           # 配置
├── server.py           # FastMCP server
├── db/
│   ├── pool.py         # 连接池
│   └── schema.py       # Schema 管理
├── llm/
│   ├── client.py       # OpenAI 客户端
│   ├── prompt.py       # Prompt 构建
│   └── validator.py    # AI 结果校验
├── models/
│   ├── schema.py       # Schema 数据模型
│   └── response.py     # 响应模型
├── security/
│   └── validator.py    # SQL 安全校验
└── tools/
    ├── query.py
    ├── execute_sql.py
    ├── list_databases.py
    ├── describe_schema.py
    └── health_check.py
```

## License

MIT
