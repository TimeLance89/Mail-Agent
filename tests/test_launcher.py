import os
import queue
from pathlib import Path

from mail_agent_launcher.main import (
    configure_environment,
    log_path,
    user_data_dir,
    wait_for_gateway,
)


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
    assert (tmp_path / "gateway").is_dir()
    assert (tmp_path / "registry").is_dir()
    assert os.environ["MAIL_AGENT_REGISTRY_URL"].endswith(":8770")
    assert os.environ["MAIL_AGENT_GATEWAY_PORT"] == "8765"


def test_user_data_dir_is_absolute():
    assert user_data_dir().expanduser().is_absolute()


def test_log_path_is_stable(tmp_path: Path):
    assert log_path(tmp_path) == tmp_path / "logs" / "mail-agent.log"


def test_wait_for_gateway_surfaces_server_crash(monkeypatch):
    monkeypatch.setattr("mail_agent_launcher.main.gateway_health", lambda timeout=0.8: False)
    errors: queue.Queue[tuple[str, BaseException]] = queue.Queue()
    errors.put(("Gateway", RuntimeError("boom")))
    ready, reason = wait_for_gateway(errors, timeout=0.01)
    assert ready is False
    assert reason is not None
    assert "Gateway" in reason
    assert "boom" in reason
