"""Read-only syntax and local Markdown-link checks. No external services."""
import ast
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]


def main():
    sources = [*ROOT.glob("*.py")]
    for folder in ("services", "models", "scripts", "tests"):
        sources.extend((ROOT / folder).glob("*.py"))
    for path in sources:
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path.relative_to(ROOT)))
    checked = 0
    for path in [ROOT / "README.md", *(ROOT / "docs").rglob("*.md")]:
        for target in re.findall(r"\[[^\]]*\]\(([^)]+)\)", path.read_text(encoding="utf-8")):
            target = target.strip("<>")
            if urlsplit(target).scheme or target.startswith("#"):
                continue
            local = unquote(target.split("#", 1)[0])
            if local and not (path.parent / local).exists():
                raise ValueError(f"Broken local link in {path.relative_to(ROOT)}: {local}")
            checked += 1
    print(f"Syntax checked: {len(sources)} Python files. Local Markdown links checked: {checked}.")


if __name__ == "__main__":
    main()
