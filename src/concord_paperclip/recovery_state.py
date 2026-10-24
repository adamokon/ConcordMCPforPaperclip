"""Trusted-service-only durable recovery journal. No network or scheduling.

Binding agent is the canonical attempts.profile UUID; tasks.owner is a service name.
Optional company_id/project_id in spec are also pinned when present.
"""
import contextlib
import json
import math
import os
import sqlite3
import stat
import time
import uuid
from pathlib import Path


class RecoveryStateError(RuntimeError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def require(ok, code):
    if not ok:
        raise RecoveryStateError(code)


def canonical(value):
    try:
        return isinstance(value, str) and str(uuid.UUID(value)) == value
    except (ValueError, TypeError, AttributeError):
        return False


def finite(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except (OverflowError, ValueError):
        return False


def integer(value, low, high=None):
    return type(value) is int and value >= low and (high is None or value <= high)


def nonempty(value):
    return isinstance(value, str) and bool(value.strip())


class RecoveryJournal:
    def __init__(self, db_path, owner, clock=time.time):
        require(nonempty(owner), 'invalid_owner')
        self.path = os.path.abspath(os.fspath(db_path))
        self.owner, self.clock = owner, clock
        self._check_path()
        with self._tx() as db:
            require(db.execute('PRAGMA user_version').fetchone()[0] == 1, 'schema_version')
            for table in ('tasks', 'attempts', 'claims', 'audit'):
                require(db.execute('SELECT 1 FROM sqlite_master WHERE type=? AND name=?',
                                   ('table', table)).fetchone() is not None, 'schema_missing')
            db.execute('CREATE TABLE IF NOT EXISTS recovery_intents '
                       '(id TEXT PRIMARY KEY, task_id TEXT NOT NULL, '
                       'source_attempt_id TEXT NOT NULL, data TEXT NOT NULL, '
                       'UNIQUE(task_id,source_attempt_id))')

    def _check_path(self):
        try:
            p = Path(self.path)
            require(not any(x.is_symlink() for x in (p, *p.parents)), 'unsafe_path')
            require(stat.S_ISREG(os.lstat(self.path).st_mode), 'unsafe_path')
        except OSError as exc:
            raise RecoveryStateError('database_missing') from exc

    @contextlib.contextmanager
    def _tx(self):
        db = None
        try:
            self._check_path()
            db = sqlite3.connect(Path(self.path).as_uri() + '?mode=rw', uri=True,
                                 timeout=5, isolation_level=None)
            db.row_factory = sqlite3.Row
            db.execute('PRAGMA busy_timeout=5000')
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('PRAGMA synchronous=FULL')
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except RecoveryStateError:
            if db is not None:
                db.rollback()
            raise
        except Exception as exc:
            if db is not None:
                db.rollback()
            raise RecoveryStateError('storage_error') from exc
        finally:
            if db is not None:
                db.close()

    def _now(self):
        try:
            value = self.clock()
        except Exception as exc:
            raise RecoveryStateError('invalid_clock') from exc
        require(finite(value), 'invalid_clock')
        return value

    def _load(self, db, intent_id):
        require(canonical(intent_id), 'invalid_uuid')
        row = db.execute('SELECT data FROM recovery_intents WHERE id=?', (intent_id,)).fetchone()
        require(row is not None, 'intent_missing')
        data = json.loads(row['data'])
        require(data['owner'] == self.owner, 'owner_mismatch')
        return data

    def _save(self, db, data):
        db.execute('UPDATE recovery_intents SET data=? WHERE id=?',
                   (json.dumps(data, allow_nan=False), data['id']))

    def _audit(self, db, data, event, at, receipt_at=None):
        db.execute('INSERT INTO audit(at,actor,task_id,event,details) VALUES(?,?,?,?,?)',
                   (at, 'trusted_recovery:' + data['policy_id'], data['task_id'], event,
                    json.dumps({'intent_id': data['id'], 'attempt_id': data['new_attempt_id'],
                                'run_id': data.get('new_run_id'), 'receipt_at': at if receipt_at is None else receipt_at})))

    def prepare(self, task_id, expected_version, source_run_id, policy_id,
                max_retries, recovery_action_id):
        require(all(canonical(x) for x in (task_id, source_run_id, recovery_action_id)), 'invalid_uuid')
        require(integer(expected_version, 0), 'invalid_version')
        require(integer(max_retries, 0, 2), 'invalid_budget')
        require(nonempty(policy_id), 'invalid_policy')
        with self._tx() as db:
            task = db.execute('SELECT * FROM tasks WHERE id=?', (task_id,)).fetchone()
            require(task is not None, 'task_missing')
            require(task['owner'] == self.owner, 'owner_mismatch')
            # Find old intent by source even after task/version have advanced.
            for row in db.execute('SELECT data FROM recovery_intents WHERE task_id=?', (task_id,)):
                old = json.loads(row['data'])
                if old['source_run_id'] == source_run_id:
                    require(old['policy_id'] == policy_id and
                            old['recovery_action_id'] == recovery_action_id and
                            old['max_retries'] == max_retries, 'intent_conflict')
                    return old
            require(task['state'] == 'execution_failed', 'task_state')
            require(task['version'] == expected_version, 'version_mismatch')
            source = db.execute('SELECT * FROM attempts WHERE task_id=? ORDER BY number DESC LIMIT 1',
                                (task_id,)).fetchone()
            require(source is not None, 'attempt_missing')
            require(canonical(source['id']) and source['run_id'] == source_run_id, 'source_mismatch')
            require(source['state'] == 'terminal',
                    'source_not_terminal')
            try:
                evidence = json.loads(source['evidence'])
            except (ValueError, TypeError):
                raise RecoveryStateError('cleanup_unproven')
            require(isinstance(evidence, dict) and evidence.get('environment_removed') is True,
                    'cleanup_unproven')
            require(evidence.get('status') in ('failed', 'cancelled', 'timed_out'), 'source_not_retryable')
            require(canonical(source['profile']), 'invalid_profile')
            require(db.execute("SELECT 1 FROM attempts WHERE profile=? AND state IN "
                               "('dispatching','running','uncertain')", (source['profile'],)).fetchone()
                    is None, 'profile_busy')
            require(db.execute('SELECT 1 FROM claims WHERE task_id=?', (task_id,)).fetchone()
                    is not None, 'claims_missing')
            count = db.execute('SELECT count(*) FROM recovery_intents WHERE task_id=?',
                               (task_id,)).fetchone()[0]
            require(count < max_retries, 'budget_exhausted')
            spec = json.loads(task['spec'])
            require(isinstance(spec, dict), 'invalid_spec')
            require(spec.get('profile') is None or spec['profile'] == source['profile'],
                    'preferred_profile_mismatch')
            require(canonical(task['issue_id']), 'invalid_uuid')
            intent_id = str(uuid.uuid5(uuid.NAMESPACE_URL, 'recovery:' + task_id + ':' + source['id']))
            attempt_id = str(uuid.uuid5(uuid.UUID(intent_id), 'attempt'))
            now = self._now()
            data = dict(id=intent_id, task_id=task_id, issue_id=task['issue_id'], owner=self.owner,
                        agent_id=source['profile'], profile=source['profile'], retry_number=count + 1,
                        source_attempt_id=source['id'], source_run_id=source_run_id,
                        new_attempt_id=attempt_id, policy_id=policy_id, max_retries=max_retries,
                        recovery_action_id=recovery_action_id, created_at=now, updated_at=now,
                        phase='prepared', new_run_id=None, reserved_version=expected_version + 1)
            for key in ('company_id', 'project_id'):
                if key in spec:
                    require(canonical(spec[key]), 'invalid_spec')
                    data[key] = spec[key]
            require(canonical(data['agent_id']), 'invalid_agent')
            db.execute('INSERT INTO attempts(id,task_id,profile,number,state,run_id,evidence) '
                       "VALUES(?,?,?,?,'uncertain',NULL,NULL)",
                       (attempt_id, task_id, source['profile'], source['number'] + 1))
            db.execute("UPDATE tasks SET state='recovery_pending',version=version+1 WHERE id=?", (task_id,))
            db.execute('INSERT INTO recovery_intents VALUES(?,?,?,?)',
                       (intent_id, task_id, source['id'], json.dumps(data, allow_nan=False)))
            self._audit(db, data, 'recovery_prepared', now)
            return data

    def _phase(self, intent_id, phase, allowed):
        with self._tx() as db:
            data = self._load(db, intent_id)
            if data['phase'] == phase:
                require(phase != 'requesting', 'request_already_claimed')
                return data
            require(data['phase'] in allowed, 'phase_conflict')
            if phase == 'requesting':
                self._reservation(db, data)
            now = self._now()
            data['phase'], data['updated_at'] = phase, now
            data[phase + '_at'] = now
            self._save(db, data)
            self._audit(db, data, 'recovery_' + phase, now)
            return data

    def requesting(self, intent_id):
        return self._phase(intent_id, 'requesting', ('prepared',))

    def uncertain(self, intent_id):
        return self._phase(intent_id, 'uncertain', ('requesting',))

    def waiting(self, intent_id):
        return self._phase(intent_id, 'waiting', ('requesting',))

    def _reservation(self, db, data):
        task = db.execute('SELECT * FROM tasks WHERE id=?', (data['task_id'],)).fetchone()
        require(task is not None and task['owner'] == self.owner, 'owner_mismatch')
        require(task['issue_id'] == data['issue_id'], 'binding_mismatch')
        spec = json.loads(task['spec'])
        require(isinstance(spec, dict), 'invalid_spec')
        require(spec.get('profile') is None or spec['profile'] == data['agent_id'],
                'preferred_profile_mismatch')
        for key in ('company_id', 'project_id'):
            if key in data:
                require(spec.get(key) == data[key], 'binding_mismatch')
        require(task['state'] == 'recovery_pending', 'task_state')
        require(task['version'] == data['reserved_version'], 'version_mismatch')
        require(db.execute('SELECT 1 FROM claims WHERE task_id=?', (data['task_id'],)).fetchone()
                is not None, 'claims_missing')
        latest = db.execute('SELECT * FROM attempts WHERE task_id=? ORDER BY number DESC LIMIT 1',
                            (data['task_id'],)).fetchone()
        require(latest is not None and latest['id'] == data['new_attempt_id'] and
                latest['state'] == 'uncertain' and latest['run_id'] is None and
                latest['profile'] == data['profile'] == data['agent_id'], 'reservation_mismatch')
        source = db.execute('SELECT * FROM attempts WHERE id=?',
                            (data['source_attempt_id'],)).fetchone()
        require(source is not None and source['task_id'] == data['task_id'] and
                source['run_id'] == data['source_run_id'] and
                source['profile'] == data['agent_id'] and source['state'] == 'terminal',
                'source_mismatch')
        evidence = json.loads(source['evidence'])
        require(isinstance(evidence, dict) and evidence.get('environment_removed') is True,
                'cleanup_unproven')
        require(evidence.get('status') in ('failed', 'cancelled', 'timed_out'),
                'source_not_retryable')

    def bind(self, intent_id, new_run):
        require(isinstance(new_run, dict), 'invalid_run')
        # Snapshot caller input before validating or persisting it.
        new_run = dict(new_run)
        with self._tx() as db:
            data = self._load(db, intent_id)
            require(canonical(new_run.get('id')), 'invalid_uuid')
            require(new_run.get('status') in ('queued', 'running', 'succeeded'), 'invalid_run_status')
            for key in ('task_id', 'issue_id', 'agent_id', 'source_run_id', 'recovery_action_id'):
                require(canonical(new_run.get(key)) and new_run[key] == data[key], 'binding_mismatch')
            for key in ('company_id', 'project_id'):
                if key in data:
                    require(new_run.get(key) == data[key], 'binding_mismatch')
            require(new_run['id'] != data['source_run_id'], 'run_reused')
            if data['phase'] == 'bound':
                require(new_run['id'] == data['new_run_id'], 'successor_conflict')
                return data
            require(data['phase'] in ('prepared', 'requesting', 'uncertain', 'waiting'), 'phase_conflict')
            self._reservation(db, data)
            require(db.execute('SELECT 1 FROM attempts WHERE run_id=?', (new_run['id'],)).fetchone()
                    is None, 'run_reused')
            now = self._now()
            db.execute("UPDATE attempts SET state='running',run_id=? WHERE id=?",
                       (new_run['id'], data['new_attempt_id']))
            db.execute("UPDATE tasks SET state='running',version=version+1 WHERE id=?", (data['task_id'],))
            data.update(phase='bound', new_run_id=new_run['id'], updated_at=now, bound_at=now)
            self._save(db, data)
            # The new run can predate this bind. Telemetry's lower bound
            # must be the pre-request time, with receipt time retained separately.
            dispatched_at = data.get('requesting_at', data['created_at'])
            require(finite(dispatched_at) and dispatched_at <= now, 'invalid_clock')
            self._audit(db, data, 'attempt_dispatched', dispatched_at, receipt_at=now)
            self._audit(db, data, 'recovery_bound', now)
            return data

    def pending(self):
        with self._tx() as db:
            result = []
            for row in db.execute('SELECT data FROM recovery_intents ORDER BY id'):
                data = json.loads(row['data'])
                if data['owner'] == self.owner and data['phase'] != 'bound':
                    result.append(data)
            return result

    def get(self, intent_id):
        with self._tx() as db:
            return self._load(db, intent_id)
