# Frontend Directory Structure

## Rules
- 通用组件放 `src/components/`，页面级组件放 `src/pages/`，业务复用逻辑放 `src/hooks/`
- API 调用必须在 `src/services/` 封装，禁止组件内裸 `fetch` / `axios`
- 类型定义放 `src/types/`（共享）或与组件同目录（局部），禁止散落
- 新增一级目录必须更新路由 / 入口索引与导航地图

## Patterns
- 组件目录按业务域分子目录（`components/order/`、`components/user/`）
- 页面与路由一一对应，路由配置集中在 `router.*`
- 资源文件（图片 / 字体）放 `src/assets/`，构建工具处理 hash 与压缩
- 测试文件与源码同目录（`Foo.test.tsx`）或镜像放 `tests/`

## Anti-Patterns
- 禁止在 `src/` 下随意新增未登记的一级目录
- 禁止页面与组件互相循环引用
- 禁止把仅本组件用的 hook / 类型上提到全局目录
