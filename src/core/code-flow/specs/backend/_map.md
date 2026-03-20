# Backend Retrieval Map

> AI 导航地图：帮助快速定位后端代码结构和关键模块。本文件由 cf-learn --map 生成，可手动补充。

## Purpose

[一句话描述后端在本项目中的角色，如：基于 FastAPI 的 RESTful 服务，负责业务逻辑和数据持久化]

## Architecture

[技术栈和核心架构模式]

- Framework: [FastAPI/Express/Gin/...]
- ORM: [SQLAlchemy/Prisma/GORM/...]
- Database: [PostgreSQL/MySQL/MongoDB/...]
- Auth: [JWT/OAuth2/Session/...]
- Queue: [Celery/Bull/...]

## Key Files

| File | Purpose |
|------|---------|
| `src/main.py` | 应用入口，启动服务 |
| `src/api/router.py` | 路由注册，API 版本管理 |
| `src/models/base.py` | ORM 基类和通用字段 |

## Module Map

[按职责分层列出模块]

```
src/
├── api/           # 接口层（路由 + 请求/响应校验）
├── services/      # 业务逻辑层
├── models/        # 数据模型（ORM）
├── schemas/       # 数据传输对象（DTO）
├── middleware/     # 中间件（认证、日志、限流）
├── utils/         # 工具函数
└── config/        # 配置管理
```

## Data Flow

[请求处理链路]

```
Request → Middleware(auth/log) → Router → Handler → Service → Model/DB → Response
```

## Navigation Guide

- 新增 API → `api/` 添加路由 + `services/` 添加业务逻辑
- 新增表 → `models/` 定义 ORM + migration 脚本
- 错误处理 → 使用统一错误类，middleware 捕获
- 配置项 → `config/` 管理，环境变量注入
