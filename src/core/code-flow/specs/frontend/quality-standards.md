# Frontend Quality Standards

## Rules
- TypeScript 项目禁止使用 `any`，未知类型用 `unknown` 并显式收敛
- 组件统一使用函数组件（React）/ 组合式 API（Vue 3），禁止类组件新增
- 关键交互（提交 / 删除 / 支付）必须有错误提示与 loading 状态
- 异步操作必须处理 loading / success / error 三态，禁止只处理成功路径
- 提交前必须通过 lint 与 type check，禁止 `eslint-disable` / `@ts-ignore` 滥用

## Patterns
- 跨组件状态用集中式状态管理，避免 prop drilling 超过 2 层
- 表单校验在提交前完成，错误信息定位到具体字段
- 网络请求统一处理 401 / 403 / 5xx，避免每个调用方重复
- 关键路径补端到端测试或组件交互测试

## Anti-Patterns
- 禁止在 render / setup 中发起未受控的副作用（用 `useEffect` / `onMounted`）
- 禁止把后端错误直接抛给用户（如 SQL / stack trace）
- 禁止用 `// @ts-ignore` 绕过类型错误，必须修复或改为 `@ts-expect-error` 加注释
- 禁止在组件中直接修改 store 内部状态，必须走 action / mutation
