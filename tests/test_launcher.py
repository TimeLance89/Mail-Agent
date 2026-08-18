import os
from pathlib import Path

from mail_agent_launcher.main import configure_environment, user_data_dir


def test_launcher_configures_runtime_paths(tmp_path: Path, monkeypatch):
    for key in (
        "MAIL_AGENT_DATA_DIR",
        "MAIL_AGENT_REGISTRY_DB",
        "MAIL_AGENT_REGISTRY_URL",
        "MAIL_AGENT_GATEWAY_HOST",
        "MAIL_AGENT_GATEWAY_PORT",
    ):
        monkeypatch.delenv(key, raising=False)
    configure_environment(tmp_path)
    assert Path(os.environ["MAIL_AGENT_DATA_DIR"]) == tmp_path / "gateway"
    assert Path(os.environ["MAIL_AGENT_REGISTRY_DB"]) == tmp_path / "registry" / "registry.db"
    assert os.environ["MAIL_AGENT_REGISTRY_URL"].endswith(":8770")
    assert os.environ["MAIL_AGENT_GATEWAY_PORT"] == "8765"


def test_user_data_dir_is_absolute():
    assert user_data_dir().expanduser().is_absolute()
