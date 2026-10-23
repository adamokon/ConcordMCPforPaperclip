import copy
import time
import uuid

import pytest

from concord_paperclip.engine import Engine
from concord_paperclip.policy import BridgeError, Principal
from concord_paperclip.store import Store


class FakePaperclip:
    def __init__(self):
        self.rows = {}
        self.creates = 0
        self.patches = 0
        self.drop_create_reply = False
        self.drop_patch_reply = False
        self.profile = str(uuid.uuid4())
        self.company_id = str(uuid.uuid4())

    def agents(self):
        return [{"id": self.profile, "name": "worker", "status": "idle", "adapterType": "process"}]

    def create_backlog(self, title, description, parent_id=None):
        self.creates += 1
        issue = {"id": str(uuid.uuid4()), "identifier": f"TEST-{self.creates}", "status": "backlog",
                 "title": title, "description": description, "companyId": self.company_id,
                 "assigneeAgentId": None, "executionRunId": None, "checkoutRunId": None, "parentId": parent_id}
        self.rows[issue["id"]] = issue
        if self.drop_create_reply:
            raise BridgeError("NETWORK_UNCERTAIN")
        return copy.deepcopy(issue)

    def issue(self, issue_id):
        return copy.deepcopy(self.rows[issue_id])

    def patch(self, issue_id, data):
        self.patches += 1
        self.rows[issue_id].update(data)
        if self.drop_patch_reply:
            raise BridgeError("NETWORK_UNCERTAIN")
        return self.issue(issue_id)


@pytest.fixture
def setup(tmp_path):
    backend = FakePaperclip()
    store = Store(tmp_path / "state" / "bridge.db")
    engine = Engine(store, backend, Principal("owner"), [{"id": backend.profile, "ready_until": time.time()+60}])
    return engine, backend, store


def submit(engine, key="first", paths=None, **extra):
    return engine.submit(key, "Synthetic test", "Create a pure function and tests.", "demo", paths or ["main.py"], **extra)


def running(engine):
    task = submit(engine)
    engine.drain()
    task = engine.inspect(task["id"])
    return engine.dispatch(task["id"], task["version"])


def completed(engine, backend):
    task = running(engine)
    return engine.observe(task["id"], {"issue_id": task["issue_id"], "run_id": str(uuid.uuid4()),
                          "agent_id": backend.profile, "status": "succeeded", "environment_removed": True})
