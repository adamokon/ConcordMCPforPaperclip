"""Actual agent modules combined; synthetic APIs, real SQLite transactions."""
from types import SimpleNamespace

from concord_paperclip.recovery_policy import decide_recovery
from concord_paperclip.recovery_service import context
from concord_paperclip.store import Store
import test_recovery_driver as driver


def test_actual_policy_prepared_restart_and_response_loss():
    f = driver.ControllerTests()
    f.setUp()
    try:
        f.policy['max_retries'] = 1
        intent = f.prepare(max_retries=1)
        f.binding['retries_used'] = 1
        f.binding['version'] = 8
        f.resolve_error = True
        result = f.controller(decide=decide_recovery).cycle([f.binding])[0]
        assert result['phase'] == 'uncertain'
        for _ in range(3):
            f.controller(decide=decide_recovery).cycle([f.binding])
        assert len(f.calls) == 1
        f.proof()
        result = f.controller(decide=decide_recovery).cycle([f.binding])[0]
        assert result['phase'] == 'bound'
        assert f.j.get(intent['id'])['new_run_id'] == f.successor
        assert len(f.calls) == 1
        assert f.sql('SELECT count(*) FROM claims') == [(1,)]
    finally:
        f.doCleanups()


def test_context_keeps_original_source_after_reserved_attempt():
    f = driver.ControllerTests()
    f.setUp()
    try:
        store = Store(f.path)
        engine = SimpleNamespace(store=store, actor=SimpleNamespace(name=f.owner),
            _task=lambda c, t: c.execute('SELECT * FROM tasks WHERE id=?', (t,)).fetchone())
        cfg = dict(company_id=f.company, project_id=f.project)
        before = context(engine, cfg, f.task)
        assert before['binding']['attempt_id'] == f.attempt
        f.prepare()
        after = context(engine, cfg, f.task)
        assert after['binding']['source_run_id'] == f.source
        assert after['binding']['attempt_id'] == f.attempt
        assert after['binding']['version'] == 8
        assert after['binding']['retries_used'] == 1
        assert after['intent']['phase'] == 'prepared'
    finally:
        f.doCleanups()


def test_root_context_does_not_create_schema_or_load_credentials():
    from pathlib import Path
    from concord_paperclip.recovery_service import read_context
    f = driver.ControllerTests()
    f.setUp()
    try:
        f.sql('DROP TABLE recovery_intents')
        before = Path(f.path).stat().st_mtime_ns
        cfg = dict(database=f.path, principal=f.owner, company_id=f.company,
                   project_id=f.project, token_command=['/must-never-run'])
        result = read_context(cfg, f.task)
        assert result['intent'] is None
        assert result['binding']['source_run_id'] == f.source
        assert result['binding']['retries_used'] == 0
        assert f.sql("SELECT count(*) FROM sqlite_master WHERE name='recovery_intents'") == [(0,)]
        assert Path(f.path).stat().st_mtime_ns == before
    finally:
        f.doCleanups()
