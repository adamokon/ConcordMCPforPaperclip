"""Synthetic SQLite fixtures, actual transactions and separate connections."""
import concurrent.futures
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
import uuid
from concord_paperclip.recovery_state import RecoveryJournal, RecoveryStateError


def uid(n):
    return str(uuid.UUID(int=n))


SCHEMA = '''
PRAGMA user_version=1;
CREATE TABLE tasks(id TEXT PRIMARY KEY,owner TEXT,spec TEXT,issue_id TEXT UNIQUE,
 identifier TEXT,state TEXT,version INTEGER,created REAL);
CREATE TABLE attempts(id TEXT PRIMARY KEY,task_id TEXT,profile TEXT,number INTEGER,
 state TEXT,run_id TEXT,evidence TEXT,UNIQUE(task_id,number));
CREATE UNIQUE INDEX profile_slot ON attempts(profile)
 WHERE state IN ('dispatching','running','uncertain');
CREATE TABLE claims(repo TEXT,scope TEXT,task_id TEXT,PRIMARY KEY(repo,scope,task_id));
CREATE TABLE audit(id INTEGER PRIMARY KEY,at REAL,actor TEXT,task_id TEXT,event TEXT,details TEXT);
'''


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(
            dir=os.environ.get('PAPERCLIP_RUN_SCRATCH_DIR') or
            os.environ.get('PAPERCLIP_SCRATCH_DIR'))
        self.addCleanup(self.tmp.cleanup)
        self.root = str(Path(self.tmp.name).resolve())
        self.path = str(Path(self.root, 'bridge.db'))
        self.task, self.issue, self.agent, self.source, self.attempt = map(uid, range(1, 6))
        self.company, self.project, self.action, self.successor = map(uid, range(6, 10))
        self.now = 1000.0
        self.owner = 'codex_agent'
        self.spec = dict(profile=None, repo='public-repo', paths=['*'], inputs=[],
                         description='Synthetic recovery', title='Synthetic', parent_id=None,
                         company_id=self.company, project_id=self.project)
        with sqlite3.connect(self.path) as db:
            db.executescript(SCHEMA)
            db.execute('INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?)',
                       (self.task, self.owner, json.dumps(self.spec), self.issue, 'SYN-1',
                        'execution_failed', 7, 10.0))
            db.execute('INSERT INTO attempts VALUES(?,?,?,?,?,?,?)',
                       (self.attempt, self.task, self.agent, 1, 'terminal', self.source,
                        json.dumps({'status': 'failed', 'environment_removed': True, 'old': ['keep']})))
            db.execute('INSERT INTO claims VALUES(?,?,?)', ('public-repo', '*', self.task))
        self.j = self.journal()

    def journal(self, clock=None):
        return RecoveryJournal(self.path, self.owner, clock or (lambda: self.now))

    def prepare(self, **kw):
        args = dict(task_id=self.task, expected_version=7, source_run_id=self.source,
                    policy_id='root-policy', max_retries=2, recovery_action_id=self.action)
        args.update(kw)
        return self.j.prepare(**args)

    def run_data(self, **kw):
        data = dict(id=self.successor, status='queued', task_id=self.task, issue_id=self.issue,
                    agent_id=self.agent, company_id=self.company, project_id=self.project,
                    source_run_id=self.source, recovery_action_id=self.action)
        data.update(kw)
        return data

    def sql(self, statement, args=()):
        with sqlite3.connect(self.path) as db:
            return db.execute(statement, args).fetchall()

    def error(self, code, fn):
        with self.assertRaises(RecoveryStateError) as ctx:
            fn()
        self.assertEqual(ctx.exception.code, code)


