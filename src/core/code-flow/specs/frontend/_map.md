# Frontend Retrieval Map

> AI 导航地图：帮助快速定位前端代码结构和关键模块。本文件由 cf-learn --map 生成，可手动补充。

## Purpose

[一句话描述前端在本项目中的角色，如：基于 React 的单页应用，负责用户交互和数据展示]

## Architecture

[技术栈和核心架构模式]

- Framework: [React/Vue/Angular/...]
- State: [Redux/Zustand/Pinia/...]
- Routing: [React Router/Vue Router/...]
- Styling: [Tailwind/CSS Modules/styled-components/...]
- Build: [Vite/Webpack/Next.js/...]

## Key Files

| File | Purpose |
|------|---------|
| `src/App.tsx` | 根组件，挂载路由和全局 Provider |
| `src/main.tsx` | 应用入口，渲染 Root |

## Module Map

[按业务域列出模块及其职责，标注入口文件]

```
src/
├── components/    # 通用 UI 组件
├── pages/         # 页面组件（路由级）
├── hooks/         # 业务复用逻辑
├── stores/        # 状态管理
├── services/      # API 调用层
├── utils/         # 工具函数
└── types/         # 类型定义
```

## Data Flow

[关键数据流向，如：用户操作 → Action → Store → Component 重渲染]

## Navigation Guide

- 新增页面 → `src/pages/` + 路由配置
- 新增组件 → `src/components/`，按功能域分子目录
- API 调用 → `src/services/`，不在组件内直接 fetch
- 状态管理 → `src/stores/`，组件通过 hook 消费
