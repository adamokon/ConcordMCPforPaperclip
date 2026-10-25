"""Opt-in recovery in the existing receiver. Paperclip remains the scheduler."""
import json
import os
import time
from pathlib import Path

from .automation import gateway, receive
from .policy import BridgeError
from .recovery_policy import decide_recovery


def context(engine, config, task_id):
    """Derive the original binding from protected state, including after reservation."""
    with engine.store.connect() as c:
        exists = c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='recovery_intents'").fetchone()
        intents = [json.loads(r[0]) for r in c.execute(
            'SELECT data FROM recovery_intents WHERE task_id=?', (task_id,))] if exists else []
    pending = [i for i in intents if i['owner'] == engine.actor.name and i['phase'] != 'bound']
    if len(pending) > 1:
        raise BridgeError('AMBIGUOUS_RECOVERY_INTENT')
    intent = pending[0] if pending else None
    with engine.store.connect() as c:
        t = engine._task(c, task_id)
        if t['owner'] != engine.actor.name or t['state'] not in {'execution_failed', 'recovery_pending'}:
            raise BridgeError('RECOVERY_TASK_SCOPE')
        if intent:
            a = c.execute('SELECT * FROM attempts WHERE id=? AND task_id=?',
                          (intent['source_attempt_id'], task_id)).fetchone()
        else:
            a = c.execute('SELECT * FROM attempts WHERE task_id=? ORDER BY number DESC LIMIT 1',
                          (task_id,)).fetchone()
        if not a or a['state'] != 'terminal' or not a['run_id']:
            raise BridgeError('RECOVERY_SOURCE_REQUIRED')
        spec = json.loads(t['spec'])
        count = len(intents)
    return {'binding': dict(task_id=task_id, issue_id=t['issue_id'], agent_id=a['profile'],
                           attempt_id=a['id'], source_run_id=a['run_id'], repo=spec['repo'],
                           company_id=config['company_id'], project_id=config['project_id'],
                           version=t['version'], retries_used=count),
            'intent': intent}


def recover(engine, config):
    from .recovery_state import RecoveryJournal
    from .recovery_driver import RecoveryController
    policy = config.get('recovery_policy', {})
    if policy.get('enabled') is not True:
        return []
    journal = RecoveryJournal(engine.store.path, engine.actor.name)
    tasks, errors = [], []
    with engine.store.connect() as c:
        rows = c.execute("SELECT id,spec FROM tasks WHERE owner=? AND state IN "
                         "('execution_failed','recovery_pending')", (engine.actor.name,)).fetchall()
    for row in rows:
        if json.loads(row['spec']).get('repo') not in policy['allowed_repos']:
            continue
        try:
            tasks.append(context(engine, config, row['id'])['binding'])
        except BridgeError as e:
            errors.append({'task_id': row['id'], 'code': e.code})
    # Root-owned test injection verifies restart after a committed reservation.
    fault = config.get('recovery_test', {})
    if fault.get('crash_after_prepare') is True:
        original = journal.prepare
        def prepare(*args, **kwargs):
            result = original(*args, **kwargs)
            selected = next((t for t in tasks if t['task_id'] == result['task_id']), {})
            if selected.get('repo') == fault.get('repo'):
                marker = Path(fault['marker'])
                try:
                    fd = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
                except FileExistsError:
                    return result
                with os.fdopen(fd, 'w') as f:
                    f.write(result['id'])
                    f.flush()
                    os.fsync(f.fileno())
                os._exit(77)
            return result
        journal.prepare = prepare
    controller = RecoveryController(journal,
        lambda b: gateway(config, {'action': 'recovery-inspect', 'task_id': b['task_id']}),
        lambda i, e: gateway(config, {'action': 'recovery-resolve', 'task_id': i['task_id'], 'intent_id': i['id']}),
        decide_recovery, policy, clock=time.time)
    return errors + controller.cycle(tasks)


def cycle(engine, config):
    from .synthetic_review import approve
    receipts = receive(engine, config)
    from .partial_cycle import cycle as partial_cycle
    partials = partial_cycle(engine, config)
    recovery = recover(engine, config)
    return {'receipts': receipts, 'partials': partials, 'recovery': recovery, 'approvals': approve(engine, config),
            'backlog': wake_ready_backlog(engine, config)}


def wake_ready_backlog(engine, config):
    """At most two durable non-model wakes for an approved queued task.

    A lost create response stays uncertain. Existing controls must be terminal
    before a second wake; no direct model invocation or profile rotation occurs.
    """
    from .automation import refresh_profiles
    from .wake import wake
    policy = config.get('recovery_policy', {})
    if policy.get('enabled') is not True:
        return []
    with engine.store.connect() as c:
        tasks = [dict(t) for t in c.execute("SELECT id,spec FROM tasks WHERE owner=? AND state IN ('queued','backlog')",
                                           (engine.actor.name,))]
    tasks = [t for t in tasks if json.loads(t['spec'])['repo'] in policy['allowed_repos']]
    if not tasks:
        return []
    ready = refresh_profiles(engine, config)
    if not any(p['id'] in policy['allowed_agents'] and p['eligible'] for p in ready):
        return []
    results = []
    for task in tasks:
        for n in range(2):
            marker = 'recovery-ready:' + task['id'] + ':' + str(n)
            with engine.store.connect() as c:
                old = c.execute('SELECT state,result FROM operations WHERE owner=? AND key=?',
                                (engine.actor.name, 'wake:' + marker)).fetchone()
            if old:
                if old['state'] != 'done' or not old['result']:
                    break
                previous = engine.backend.issue(json.loads(old['result'])['issue_id'])
                if (previous.get('status') not in {'done','cancelled'} or previous.get('executionRunId')
                        or previous.get('checkoutRunId')):
                    break
                continue
            results.append({'task_id': task['id'], 'wake': wake(engine, config, marker)})
            break
    return results


def read_context(config, task_id):
    """Root reader never opens writable SQLite or loads model/API credentials."""
    import contextlib
    import sqlite3
    from types import SimpleNamespace
    @contextlib.contextmanager
    def connect():
        db = sqlite3.connect(Path(config['database']).as_uri() + '?mode=ro', uri=True, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            yield db
        finally:
            db.close()
    def task(c, identity):
        row = c.execute('SELECT * FROM tasks WHERE id=?', (identity,)).fetchone()
        if row is None:
            raise BridgeError('TASK_NOT_FOUND')
        return row
    engine = SimpleNamespace(store=SimpleNamespace(connect=connect),
                             actor=SimpleNamespace(name=config['principal']), _task=task)
    return context(engine, config, task_id)
