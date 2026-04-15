# Institution

## 初步需求

主要的需求是使用 Python 构建一个 MySQL 的 mcp：用户使用自然语言描述查询需求，然后 mcp server 根据结果来返回一个 SQL 或者返回这个查询的结果。mcp 的服务在启动的时候，应该读取它都有哪些可以访问的数据库，并且缓存这些数据库的 schema，了解每个数据库下面都有哪些 table/view/types/index 等等，然后根据这些信息以及用户的输入去调用 OpenAI 的大模型来生成 SQL，之后 mcp server 应该需要校验这个 SQL 只允许查询的语句然后测试这个 SQL 确保它能够执行并且返回有意义的结果，这里也可以把用户输入生成的 SQL 或者返回结果的一部分来调用 OpenAI 来进行确认，以保证返回的结果有意义。最后根据用户的输入是返回 SQL 还是返回 SQL 查询之后的结果来返回相应的内容。根据以上需求构建一个详细的需求文档，等我 review 后再讨论设计。文档放在 ./specs/0001-mysql-mcp-prd.md 

gemini 研究：

帮我研究下这个需求如果使用 Python 来实现，应该用哪些库，为什么使用这些库

## 构建设计文档

根据 ./specs/0001-mysql-mcp-prd.md，使用 FastMCP/Asyncmysql/SQLGlot/Pydantic 以及 OpenAI 构建 mysql-mcp 的设计文档，文档放在 ./specs/0002-mysql-mcp-design.md 文件中

## 生成 CLAUDE.md

为当前项目生成 CLAUDE.md，要求：代码要符合 python best practice / idomatic python，符合 SOLID/DRY/YANGI 等设计思路，代码质量要高，性能要好

## 生成实现计划

根据 ./specs/0002-mysql-mcp-design.md 构建 mysql-mcp 的实现计划，文档放在 ./specs/0003-mysql-mcp-impl-plan.md 

## 构架测试数据

根据  @specs/0001-mysql-mcp-prd.md 在 ./fixtures 下构建三个有意义的数据，分别有少量、中等、大量的 table/view/types/index  等 schema，且有足够多的数据。生成这三个数据库的 SQL 文件，并构建 Makefile 来重建这些测试数据库