class JournalTests(Fixture):
    def test_prepare_retains_source_claims_spec_and_schema(self):
        source = self.sql('SELECT * FROM attempts')
        task = self.sql('SELECT owner,spec,issue_id,id FROM tasks')
        claims = self.sql('SELECT * FROM claims')
        i = self.prepare()
        self.assertEqual(self.sql('PRAGMA user_version'), [(1,)])
        self.assertEqual(self.sql('SELECT * FROM attempts WHERE id=?', (self.attempt,)), source)
        self.assertEqual(self.sql('SELECT owner,spec,issue_id,id FROM tasks'), task)
        self.assertEqual(self.sql('SELECT * FROM claims'), claims)
        self.assertEqual(self.sql('SELECT state,version FROM tasks'), [('recovery_pending', 8)])
        self.assertEqual(self.sql('SELECT state,run_id,evidence,number FROM attempts WHERE id=?',
                                  (i['new_attempt_id'],)), [('uncertain', None, None, 2)])
        self.assertEqual(i, self.prepare())
        self.assertEqual(self.sql('SELECT count(*) FROM audit'), [(1,)])
        self.assertEqual(self.sql('SELECT actor FROM audit'), [('trusted_recovery:root-policy',)])

    def test_conflicting_prepare_and_owner(self):
        self.prepare()
        for kw in ({'policy_id': 'other'}, {'recovery_action_id': uid(99)}, {'max_retries': 1}):
            self.error('intent_conflict', lambda kw=kw: self.prepare(**kw))
        self.error('task_state', lambda: self.prepare(source_run_id=uid(88)))
        other = RecoveryJournal(self.path, uid(77))
        self.error('owner_mismatch', lambda: other.prepare(self.task, 7, self.source, 'root-policy', 2, self.action))

    def test_version_source_and_cleanup_rejected(self):
        self.error('version_mismatch', lambda: self.prepare(expected_version=8))
        self.error('source_mismatch', lambda: self.prepare(source_run_id=uid(88)))
        for value in (False, 1, 'true', None):
            self.sql('UPDATE attempts SET evidence=?', (json.dumps({'environment_removed': value}),))
            self.error('cleanup_unproven', self.prepare)
        self.assertEqual(self.sql('SELECT count(*) FROM attempts'), [(1,)])

    def test_profile_claims_and_terminal(self):
        self.sql("UPDATE attempts SET state='running'")
        self.error('source_not_terminal', self.prepare)
        self.sql("UPDATE attempts SET state='terminal'")
        self.sql('INSERT INTO attempts VALUES(?,?,?,?,?,?,?)',
                 (uid(88), uid(89), self.agent, 1, 'uncertain', None, None))
        self.error('profile_busy', self.prepare)
        self.sql('DELETE FROM attempts WHERE id=?', (uid(88),))
        self.sql('DELETE FROM claims')
        self.error('claims_missing', self.prepare)

    def test_budget_and_validation(self):
        self.error('budget_exhausted', lambda: self.prepare(max_retries=0))
        for val in (-1, 3, True, 1.0):
            self.error('invalid_budget', lambda val=val: self.prepare(max_retries=val))
        for val in ('bad', self.task.upper() + 'X'):
            self.error('invalid_uuid', lambda val=val: self.prepare(task_id=val))
        self.error('invalid_policy', lambda: self.prepare(policy_id=' '))
        self.error('invalid_version', lambda: self.prepare(expected_version=True))

    def test_actual_budget_counts_prior_intents(self):
        i = self.prepare(max_retries=1)
        self.j.bind(i['id'], self.run_data())
        self.sql("UPDATE attempts SET state='terminal',evidence=? WHERE id=?",
                 (json.dumps({'status': 'failed', 'environment_removed': True}), i['new_attempt_id']))
        self.sql("UPDATE tasks SET state='execution_failed',version=10")
        self.error('budget_exhausted', lambda: self.prepare(expected_version=10,
                   source_run_id=self.successor, recovery_action_id=uid(44), max_retries=1))
        j = self.prepare(expected_version=10, source_run_id=self.successor,
                         recovery_action_id=uid(44), max_retries=2)
        self.assertNotEqual(i['id'], j['id'])
        self.assertEqual(len(self.j.pending()), 1)

    def test_restart_concurrent_exactly_one(self):
        barrier = threading.Barrier(6)
        def prepare_one(_):
            j = self.journal()
            barrier.wait()
            return j.prepare(self.task, 7, self.source, 'root-policy', 2, self.action)
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(prepare_one, range(6)))
        self.assertTrue(all(i == results[0] for i in results))
        self.assertEqual(self.sql('SELECT count(*) FROM attempts'), [(2,)])
        self.assertEqual(self.journal().get(results[0]['id']), results[0])

    def test_rollback_after_partial_writes(self):
        self.sql("CREATE TRIGGER audit_fail BEFORE INSERT ON audit BEGIN SELECT RAISE(ABORT,'synthetic'); END")
        self.error('storage_error', self.prepare)
        self.assertEqual(self.sql('SELECT state,version FROM tasks'), [('execution_failed', 7)])
        self.assertEqual(self.sql('SELECT count(*) FROM attempts'), [(1,)])
        self.assertEqual(self.j.pending(), [])
        self.sql('DROP TRIGGER audit_fail')
        self.prepare()  # exception closed transaction and connection

    def test_bind_rollback_preserves_reservation(self):
        i = self.prepare()
        self.sql("CREATE TRIGGER bind_audit_fail BEFORE INSERT ON audit "
                 "WHEN NEW.event='attempt_dispatched' BEGIN SELECT RAISE(ABORT,'synthetic'); END")
        self.error('storage_error', lambda: self.j.bind(i['id'], self.run_data()))
        self.assertEqual(self.sql('SELECT state,version FROM tasks'), [('recovery_pending', 8)])
        self.assertEqual(self.sql('SELECT state,run_id FROM attempts WHERE id=?',
                                  (i['new_attempt_id'],)), [('uncertain', None)])
        self.assertEqual(self.j.get(i['id'])['phase'], 'prepared')
        self.sql('DROP TRIGGER bind_audit_fail')
        self.assertEqual(self.j.bind(i['id'], self.run_data())['phase'], 'bound')

    def test_constructor_rejects_wrong_schema_without_reset(self):
        self.sql('PRAGMA user_version=9')
        self.error('schema_version', self.journal)
        self.assertEqual(self.sql('PRAGMA user_version'), [(9,)])
        self.assertEqual(self.sql('SELECT count(*) FROM attempts'), [(1,)])

    def test_clock_and_path_fail_closed(self):
        for val in (float('nan'), float('inf'), True, '1000'):
            self.j = self.journal(lambda val=val: val)
            self.error('invalid_clock', self.prepare)
        missing = os.path.join(self.root, 'wrong.db')
        self.error('database_missing', lambda: RecoveryJournal(missing, self.agent))
        self.assertFalse(os.path.exists(missing))
        link = os.path.join(self.root, 'link.db')
        os.symlink(self.path, link)
        self.error('unsafe_path', lambda: RecoveryJournal(link, self.agent))
        parent_link = os.path.join(self.root, 'dirlink')
        os.symlink(self.root, parent_link)
        self.error('unsafe_path', lambda: RecoveryJournal(os.path.join(parent_link, 'bridge.db'), self.agent))

    def test_bind_idempotent_and_receipt(self):
        i = self.prepare()
        self.j.requesting(i['id'])
        self.j.uncertain(i['id'])
        self.now = 1010.0
        bound = self.journal().bind(i['id'], self.run_data(status='succeeded'))
        self.assertEqual(bound['phase'], 'bound')
        self.assertEqual(self.sql('SELECT state,version FROM tasks'), [('running', 9)])
        self.assertEqual(self.sql('SELECT state,run_id FROM attempts WHERE id=?', (i['new_attempt_id'],)),
                         [('running', self.successor)])
        self.assertEqual(self.j.bind(i['id'], self.run_data()), bound)
        self.assertEqual(self.j.pending(), [])
        self.assertEqual(self.sql("SELECT at FROM audit WHERE event='attempt_dispatched'"), [(1000.0,)])
        detail = json.loads(self.sql("SELECT details FROM audit WHERE event='attempt_dispatched'")[0][0])
        self.assertEqual(detail["receipt_at"], 1010.0)
        self.assertEqual(self.sql("SELECT at FROM audit WHERE event='recovery_bound'"), [(1010.0,)])
        self.error('successor_conflict', lambda: self.j.bind(i['id'], self.run_data(id=uid(77))))
        self.assertEqual(self.sql('SELECT count(*) FROM claims'), [(1,)])

    def test_bind_field_drift(self):
        i = self.prepare()
        for key in ('task_id', 'issue_id', 'agent_id', 'source_run_id', 'recovery_action_id',
                    'company_id', 'project_id'):
            self.error('binding_mismatch', lambda key=key: self.j.bind(i['id'], self.run_data(**{key: uid(99)})))
        self.error('invalid_run_status', lambda: self.j.bind(i['id'], self.run_data(status='failed')))
        self.error('run_reused', lambda: self.j.bind(i['id'], self.run_data(id=self.source)))
        self.sql('INSERT INTO attempts VALUES(?,?,?,?,?,?,?)',
                 (uid(88), uid(89), 'other', 1, 'failed', self.successor, '{}'))
        self.error('run_reused', lambda: self.j.bind(i['id'], self.run_data()))

    def test_bind_task_owner_version_and_reservation_drift(self):
        i = self.prepare()
        self.sql('UPDATE tasks SET owner=?', (uid(99),))
        self.error('owner_mismatch', lambda: self.j.bind(i['id'], self.run_data()))
        self.sql('UPDATE tasks SET owner=?,version=9', (self.owner,))
        self.error('version_mismatch', lambda: self.j.bind(i['id'], self.run_data()))
        self.sql('UPDATE tasks SET version=8')
        self.sql("UPDATE attempts SET state='terminal' WHERE id=?", (i['new_attempt_id'],))
        self.error('reservation_mismatch', lambda: self.j.bind(i['id'], self.run_data()))

    def test_phase_quarantine_and_detached_copies(self):
        i = self.prepare()
        i['profile'] = 'tamper'
        actual = self.j.get(i['id'])
        self.assertEqual(actual['profile'], self.agent)
        self.j.requesting(i['id'])
        self.error('request_already_claimed', lambda: self.j.requesting(i['id']))
        self.j.waiting(i['id'])
        self.error('phase_conflict', lambda: self.j.requesting(i['id']))
        self.now += 100000
        self.assertEqual(self.journal().pending()[0]['phase'], 'waiting')
        self.assertEqual(self.sql("SELECT state FROM attempts WHERE number=2"), [('uncertain',)])

    def test_native_terminal_schema_and_status_guards(self):
        for state in ('failed', 'execution_failed', 'cancelled', 'timed_out', 'succeeded'):
            self.sql('UPDATE attempts SET state=?', (state,))
            self.error('source_not_terminal', self.prepare)
        self.sql("UPDATE attempts SET state='terminal'")
        for status in ('succeeded', 'running', 'unknown', None):
            self.sql('UPDATE attempts SET evidence=?',
                     (json.dumps({'status': status, 'environment_removed': True}),))
            self.error('source_not_retryable', self.prepare)
        self.assertEqual(self.sql('SELECT count(*) FROM attempts'), [(1,)])

    def test_cancelled_source_accepted(self):
        self.sql('UPDATE attempts SET evidence=?',
                 (json.dumps({'status': 'cancelled', 'environment_removed': True}),))
        self.assertEqual(self.prepare()['agent_id'], self.agent)

    def test_timed_out_source_accepted(self):
        self.sql('UPDATE attempts SET evidence=?',
                 (json.dumps({'status': 'timed_out', 'environment_removed': True}),))
        self.assertEqual(self.prepare()['agent_id'], self.agent)

    def test_service_owner_and_preferred_profile(self):
        self.assertNotIn('agent_id', self.spec)
        self.spec['profile'] = uid(99)
        self.sql('UPDATE tasks SET spec=?', (json.dumps(self.spec),))
        self.error('preferred_profile_mismatch', self.prepare)
        self.spec['profile'] = self.agent
        self.sql('UPDATE tasks SET spec=?', (json.dumps(self.spec),))
        before = self.sql('SELECT owner,spec FROM tasks')
        i = self.prepare()
        self.assertEqual(i['agent_id'], self.agent)
        self.assertEqual(i['owner'], 'codex_agent')
        self.j.bind(i['id'], self.run_data())
        self.assertEqual(self.sql('SELECT owner,spec FROM tasks'), before)

    def test_other_service_and_absent_scope_fields(self):
        self.owner = 'codex_e2e_coordinator'
        spec = {k: v for k, v in self.spec.items() if k not in ('company_id', 'project_id')}
        self.sql('UPDATE tasks SET owner=?,spec=?', (self.owner, json.dumps(spec)))
        self.j = self.journal()
        i = self.prepare()
        self.assertNotIn('company_id', i)
        self.assertEqual(i['agent_id'], self.agent)
        self.assertEqual(self.j.bind(i['id'], self.run_data())['phase'], 'bound')

    def test_profile_must_be_canonical(self):
        for profile in ('synthetic-profile', None, self.agent.upper() + 'X'):
            self.sql('UPDATE attempts SET profile=?', (profile,))
            self.error('invalid_profile', self.prepare)

    def test_preferred_profile_drift_blocks_claim_and_bind(self):
        i = self.prepare()
        self.spec['profile'] = uid(99)
        self.sql('UPDATE tasks SET spec=?', (json.dumps(self.spec),))
        self.error('preferred_profile_mismatch', lambda: self.j.requesting(i['id']))
        self.error('preferred_profile_mismatch', lambda: self.j.bind(i['id'], self.run_data()))
        self.assertEqual(self.j.get(i['id'])['phase'], 'prepared')

    def test_reserved_profile_drift_blocks_claim_and_bind(self):
        i = self.prepare()
        self.sql('UPDATE attempts SET profile=? WHERE id=?', (uid(99), i['new_attempt_id']))
        self.error('reservation_mismatch', lambda: self.j.requesting(i['id']))
        self.error('reservation_mismatch', lambda: self.j.bind(i['id'], self.run_data()))

    def test_original_evidence_and_claims_unchanged_through_binding(self):
        source = self.sql('SELECT * FROM attempts WHERE id=?', (self.attempt,))
        claims = self.sql('SELECT * FROM claims')
        i = self.prepare()
        self.j.requesting(i['id'])
        self.j.uncertain(i['id'])
        self.j.bind(i['id'], self.run_data())
        self.assertEqual(self.sql('SELECT * FROM attempts WHERE id=?', (self.attempt,)), source)
        self.assertEqual(self.sql('SELECT * FROM claims'), claims)



if __name__ == '__main__':
    unittest.main()
