import asyncio
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from concord_paperclip.paperclip import Paperclip, RemoteError
from concord_paperclip.policy import BridgeError


@pytest.fixture
def http_server():
    calls = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            calls.append(("GET", self.path, self.headers.get("Authorization")))
            if self.path == "/api/health":
                result = {"status": "ok", "commit": "test-fixture"}
            elif self.path.endswith("/agents"):
                result = [{"id": "a", "name": "example", "status": "idle", "adapterType": "process",
                           "adapterConfig": {"env": {"SECRET": "must-not-leak"}}}]
            elif self.path == "/redirect":
                self.send_response(302)
                self.send_header("Location", "/stolen")
                self.end_headers()
                return
            else:
                result = {"id": "issue", "companyId": "company", "status": "backlog"}
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(result).encode())

        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            calls.append(("POST", self.path, payload))
            self.send_response(201)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"id": "issue", "companyId": "company", "identifier": "TEST-1", **payload}).encode())
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield "http://127.0.0.1:" + str(server.server_port), calls
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def test_actual_rest_contract(http_server):
    url, calls = http_server
    api = Paperclip(url, "company", "example-token", project_id="project")
    issue = api.create_backlog("Example", "Synthetic")
    assert issue["status"] == "backlog"
    assert calls[-1][1] == "/api/companies/company/issues"
    assert calls[-1][2]["projectId"] == "project"
    assert "assigneeAgentId" not in calls[-1][2]
    assert "adapterConfig" not in api.agents()[0]
    assert api.issue("issue")["companyId"] == "company"


def test_no_redirect_credentials(http_server):
    url, calls = http_server
    with pytest.raises(RemoteError, match="Paperclip rejected"):
        Paperclip(url, "company", "secret").request("GET", "/redirect")
    assert all(c[1] != "/stolen" for c in calls)


def test_cross_company_rejected(http_server):
    url, _ = http_server
    with pytest.raises(RemoteError, match="COMPANY_MISMATCH"):
        Paperclip(url, "other").issue("issue")


@pytest.mark.parametrize("url", ["http://example.com", "https://user:password@example.com", "https://example.com?a=b"])
def test_unsafe_base_url(url):
    with pytest.raises(BridgeError):
        Paperclip(url, "company")


def test_official_mcp_sdk_real_stdio_subprocess(http_server, tmp_path):
    url, calls = http_server
    config = tmp_path/"config.json"
    config.write_text(json.dumps({"base_url": url, "company_id": "company", "project_id": "project",
                                  "principal": "test", "database": str(tmp_path/"state.db")}))
    async def run():
        params = StdioServerParameters(command=sys.executable,
                                       env={"PYTHONPATH": os.environ.get("PYTHONPATH", "")}, args=["-m", "concord_paperclip.cli",
                                       "--config", str(config), "serve"])
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                init = await session.initialize()
                assert init.serverInfo.name == "ConcordMCPforPaperclip"
                tools = (await session.list_tools()).tools
                assert "paperclip_submit_work" in {t.name for t in tools}
                assert all("caller_id" not in t.inputSchema.get("properties", {}) for t in tools)
                status = await session.call_tool("bridge_status", {})
                assert not status.isError
                queued = await session.call_tool("paperclip_submit_work", {
                    "idempotency_key": "sdk-smoke", "title": "SDK test", "description": "Synthetic code",
                    "repo": "demo", "allowed_paths": ["a.py"]})
                assert not queued.isError
                data = json.loads(queued.content[0].text)
                assert data["state"] == "queued"
                assert not any(c[0] == "POST" for c in calls)
                read = await session.call_tool("paperclip_inspect_work", {"task_id": data["id"]})
                assert not read.isError
                bad = await session.call_tool("paperclip_submit_work", {
                    "idempotency_key": "x", "title": "T", "description": "D", "repo": "r",
                    "allowed_paths": ["../secrets"]})
                assert "INVALID_PATH" in bad.content[0].text
    asyncio.run(run())
