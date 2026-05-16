# Backend Platform Rules

## Rules
- API 变更必须保持向后兼容；破坏性变更走新版本路径（`/v2/...`）并保留旧版本至少一个发布周期
- 配置项分环境管理（dev / staging / prod），敏感值走密钥管理服务，禁止入库
- 新增外部依赖必须更新部署文档与 `requirements` / `package.json` 锁文件
- 灰度 / 实验性功能必须由 feature flag 控制，默认关闭
- API 响应必须走统一封装：`success(data)` / `fail(code, message?)`，handler 禁止手写 `{code, message, data}` 字面量
- 错误码 → message 映射定义为常量，按业务模块拆分（`errors/order.py`、`errors/user.py`），错误码全局唯一，禁止重复

## Patterns
- API 响应统一结构：`{ code, message, data }`（`code=0` 表示成功），全项目一致
- 错误码命名空间：模块前缀 + 顺序号（如订单错误码 `10xxx`、用户 `20xxx`），便于定位归属
- 异常 → 错误码：自定义业务异常类携带 `code`，由中间件统一转 `fail(code)` 响应
- 配置加载优先级：环境变量 > 配置文件 > 默认值
- 健康检查端点（`/healthz`、`/readyz`）必须独立于业务认证
- 部署前跑 smoke test，覆盖核心路径

## Anti-Patterns
- 禁止在生产环境开启 `DEBUG` / 详细堆栈输出
- 禁止把 secret 写进代码库或 dev 配置文件
- 禁止破坏性 API 变更不通知调用方直接发布
- 禁止 feature flag 长期遗留，上线稳定后必须清理
- 禁止在 handler 里直接拼响应结构或硬编码错误 message，必须引用 `errors/` 常量并走 `success / fail` 封装
