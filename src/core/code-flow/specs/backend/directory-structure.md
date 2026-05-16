# Backend Directory Structure

## Rules
- 接口层放 `api/`，业务逻辑放 `services/`，数据模型放 `models/`，禁止跨层倒置依赖
- 入口文件（`main.*`）只做框架装配，不写业务代码
- 配置统一放 `config/`，禁止在业务代码中直接读 `os.environ` / `process.env`
- 常量集中放 `constants/`，按业务模块拆分（`constants/order.py`、`constants/user.py`），禁止在业务代码中散落硬编码字面量（魔法数字 / 字符串 / 状态码）
- 数据访问层独立放 `crud/` 或 `repositories/`，业务层依赖 CRUD 抽象，不直接依赖 ORM
- 新增一级目录必须同步更新导航地图与 `__init__` / `index` 索引

## Patterns
- 模块按业务域拆分（如 `services/order/`、`services/user/`），目录深度建议 ≤ 3 层
- 公共工具放 `utils/`，无业务依赖；与业务相关的 helper 放对应 service 子目录
- 常量命名用 UPPER_SNAKE_CASE，枚举优先使用语言原生 `Enum`
- 测试目录与源码同构（`tests/services/order/test_*`）

## Anti-Patterns
- 禁止在根目录堆放脚本与临时代码，临时脚本放 `scripts/` 并命名清晰
- 禁止在 `models/` 里写业务逻辑，模型仅定义结构与简单关联
- 禁止把常量直接写在业务代码里（如 `if status == 1` / `role == "admin"`），必须引用 `constants/` 中的命名常量
- 禁止单文件超过 500 行或单函数超过 50 行
