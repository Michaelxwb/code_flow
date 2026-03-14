# cf-inject

手动注入指定领域或文件路径对应的规范（Hook 失败时回退）。

## Usage
- `/cf-inject frontend|backend`
- `/cf-inject path/to/file.ext`
- `/cf-inject --list-specs --domain=frontend`

## Command
- `python3 .code-flow/scripts/cf_inject.py [domain|file_path]`
- `python3 .code-flow/scripts/cf_inject.py --list-specs --domain=frontend`
