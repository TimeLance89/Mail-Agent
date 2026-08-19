from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_preview_tag_moves_only_after_release_asset_is_verified():
    workflow = (ROOT / ".github/workflows/build-installers.yml").read_text(encoding="utf-8")

    upload = workflow.index('gh release upload preview-latest "$INSTALLER" --clobber')
    redownload = workflow.index("gh release download preview-latest", upload)
    compare_hash = workflow.index('if [[ "$ACTUAL_SHA256" != "$EXPECTED_SHA256" ]]', redownload)
    verify_digest = workflow.index("PUBLISHED_DIGEST=", compare_hash)
    edit_release = workflow.index("gh release edit preview-latest", verify_digest)
    move_tag = workflow.index('git tag -f preview-latest "$GITHUB_SHA"', edit_release)
    verify_remote = workflow.index("git ls-remote origin refs/tags/preview-latest", move_tag)

    assert upload < redownload < compare_hash < verify_digest < edit_release < move_tag < verify_remote
    assert '"sha256:${EXPECTED_SHA256}"' in workflow
    assert "restore_previous_asset" in workflow


def test_preview_publish_remains_gated_by_windows_installer_job():
    workflow = (ROOT / ".github/workflows/build-installers.yml").read_text(encoding="utf-8")
    publish = workflow.split("  publish-preview:", 1)[1].split("  standalone:", 1)[0]
    assert "needs: [windows]" in publish
    assert "actions/download-artifact@v4" in publish
    assert "Mail-Agent-Windows-Installer" in publish
    assert "test -f release-assets/Mail-Agent-Setup.exe" in publish
