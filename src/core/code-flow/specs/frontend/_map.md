# Frontend Retrieval Map

> AI 导航地图：定位前端代码结构和关键模块。可由 `/cf-learn --map` 重生成，建议按真实项目手动校准。

## Purpose

前端单页 / 多页应用，负责用户交互、页面渲染与 API 调用。默认假设为基于组件的 SPA。

## Architecture

- Framework: 任意主流框架（React / Vue / Svelte / Solid 等）
- Language: TypeScript（推荐）或 JavaScript + JSDoc
- State: 局部状态优先，跨组件共享走集中式（Redux / Zustand / Pinia）
- Routing: 框架官方路由（React Router / Vue Router / 文件路由）
- Styling: 原子化（Tailwind）或模块化（CSS Modules / styled-components）
- Build: Vite / Webpack / Next.js 等

## Key Files

| File | Purpose |
|------|---------|
| `src/main.*` | 应用入口，挂载 Root |
| `src/App.*` | 根组件，注册路由与全局 Provider |
| `src/router.*` | 路由定义 |
| `src/services/` | API 调用封装 |

## Module Map

```
src/
├── components/   # 通用 UI 组件，无业务依赖
├── pages/        # 页面级组件（路由叶子）
├── hooks/        # 业务复用逻辑（React）/ composables（Vue）
├── stores/       # 状态管理
├── services/     # API 调用层
├── utils/        # 纯函数工具
├── types/        # 类型定义
└── styles/       # 全局样式 / 主题
```

## Data Flow

```
User Action → Event Handler → Service(API) → Store/State → Re-render
```

## Navigation Guide

- 新增页面 → `pages/` 添加组件 + 路由配置
- 新增组件 → `components/` 按业务域分子目录，复用优先
- API 调用 → 统一走 `services/`，不在组件内裸 fetch
- 状态管理 → 跨组件状态走 `stores/`，组件通过 hook / composable 消费
