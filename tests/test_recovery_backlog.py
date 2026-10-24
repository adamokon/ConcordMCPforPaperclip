import json
import uuid

from concord_paperclip.engine import Engine
from concord_paperclip.policy import Principal
from concord_paperclip.recovery_service import wake_ready_backlog
from concord_paperclip.store import Store


class Backend:
    calls = 0
    lose_response = False
    status = 'done'

    def agents(self):
        return [{'id': 'coordinator', 'adapterType': 'process'}]

    def wake_coordinator(self, identity, marker):
        assert identity == 'coordinator'
        self.calls += 1
        if self.lose_response:
            raise OSError('response lost')
        return {'id': str(uuid.uuid4())}

    def issue(self, identity):
        return {'id': identity, 'status': self.status}


def setup(tmp_path, monkeypatch, state='queued'):
    backend = Backend()
    engine = Engine(Store(tmp_path / 'bridge.db'), backend, Principal('service', 'coordinator'))
    task = str(uuid.uuid4())
    with engine.store.transaction() as c:
        c.execute('INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?)',
                  (task, 'service', json.dumps({'repo': 'public'}), None, None, state, 1, 10))
    monkeypatch.setattr('concord_paperclip.automation.refresh_profiles',
                        lambda *args: [{'id': 'worker', 'eligible': True}])
    cfg = {'native_agent_id': 'coordinator', 'recovery_policy': {
        'enabled': True, 'allowed_repos': ['public'], 'allowed_agents': ['worker']}}
    return engine, backend, cfg


def test_queued_work_gets_bounded_non_model_wake(tmp_path, monkeypatch):
    e, b, c = setup(tmp_path, monkeypatch)
    assert len(wake_ready_backlog(e, c)) == 1
    b.status = 'in_progress'
    assert wake_ready_backlog(e, c) == []
    assert b.calls == 1
    b.status = 'done'
    assert len(wake_ready_backlog(e, c)) == 1
    assert wake_ready_backlog(e, c) == []
    assert b.calls == 2


def test_lost_wake_response_never_replayed(tmp_path, monkeypatch):
    e, b, c = setup(tmp_path, monkeypatch)
    b.lose_response = True
    wake_ready_backlog(e, c)
    for _ in range(3):
        assert wake_ready_backlog(e, c) == []
    assert b.calls == 1


def test_unready_or_unapproved_does_not_wake(tmp_path, monkeypatch):
    e, b, c = setup(tmp_path, monkeypatch)
    monkeypatch.setattr('concord_paperclip.automation.refresh_profiles',
                        lambda *args: [{'id': 'worker', 'eligible': False}])
    assert wake_ready_backlog(e, c) == []
    c['recovery_policy']['allowed_repos'] = ['other']
    assert wake_ready_backlog(e, c) == []
    assert b.calls == 0
