"""Read the release source without importing the application or its dependencies."""
import ast
from pathlib import Path
import re


def release_version(root: Path) -> str:
    tree = ast.parse((root / "codexmeter/__init__.py").read_text(encoding="utf-8"))
    values = [node.value for node in tree.body if isinstance(node, ast.Assign)
              and any(isinstance(target, ast.Name) and target.id == "__version__"
                      for target in node.targets)]
    if len(values) != 1 or not isinstance(values[0], ast.Constant):
        raise ValueError("Release version must have exactly one literal assignment")
    value = values[0].value
    if not isinstance(value, str) or not re.fullmatch(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)", value):
        raise ValueError("Release version must have four numeric components")
    if any(int(part) > 65535 for part in value.split(".")):
        raise ValueError("Release version exceeds Windows file-version limits")
    return value


def firmware_header(root: Path, output: Path) -> Path:
    version = release_version(root)
    header = output / "release_version.h"
    text = '#pragma once\n#define CODEXMETER_RELEASE_VERSION "' + version + '"\n'
    output.mkdir(parents=True, exist_ok=True)
    if not header.exists() or header.read_text(encoding="utf-8") != text:
        header.write_text(text, encoding="utf-8", newline="\n")
    return header


if __name__ == "__main__":
    print(release_version(Path(__file__).resolve().parents[1]))
