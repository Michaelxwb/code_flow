#!/usr/bin/env python3
import os


def main() -> None:
    try:
        project_root = os.getcwd()
        state_path = os.path.join(project_root, ".code-flow", ".inject-state")
        if os.path.exists(state_path):
            os.remove(state_path)
    except Exception:
        return


if __name__ == "__main__":
    main()
