# Component Specs

## Rules
- Props 必须类型化（TS interface / PropTypes / defineProps），可选项给默认值
- 组件文件名与导出组件名一致，使用 PascalCase
- 单组件文件 ≤ 300 行，超出拆成子组件或提取 hook
- 组件内禁止直接修改 props，需改值通过事件 / 回调上抛

## Patterns
- 拆分容器组件（数据获取 / 状态）与展示组件（纯 UI），便于测试和复用
- 复用逻辑提取为 hook（`useXxx`）/ composable，禁止跨组件复制粘贴
- 列表渲染必须给 `key`，且 `key` 稳定唯一，避免使用数组索引
- 受控表单优先；非受控仅用于不需要回读值的场景
- 样式遵循设计系统：间距用 4 的倍数，强调色 ≤ 2 种

## Anti-Patterns
- 禁止在组件内直接修改 props 或 store 内部状态
- 禁止把大量逻辑塞进 JSX 表达式，复杂条件提取变量或子组件
- 禁止用 `index` 作为列表 `key`（顺序变更会触发错误复用）
- 禁止省略 `alt` / `aria-*` 等可访问性属性
