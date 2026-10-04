"""Native runtime project discovery and all-or-nothing path validation."""
import os
from pathlib import Path
from cf_patch import FileOperation


def project_root(cwd: str) -> str:
    directory = Path(cwd).absolute()
    for candidate in (directory, *directory.parents):
        if (candidate / ".code-flow/config.yml").is_file():
            return str(candidate)
    return ""


def validated_paths(root: str, cwd: str, operations: tuple[FileOperation, ...]) -> tuple[tuple[str, bool], ...]:
    paths: dict[str, bool] = {}
    for operation in operations:
        for path, deleted in ((operation.path, operation.kind in {"delete", "move"}),
                              (operation.destination, False)):
            if not path:
                continue
            absolute = Path(os.path.abspath(os.path.join(cwd, path)))
            if not absolute.is_relative_to(Path(root)) or not absolute.resolve().is_relative_to(Path(root).resolve()):
                raise ValueError(f"patch path is outside project: {path}")
            paths[str(absolute)] = deleted
    return tuple(paths.items())
