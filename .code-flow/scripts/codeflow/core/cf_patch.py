"""Shared structured patch parser for native platform entries."""
from dataclasses import dataclass, replace


@dataclass(frozen=True)
class FileOperation:
    kind: str
    path: str
    destination: str = ""


def parse_patch(command: str) -> tuple[FileOperation, ...]:
    lines = command.splitlines()
    if len(lines) < 3 or lines[0] != "*** Begin Patch" or lines[-1] != "*** End Patch":
        raise ValueError("patch must contain a complete Begin/End envelope")
    operations: list[FileOperation] = []
    headers = {"*** Add File: ": "add", "*** Update File: ": "update", "*** Delete File: ": "delete"}
    for line in lines[1:-1]:
        header = next((prefix for prefix in headers if line.startswith(prefix)), "")
        if header:
            path = line[len(header):]
            if not path or "\x00" in path:
                raise ValueError("patch file path is empty or invalid")
            operations.append(FileOperation(headers[header], path))
        elif line.startswith("*** Move to: "):
            if not operations or operations[-1].kind != "update" or not line[13:]:
                raise ValueError("Move to must follow an Update File")
            operations[-1] = replace(operations[-1], kind="move", destination=line[13:])
        elif not operations or (line and not line.startswith(("+", "-", " ", "@@", "*** End of File"))):
            raise ValueError("unrecognized patch syntax")
    if not operations:
        raise ValueError("patch contains no file operations")
    return tuple(operations)
