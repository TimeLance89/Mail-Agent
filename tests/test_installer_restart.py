from pathlib import Path


def test_windows_installer_restarts_with_clean_pyinstaller_environment():
    script = Path("packaging/windows/restart-mail-agent.cmd").read_text(encoding="utf-8")
    installer = Path("packaging/windows/MailAgent.iss").read_text(encoding="utf-8")

    # Preserve the original PyInstaller restart fix while requiring the stronger verified restart.
    assert 'PYINSTALLER_RESET_ENVIRONMENT=1' in script
    assert 'set "APP_EXE=%~1"' in script
    assert 'start "" "%APP_EXE%"' in script
    assert 'Invoke-RestMethod' in script
    assert 'MAIL_AGENT_EXPECTED_VERSION' in script
    assert 'update-restart.log' in script

    assert 'Source: "restart-mail-agent.cmd"; DestDir: "{tmp}"; Flags: deleteafterinstall' in installer
    assert installer.count('Filename: "{tmp}\\restart-mail-agent.cmd"') == 2
    assert '""{#MyAppVersion}"" ""open-browser"""' in installer
    assert '""{#MyAppVersion}"" ""no-browser"""' in installer
    assert 'runhidden postinstall skipifsilent' in installer
    assert 'runhidden skipifnotsilent' in installer
