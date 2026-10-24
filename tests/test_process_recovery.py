"""A real process dies after external creation, before the SQLite confirmation."""

import json
import os
import subprocess
import sys
from pathlib import Path

from concord_paperclip.engine import Engine
from concord_paperclip.policy import Principal
from concord_paperclip.store import Store
from conftest import FakePaperclip


def test_hard_crash_and_backup_restore_never_replay_create(tmp_path):
    script = '''import json,os,pathlib,sys,uuid
from concord_paperclip.engine import Engine
from concord_paperclip.policy import Principal
from concord_paperclip.store import Store
class Remote:
 def create_backlog(self,title,description,parent_id=None):
  pathlib.Path(sys.argv[2]).write_text(json.dumps({'id':str(uuid.uuid4()),'title':title,'description':description,'status':'backlog','assigneeAgentId':None}))
  os._exit(71)
e=Engine(Store(sys.argv[1]),Remote(),Principal('owner'))
e.submit('only-once','Public synthetic task','Create a function.','demo',['main.py'])
e.drain()
'''
    database = tmp_path / "bridge.db"
    remote = tmp_path / "external-issue.json"
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1]/"src")}
    p = subprocess.run([sys.executable, "-c", script, str(database), str(remote)], env=env, timeout=15)
    assert p.returncode == 71
    external_bytes = remote.read_bytes()
    backend = FakePaperclip()
    issue = json.loads(external_bytes)
    backend.rows[issue["id"]] = issue
    engine = Engine(Store(database), backend, Principal("owner"))
    assert engine.recover()["quarantined"] == 1
    assert engine.drain() == [] and backend.creates == 0
    with engine.store.connect() as c:
        task = dict(c.execute("SELECT * FROM tasks").fetchone())
    assert task["state"] == "create_uncertain"
    engine.adopt(task["id"], issue["id"], task["version"])
    backup = tmp_path / "accepted-backup.db"
    engine.store.backup(str(backup))
    restored = Engine(Store(backup), backend, Principal("owner"))
    assert restored.recover()["quarantined"] == 0
    assert restored.drain() == [] and backend.creates == 0
    assert restored.inspect(task["id"])["issue_id"] == issue["id"]
    assert remote.read_bytes() == external_bytes
