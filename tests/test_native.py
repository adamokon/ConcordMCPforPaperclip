import pytest

from concord_paperclip import native
from concord_paperclip.broker import request_native
from concord_paperclip.policy import BridgeError


def test_native_client_needs_platform_context(monkeypatch, tmp_path):
    monkeypatch.delenv("PAPERCLIP_RUN_ID", raising=False)
    monkeypatch.delenv("PAPERCLIP_API_KEY", raising=False)
    with pytest.raises(BridgeError, match="NATIVE_CONTEXT_REQUIRED"):
        request_native(tmp_path/"socket")


@pytest.mark.parametrize("agent,status", [("other-agent", "running"), ("native", "succeeded"), ("native", "failed")])
def test_broker_rejects_other_or_terminal_native_run(monkeypatch, agent, status):
    class Backend:
        run_id = None
    class Engine:
        backend = Backend()
    class Runtime:
        def __init__(self, *args, **kwargs):
            pass
        def run(self, run_id):
            return {"agentId": agent, "status": status}
    monkeypatch.setattr(native, "make_engine", lambda c: Engine())
    monkeypatch.setattr(native, "Paperclip", Runtime)
    with pytest.raises(BridgeError, match="NATIVE_RUN_MISMATCH"):
        native.execute({"base_url": "https://example.invalid", "company_id": "company", "native_agent_id": "native"},
                       "run", "not-a-real-token")
