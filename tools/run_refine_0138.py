from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "refine_0138.py"

source = SCRIPT.read_text(encoding="utf-8")
source = source.replace(
    'text = text[:start] + replacement + "\\n"',
    'text = text[:start] + replacement',
    1,
)
source = source.replace(
    '# Self-clean staging infrastructure.\n'
    '(ROOT / ".github/workflows/refine-0138.yml").unlink(missing_ok=True)\n'
    'Path(__file__).unlink(missing_ok=True)\n',
    '# Staging cleanup is performed by the repository maintainer after the product commit.\n',
    1,
)

namespace = {
    "__file__": str(SCRIPT),
    "__name__": "__main__",
}
exec(compile(source, str(SCRIPT), "exec"), namespace, namespace)
