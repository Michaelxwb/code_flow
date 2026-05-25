# Project Guidelines

## Team Identity
- Team: [team name]
- Project: [project name]
- Language: [primary language]

## Core Principles
- All changes must include tests
- Single responsibility per function (<= 50 lines)
- No loose typing or silent exception handling
- Handle errors explicitly

## Forbidden Patterns
- Hard-coded secrets or credentials
- Unparameterized SQL
- Network calls inside tight loops

## Spec Loading
本项目使用 code-flow 两层规范体系。

**两层架构**：
- **Tier 0 `_map.md`（导航地图）**：项目结构、关键文件、数据流。你手动读取，帮助理解代码在哪里。
- **Tier 1 约束规范**：编码规则、模式、反模式。由 code-flow 插件自动注入，你无需手动加载。

**你的职责**：
1. 从问题判断领域：
   - **frontend**：components、pages、hooks、styles、UI、.tsx/.jsx/.css
   - **backend**：services、API、database、models、logging、.py/.go
2. 读取 `.code-flow/specs/<domain>/_map.md` 获取导航上下文
3. 约束规范由 code-flow 插件在你发送消息时自动注入——不要手动读取
4. 问题跨多个领域时，读取所有匹配的 `_map.md`
5. 没有匹配领域时，跳过规范加载

不要询问用户加载哪些规范——系统自动处理约束注入。

## Task Documents (cf-task workflow)

- `.code-flow/specs/shared/` holds PRD/design templates used by `/cf-task:prd` and `/cf-task:align`
- Workflow: `/cf-task:prd` → `.prd.md` → `/cf-task:align <.prd.md>` → `.design.md` → `/cf-task:plan <.design.md>` → tasks
- Templates are read by the commands themselves; you do not need to pre-load them
