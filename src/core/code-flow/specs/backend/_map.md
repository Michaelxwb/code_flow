# Backend Retrieval Map

> AI 导航地图：定位后端代码结构和关键模块。可由 `/cf-learn --map` 重生成，建议按真实项目手动校准。

## Purpose

后端服务，负责 API 暴露、业务逻辑与数据持久化。默认假设为分层架构（API → Service → Model）。

## Architecture

- Framework: 任意 Web 框架（FastAPI / Express / Spring / Gin 等）
- ORM/Driver: 与数据库匹配的官方/主流驱动
- Database: 关系型为主（PostgreSQL / MySQL），可叠加缓存（Redis）
- Auth: Token-based（JWT / OAuth2 / Session）
- Async: 必要时引入消息队列或后台任务（Celery / Bull / BullMQ）

## Key Files

| File | Purpose |
|------|---------|
| `src/main.*` | 应用入口，初始化框架、路由、中间件 |
| `src/api/router.*` | 路由注册，统一前缀与版本 |
| `src/services/` | 业务逻辑实现，禁止跨层调用 ORM |
| `src/models/` | 数据模型定义（ORM / Schema） |
| `src/config/` | 配置加载，环境变量优先 |

## Module Map

```
src/
├── api/         # 接口层：路由 + 请求/响应 schema 校验
├── services/    # 业务逻辑层：纯函数为主，便于测试
├── models/      # 数据模型（ORM 或 ODM）
├── schemas/     # DTO / 请求响应类型
├── middleware/  # 认证、日志、限流、CORS
├── utils/       # 工具函数，无业务依赖
└── config/      # 配置与环境变量
```

## Data Flow

```
Request → Middleware(auth/log) → Router → Handler(API)
        → Service(业务) → Model(DB/Cache) → Response
```

## Navigation Guide

- 新增 API → `api/` 加路由 + `schemas/` 定义请求响应 + `services/` 实现业务
- 新增表 → `models/` 定义模型 + `migrations/` 加迁移脚本
- 错误处理 → 抛业务异常类，由中间件统一转 HTTP 响应
- 配置项 → `config/` 集中管理，禁止散落 `os.environ`/`process.env`
