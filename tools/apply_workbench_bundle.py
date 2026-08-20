from __future__ import annotations

import base64
import gzip
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUNDLE_DIR = ROOT / "tools" / "workbench_bundle"

bundle_text = "".join(path.read_text(encoding="utf-8") for path in sorted(BUNDLE_DIR.glob("bundle_*.txt")))
payload = json.loads(bundle_text)

for key, rel in {
    "ui": "apps/web/workbench-ui.js",
    "css": "apps/web/workbench.css",
    "index": "apps/web/index.html",
}.items():
    target = ROOT / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(gzip.decompress(base64.b64decode(payload[key])))

ui = ROOT / "apps/web/workbench-ui.js"
text = ui.read_text(encoding="utf-8")
text = text.replace(
    "/* MAIL-AGENT Workbench design prototype.\n   Runs on top of the real 0.13.9 app logic. No backend/security semantics are changed. */",
    "/* MAIL-AGENT Workbench UI. Presentation layer only; backend and security semantics stay unchanged. */",
)
ui.write_text(text, encoding="utf-8")

index = ROOT / "apps/web/index.html"
text = index.read_text(encoding="utf-8")
text = text.replace(
    '<script src="/assets/app.js?v=0.14.0" defer></script>\n  <script src="/assets/workbench-ui.js?v=0.14.0" defer></script>\n  <script src="/assets/startup-rescue.js?v=0.14.0" defer></script>',
    '<script src="/assets/app.js?v=0.14.0" defer></script>\n  <script src="/assets/startup-rescue.js?v=0.14.0" defer></script>\n  <script src="/assets/workbench-ui.js?v=0.14.0" defer></script>',
)
index.write_text(text, encoding="utf-8")

version_replacements = {
    "pyproject.toml": [('version = "0.13.9"', 'version = "0.14.0"')],
    "packaging/windows/MailAgent.iss": [('#define MyAppVersion "0.13.9"', '#define MyAppVersion "0.14.0"')],
    "packages/agent_core/mail_agent_core/identity.py": [('app_version: str = "0.13.9"', 'app_version: str = "0.14.0"')],
    "apps/web/desktop-links.js": [("const APP_VERSION = '0.13.9'", "const APP_VERSION = '0.14.0'")],
    "apps/gateway/mail_agent_gateway/main.py": [('APP_VERSION = "0.13.9"', 'APP_VERSION = "0.14.0"')],
    "apps/launcher/mail_agent_launcher/main.py": [('APP_VERSION = "0.13.9"', 'APP_VERSION = "0.14.0"')],
}
for rel, replacements in version_replacements.items():
    path = ROOT / rel
    source = path.read_text(encoding="utf-8")
    for old, new in replacements:
        if old not in source:
            raise SystemExit(f"Missing expected version marker in {rel}: {old}")
        source = source.replace(old, new)
    path.write_text(source, encoding="utf-8")

for rel in (
    "tests/test_recovery_contract.py",
    "tests/test_startup_nonblocking.py",
    "tests/test_windows_update_restart.py",
):
    path = ROOT / rel
    path.write_text(path.read_text(encoding="utf-8").replace("0.13.9", "0.14.0"), encoding="utf-8")

startup = ROOT / "tests/test_startup_nonblocking.py"
source = startup.read_text(encoding="utf-8")
source = source.replace('        "attention-center.js",\n', '')
source = source.replace(
    '        "desktop-links.js",\n',
    '        "desktop-links.js",\n        "workbench.css",\n        "workbench-ui.js",\n',
)
source = source.replace(
    '    assert index.index("/assets/startup-rescue.js?v=0.14.0") < index.index(\n        "/assets/mail-provider-setup.js?v=0.14.0"\n    )',
    '    assert index.index("/assets/startup-rescue.js?v=0.14.0") < index.index(\n        "/assets/workbench-ui.js?v=0.14.0"\n    )\n    assert index.index("/assets/workbench-ui.js?v=0.14.0") < index.index(\n        "/assets/mail-provider-setup.js?v=0.14.0"\n    )',
)
startup.write_text(source, encoding="utf-8")

