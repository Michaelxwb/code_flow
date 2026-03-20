# Backend Directory Structure

## Rules
- 服务入口放在 services/，接口层放在 api/。
- 数据模型放在 models/，禁止业务逻辑散落在入口文件。

## Patterns
- 模块按业务域拆分，保持目录深度可控。

## Anti-Patterns
- 禁止在根目录堆放脚本与临时代码。
