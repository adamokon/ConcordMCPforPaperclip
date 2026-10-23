"""REST paths verified against Paperclip issue/agent routers, not an invented v1 API."""

import json
import urllib.error
import urllib.parse
import urllib.request

from .policy import BridgeError


class RemoteError(BridgeError):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never send auth credentials to an SSO redirect or another origin.
        return None


class Paperclip:
    def __init__(self, base_url: str, company_id: str, token: str = "", timeout=15,
                 project_id: str | None = None, run_id: str | None = None, trusted_http_hosts=()):
        parsed = urllib.parse.urlsplit(base_url)
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise BridgeError("INVALID_BASE_URL")
        if parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in {
            "127.0.0.1", "localhost", "::1", *trusted_http_hosts
        }):
            raise BridgeError("TLS_REQUIRED", "Use HTTPS or an SSH tunnel terminating on loopback")
        self.base_url = base_url.rstrip("/")
        self.company_id = company_id
        self.token = token
        self.timeout = timeout
        self.project_id = project_id
        self.run_id = run_id
        self.opener = urllib.request.build_opener(NoRedirect())

    def request(self, method, path, data=None):
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        if self.run_id:
            headers["X-Paperclip-Run-Id"] = self.run_id
        body = None
        if data is not None:
            body = json.dumps(data, allow_nan=False).encode()
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(self.base_url + path, body, headers, method=method)
        try:
            with self.opener.open(req, timeout=self.timeout) as response:
                raw = response.read(2_000_001)
                if len(raw) > 2_000_000:
                    raise RemoteError("RESPONSE_TOO_LARGE")
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as e:
            raise RemoteError(f"HTTP_{e.code}", "Paperclip rejected request; response body withheld") from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise RemoteError("NETWORK_UNCERTAIN", "Do not repeat a write without reconciliation") from None
        except (ValueError, UnicodeError):
            raise RemoteError("INVALID_RESPONSE") from None

    @staticmethod
    def segment(value):
        return urllib.parse.quote(str(value), safe="")

    def company_path(self, resource):
        return f"/api/companies/{self.segment(self.company_id)}/{resource}"

    def health(self):
        row = self.request("GET", "/api/health")
        if not isinstance(row, dict):
            raise RemoteError("API_CONTRACT")
        return {key: row[key] for key in ("status", "version", "commit", "deploymentMode", "authReady", "bootstrapStatus")
                if key in row}

    def agents(self):
        rows = self.request("GET", self.company_path("agents"))
        if not isinstance(rows, list):
            raise RemoteError("API_CONTRACT")
        # Exclude adapterConfig/env; these can include secrets or private paths.
        return [{k: a.get(k) for k in ("id", "name", "status", "adapterType")} for a in rows]

    def issue(self, issue_id):
        row = self.request("GET", "/api/issues/" + self.segment(issue_id))
        if not isinstance(row, dict) or row.get("companyId") != self.company_id:
            raise RemoteError("COMPANY_MISMATCH")
        return row

    def issues(self):
        # Bounded scan. If truncated we cannot conclude that a marker is absent.
        rows = self.request("GET", self.company_path("issues") + "?limit=200&offset=0")
        if not isinstance(rows, list):
            raise RemoteError("API_CONTRACT", "Expected issue array; inspect the installed API version")
        return rows

    def create_backlog(self, title, description, parent_id=None):
        data = {"title": title, "description": description, "status": "backlog"}
        if self.project_id:
            data["projectId"] = self.project_id
        if parent_id:
            data["parentId"] = parent_id
        return self.request("POST", self.company_path("issues"), data)

    def wake_coordinator(self, agent_id, marker):
        if not self.project_id:
            raise BridgeError("PROJECT_REQUIRED")
        return self.request("POST", self.company_path("issues"), {
            "title": "Bridge operation " + marker,
            "description": "Machine control request. Process only queued, validated bridge operations. " + marker,
            "projectId": self.project_id, "assigneeAgentId": agent_id, "status": "todo",
        })

    def patch(self, issue_id, data):
        return self.request("PATCH", "/api/issues/" + self.segment(issue_id), data)

    def active_runs(self):
        rows = self.request("GET", self.company_path("live-runs"))
        if not isinstance(rows, list):
            raise RemoteError("API_CONTRACT")
        return rows

    def run(self, run_id):
        row = self.request("GET", "/api/heartbeat-runs/" + self.segment(run_id))
        if not isinstance(row, dict) or row.get("companyId") != self.company_id:
            raise RemoteError("COMPANY_MISMATCH")
        return row

    def comments(self, issue_id):
        self.issue(issue_id)
        return self.request("GET", "/api/issues/" + self.segment(issue_id) + "/comments")