(ROOT / "tests/test_attention_ui_contract.py").write_text(
    '''from __future__ import annotations\n\nimport shutil\nimport subprocess\nfrom pathlib import Path\n\nimport pytest\n\nROOT = Path(__file__).resolve().parents[1]\n\n\ndef test_attention_workbench_and_routes_are_wired():\n    index = (ROOT / "apps/web/index.html").read_text(encoding="utf-8")\n    js = (ROOT / "apps/web/workbench-ui.js").read_text(encoding="utf-8")\n    main = (ROOT / "apps/gateway/mail_agent_gateway/main.py").read_text(encoding="utf-8")\n    desktop = (ROOT / "apps/launcher/mail_agent_launcher/desktop_runtime.py").read_text(encoding="utf-8")\n\n    assert "/assets/workbench-ui.js?v=0.14.0" in index\n    assert "/assets/attention-center.css?v=0.14.0" in index\n    assert "/assets/attention-center.js" not in index\n    assert "Wartet auf dich" in js\n    assert "/v1/attention?limit=200" in js\n    assert "/v1/attention/resolve" in js\n    assert '@app.get("/v1/attention")' in main\n    assert '@app.post("/v1/attention/resolve")' in main\n    assert "shadow_reports.recent_reports" in main\n    assert "attention_source" in main\n    assert "Shadow-Ergebnis" in js\n    assert 'view="attention"' in desktop\n\n\ndef test_workbench_attention_has_no_recursive_mutation_observer():\n    js = (ROOT / "apps/web/workbench-ui.js").read_text(encoding="utf-8")\n    assert "MutationObserver" not in js\n\n\ndef test_workbench_attention_javascript_syntax():\n    node = shutil.which("node")\n    if not node:\n        pytest.skip("Node.js is not available")\n    result = subprocess.run(\n        [node, "--check", str(ROOT / "apps/web/workbench-ui.js")],\n        capture_output=True,\n        text=True,\n        check=False,\n    )\n    assert result.returncode == 0, result.stderr\n''',
    encoding="utf-8",
)

(ROOT / "tests/test_workbench_ui.py").write_text(
    '''from __future__ import annotations\n\nimport shutil\nimport subprocess\nfrom pathlib import Path\n\nimport pytest\n\nROOT = Path(__file__).resolve().parents[1]\n\n\ndef test_workbench_is_first_class_and_legacy_attention_enhancer_is_not_loaded():\n    index = (ROOT / "apps/web/index.html").read_text(encoding="utf-8")\n    assert "/assets/workbench.css?v=0.14.0" in index\n    assert "/assets/workbench-ui.js?v=0.14.0" in index\n    assert "/assets/dashboard-live.js?v=0.14.0" in index\n    assert "/assets/attention-center.js" not in index\n\n\ndef test_workbench_preserves_core_actions_and_settings():\n    source = (ROOT / "apps/web/workbench-ui.js").read_text(encoding="utf-8")\n    for marker in (\n        "runAgentNow", "syncNow", "data-approve", "data-reject",\n        "data-draft-edit", "data-draft-submit", "/v1/attention?limit=200",\n        "/v1/attention/resolve", "/v1/settings/behavior", "mark_processed_read",\n        "newsletter_action", "advertising_action", "saveBehaviorSettings",\n        "saveBrainSettings", "probeSettingsProvider", "check-update", "install-update",\n    ):\n        assert marker in source\n\n\ndef test_workbench_has_real_filters_and_command_palette_not_preview_controls():\n    source = (ROOT / "apps/web/workbench-ui.js").read_text(encoding="utf-8")\n    assert "data-inbox-filter" in source\n    assert "data-attention-filter" in source\n    assert "function openCommand()" in source\n    assert 'data-command-action="sync"' in source\n    assert 'data-command-action="run"' in source\n    assert "design-preview" not in source\n    assert "installDemoData" not in source\n\n\ndef test_workbench_javascript_syntax():\n    node = shutil.which("node")\n    if not node:\n        pytest.skip("Node.js is not available")\n    result = subprocess.run(\n        [node, "--check", str(ROOT / "apps/web/workbench-ui.js")],\n        capture_output=True, text=True, check=False,\n    )\n    assert result.returncode == 0, result.stderr\n''',
    encoding="utf-8",
)

# Normalize generated text before git diff checks.
for path in (
    ROOT / "apps/web/workbench-ui.js",
    ROOT / "apps/web/workbench.css",
    ROOT / "apps/web/index.html",
    ROOT / "tests/test_attention_ui_contract.py",
    ROOT / "tests/test_workbench_ui.py",
):
    source = path.read_text(encoding="utf-8")
    path.write_text("\n".join(line.rstrip() for line in source.splitlines()) + "\n", encoding="utf-8")

# Remove transport-only staging artifacts. The temporary workflow itself is removed via the connector.
for rel in ("tools/workbench_payload", "tools/workbench_payload2", "tools/workbench_bundle"):
    shutil.rmtree(ROOT / rel, ignore_errors=True)
for rel in ("tools/apply_workbench_design.py", "tools/apply_workbench_bundle.py"):
    path = ROOT / rel
    if path.exists():
        path.unlink()
