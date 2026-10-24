"""Fake policy/API only; never HTTP, SSH, credentials or provider calls."""
import copy
import concurrent.futures
import threading
import json
import unittest
from concord_paperclip.recovery_driver import RecoveryController
from concord_paperclip.recovery_state import RecoveryStateError
from test_recovery_state import Fixture, uid


def pure_policy(policy, binding, evidence, now):
    """Synthetic pure policy with the real four-argument API, action/code only."""
    if evidence['new_run'] is not None:
        return {'action': 'bind', 'code': 'native_successor'}
    if (not policy['enabled'] or binding['retries_used'] >= policy['max_retries'] or
            evidence['paused'] or evidence['terminated'] or evidence['other_run_active'] or
            evidence['error_kind'] != 'pre_provider_transient' or
            evidence['native_status'] not in ('failed', 'cancelled', 'timed_out') or
            evidence['provider_started'] is not False or
            evidence['effects'] != 'not_performed' or not evidence['cleanup_complete'] or
            evidence['attestation'] != 'trusted_pre_provider_v1' or
            not 0 <= now - evidence['observed_at'] <= policy['max_evidence_age']):
        return {'action': 'block', 'code': 'policy_denied'}
    return {'action': 'retry', 'code': 'safe_retry'}


class ControllerTests(Fixture):
    def setUp(self):
        super().setUp()
        self.binding = dict(task_id=self.task, issue_id=self.issue, agent_id=self.agent,
                            source_run_id=self.source, attempt_id=self.attempt,
                            company_id=self.company, project_id=self.project,
                            repo='public-repo', retries_used=0, version=7)
        self.evidence = {k: self.binding[k] for k in
                         ('task_id', 'issue_id', 'agent_id', 'source_run_id', 'attempt_id',
                          'company_id', 'project_id')}
        self.evidence.update(observed_at=self.now, native_status='failed', cleanup_complete=True,
                             other_run_active=False, provider_started=False, effects='not_performed',
                             attestation='trusted_pre_provider_v1', recovery_action_id=self.action,
                             error_kind='pre_provider_transient', paused=False, terminated=False, new_run=None)
        self.policy = dict(enabled=True, policy_id='root-policy', allowed_repos=['public-repo'],
                           allowed_agents=[self.agent], company_id=self.company, project_id=self.project,
                           max_retries=2, max_evidence_age=30.0)
        self.action_choice = dict(action='retry', code='retry_allowed')
        self.calls = []
        self.inspections = 0
        self.decisions = 0
        self.resolve_error = False

    def inspect_fake(self, binding):
        self.inspections += 1
        return copy.deepcopy(self.evidence)

    def decide_fake(self, policy, binding, evidence, now):
        self.decisions += 1
        return copy.deepcopy(self.action_choice)

    def resolve_fake(self, intent, evidence):
        # Durable BEFORE side effect, using an independent connection.
        self.assertEqual(self.journal().get(intent['id'])['phase'], 'requesting')
        self.calls.append(intent['id'])
        if self.resolve_error:
            raise OSError('synthetic lost response')
        return self.run_data()  # deliberately ignored until inspect proof

    def controller(self, **kw):
        args = dict(journal=self.journal(), inspect=self.inspect_fake, resolve=self.resolve_fake,
                    decide=self.decide_fake, policy=self.policy, clock=lambda: self.now)
        args.update(kw)
        return RecoveryController(**args)

    def cycle(self, **kw):
        return self.controller(**kw).cycle([self.binding])[0]

    def proof(self):
        self.evidence.update(new_run=self.run_data(), recovery_action_id=self.action)
        self.action_choice = {'action': 'bind'}

    def test_one_call_wait_and_restart_native_adoption(self):
        r = self.cycle()
        self.assertEqual(r['phase'], 'waiting')
        self.assertEqual(self.sql('SELECT state FROM tasks'), [('recovery_pending',)])
        self.assertEqual(self.cycle()['action'], 'wait')
        self.assertEqual(len(self.calls), 1)
        self.proof()
        self.binding['retries_used'] = 2  # adoption even after budget consumed
        self.assertEqual(self.cycle()['phase'], 'bound')
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.inspections, 3)
        self.assertEqual(self.decisions, 3)

    def test_lost_response_quarantined_never_resolve_twice(self):
        self.resolve_error = True
        self.assertEqual(self.cycle()['phase'], 'uncertain')
        for _ in range(3):
            self.assertEqual(self.cycle()['action'], 'wait')
        self.assertEqual(len(self.calls), 1)
        self.proof()
        self.assertEqual(self.cycle()['phase'], 'bound')
        self.assertEqual(len(self.calls), 1)

    def test_crash_after_requesting_before_api(self):
        i = self.prepare()
        self.j.requesting(i['id'])
        self.assertEqual(self.cycle()['action'], 'wait')
        self.assertEqual(self.calls, [])
        self.assertEqual(self.j.pending()[0]['phase'], 'requesting')
        self.proof()
        self.assertEqual(self.cycle()['phase'], 'bound')

    def test_waiting_commit_failure_keeps_requesting_no_second_call(self):
        journal = self.journal()
        def fail_waiting(intent_id):
            raise RecoveryStateError('storage_error')
        journal.waiting = fail_waiting
        self.assertEqual(self.cycle(journal=journal)['code'], 'storage_error')
        self.assertEqual(self.j.pending()[0]['phase'], 'requesting')
        self.assertEqual(self.cycle()['action'], 'wait')
        self.assertEqual(len(self.calls), 1)
        self.proof()
        self.assertEqual(self.cycle()['phase'], 'bound')

    def test_native_proof_adoption_with_disabled_policy(self):
        self.cycle()
        self.proof()
        self.policy['enabled'] = False
        self.policy['max_retries'] = 0
        self.assertEqual(self.cycle()['phase'], 'bound')
        self.assertEqual(len(self.calls), 1)

    def test_crash_after_prepared_resumes_once(self):
        self.prepare()
        self.assertEqual(self.cycle()['phase'], 'waiting')
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.cycle()['action'], 'wait')
        self.assertEqual(len(self.calls), 1)

    def test_crash_after_api_before_waiting_commit(self):
        i = self.prepare()
        self.j.requesting(i['id'])
        self.resolve_fake(i, self.evidence)
        self.proof()
        self.assertEqual(self.cycle()['phase'], 'bound')
        self.assertEqual(len(self.calls), 1)

    def test_pending_wait_receive_block_no_mutation(self):
        for action in ('receive', 'wait', 'block'):
            self.action_choice = {'action': action}
            self.assertEqual(self.cycle()['action'], action)
        self.assertEqual(self.sql('SELECT count(*) FROM attempts'), [(1,)])
        self.assertEqual(self.calls, [])
        i = self.prepare()
        audits = self.sql('SELECT * FROM audit')
        for action in ('receive', 'wait', 'block'):
            self.action_choice = {'action': action}
            self.assertEqual(self.cycle()['intent_id'], i['id'])
        self.assertEqual(self.sql('SELECT * FROM audit'), audits)

    def test_api_response_is_not_authority(self):
        r = self.cycle()
        self.assertEqual(r['phase'], 'waiting')
        self.action_choice = {'action': 'bind'}
        self.assertEqual(self.cycle()['code'], 'successor_unproven')
        self.assertEqual(self.sql('SELECT state FROM tasks'), [('recovery_pending',)])

    def test_no_bind_without_intent(self):
        self.proof()
        self.assertEqual(self.cycle()['code'], 'successor_unproven')
        self.assertEqual(self.calls, [])

    def test_stale_future_and_nonfinite_evidence(self):
        for value in (900.0, 1001.0, float('nan'), float('inf'), True, '1000'):
            self.evidence['observed_at'] = value
            self.assertEqual(self.cycle()['code'], 'stale_evidence')
        self.assertEqual(self.calls, [])
        self.assertEqual(self.decisions, 0)

    def test_evidence_uuid_drift_each_field(self):
        for key in ('task_id', 'issue_id', 'agent_id', 'source_run_id', 'attempt_id',
                    'company_id', 'project_id'):
            with self.subTest(key=key):
                old = self.evidence[key]
                self.evidence[key] = uid(99)
                self.assertEqual(self.cycle()['code'], 'evidence_mismatch')
                self.evidence[key] = old
        self.assertEqual(self.calls, [])

    def test_strict_evidence_types(self):
        for key, value in (('cleanup_complete', 1), ('other_run_active', None),
                           ('paused', 'false'), ('terminated', 0), ('provider_started', 0),
                           ('native_status', 'done'), ('effects', 'safe'),
                           ('attestation', 'worker says safe'), ('error_kind', 'transient'),
                           ('recovery_action_id', 'bad')):
            with self.subTest(key=key):
                old = self.evidence[key]
                self.evidence[key] = value
                self.assertEqual(self.cycle()['code'], 'invalid_evidence')
                self.evidence[key] = old
        self.assertEqual(self.decisions, 0)

    def test_successor_drift_rejected(self):
        self.cycle()
        self.proof()
        for key in ('task_id', 'issue_id', 'agent_id', 'company_id', 'project_id', 'source_run_id',
                    'recovery_action_id'):
            old = self.evidence['new_run'][key]
            self.evidence['new_run'][key] = uid(99)
            self.assertEqual(self.cycle()['code'], 'successor_mismatch')
            self.evidence['new_run'][key] = old
        self.evidence['new_run']['id'] = self.source
        self.assertEqual(self.cycle()['code'], 'successor_mismatch')
        self.assertEqual(len(self.calls), 1)

    def test_action_drift_rejected_after_lost_response(self):
        self.resolve_error = True
        self.cycle()
        self.proof()
        self.evidence['new_run']['recovery_action_id'] = uid(99)
        self.evidence['recovery_action_id'] = uid(99)
        self.assertEqual(self.cycle()['code'], 'action_mismatch')
        self.assertEqual(self.j.pending()[0]['phase'], 'uncertain')

    def test_inspect_error_only_affects_its_task(self):
        bad = dict(self.binding, task_id=uid(99))
        def inspect(b):
            if b['task_id'] == bad['task_id']:
                raise OSError('synthetic')
            return self.evidence
        outcomes = self.controller(inspect=inspect).cycle([bad, self.binding])
        self.assertEqual(outcomes[0]['code'], 'inspect_error')
        self.assertEqual(outcomes[1]['phase'], 'waiting')
        self.assertEqual(len(self.calls), 1)

    def test_root_policy_binding_and_budget_checks(self):
        self.binding['repo'] = 'unapproved'
        self.assertEqual(self.cycle()['code'], 'binding_not_allowed')
        self.binding['repo'] = 'public-repo'
        self.policy['enabled'] = False
        self.assertEqual(self.cycle()['code'], 'policy_disabled')
        self.policy['enabled'] = True
        self.binding['retries_used'] = 2
        self.assertEqual(self.cycle()['code'], 'budget_exhausted')
        self.assertEqual(self.calls, [])

    def test_invalid_policy_and_clock(self):
        for key, value in (('enabled', 1), ('max_retries', True), ('max_retries', 3),
                           ('max_evidence_age', float('nan')), ('max_evidence_age', 61),
                           ('allowed_agents', ['bad']), ('company_id', 'bad')):
            p = dict(self.policy, **{key: value})
            with self.assertRaises(RecoveryStateError):
                self.controller(policy=p)
        self.assertEqual(self.cycle(clock=lambda: float('nan'))['code'], 'invalid_clock')

    def test_bad_decision_and_decide_error(self):
        self.action_choice = {'action': 'reset_auth'}
        self.assertEqual(self.cycle()['code'], 'invalid_decision')
        def broken(*args):
            raise ValueError('synthetic')
        self.assertEqual(self.cycle(decide=broken)['code'], 'decide_error')
        self.assertEqual(self.calls, [])

    def test_concurrent_controllers_resolve_once(self):
        barrier = threading.Barrier(2)
        def decide(*args):
            barrier.wait(timeout=5)
            return self.action_choice
        # Both controllers retrieve empty pending before either prepares.
        controllers = [self.controller(decide=decide), self.controller(decide=decide)]
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda c: c.cycle([self.binding]), controllers))
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.sql('SELECT count(*) FROM attempts'), [(2,)])
        self.assertEqual(sum(r[0].get('phase') == 'waiting' for r in results), 1)

    def test_caller_and_callback_mutations_do_not_rewrite_policy(self):
        c = self.controller()
        self.policy['enabled'] = False
        self.assertTrue(c.policy['enabled'])
        original = copy.deepcopy(self.binding)
        def inspect(b):
            b['repo'] = 'tamper'
            return self.evidence
        def decide(p, b, e, now):
            b['version'] = -1
            e['new_run'] = self.run_data()
            p['enabled'] = False
            return self.action_choice
        self.assertEqual(self.cycle(inspect=inspect, decide=decide)['code'], 'policy_disabled')
        self.policy['enabled'] = True
        self.assertEqual(self.cycle(inspect=inspect, decide=decide)['phase'], 'waiting')
        self.assertEqual(self.binding, original)
        self.assertIsNone(self.evidence['new_run'])

    def test_actual_pure_signature_and_action_from_evidence(self):
        observed = []
        def decide(policy, binding, evidence, now):
            observed.append((copy.deepcopy(policy), copy.deepcopy(binding), now))
            return pure_policy(policy, binding, evidence, now)
        self.evidence['recovery_action_id'] = uid(77)
        self.assertEqual(self.cycle(decide=decide)['phase'], 'waiting')
        intent = self.j.pending()[0]
        self.assertEqual(intent['recovery_action_id'], uid(77))
        self.assertEqual(observed, [(self.policy, self.binding, self.now)])

    def test_decision_cannot_supply_missing_action_id(self):
        self.evidence['recovery_action_id'] = None
        self.action_choice['recovery_action_id'] = self.action
        self.assertEqual(self.cycle()['code'], 'invalid_action')
        self.assertEqual(self.calls, [])
        self.assertEqual(self.j.pending(), [])

    def test_prepared_restart_reserved_budget_keeps_policy(self):
        self.policy['max_retries'] = 1
        i = self.prepare(max_retries=1)
        self.binding.update(retries_used=1, version=8)
        policies = []
        def decide(policy, binding, evidence, now):
            policies.append(copy.deepcopy(policy))
            self.assertEqual(binding['retries_used'], 0)
            return pure_policy(policy, binding, evidence, now)
        self.assertEqual(self.cycle(decide=decide)['phase'], 'waiting')
        self.assertEqual(policies, [self.policy])
        self.assertEqual(self.j.get(i['id'])['max_retries'], 1)
        self.assertEqual(self.sql('SELECT count(*) FROM attempts'), [(2,)])
        self.assertEqual(len(self.calls), 1)

    def test_prepared_second_retry_keeps_prior_slot_charged(self):
        i = self.prepare()
        self.j.bind(i['id'], self.run_data())
        self.sql("UPDATE attempts SET state='terminal',evidence=? WHERE id=?",
                 (json.dumps({'status': 'failed', 'environment_removed': True}), i['new_attempt_id']))
        self.sql("UPDATE tasks SET state='execution_failed',version=10")
        second = self.prepare(expected_version=10, source_run_id=self.successor,
                              recovery_action_id=uid(44))
        self.binding.update(source_run_id=self.successor, attempt_id=i['new_attempt_id'],
                            retries_used=1, version=10)
        self.evidence.update(source_run_id=self.successor, attempt_id=i['new_attempt_id'],
                             recovery_action_id=uid(44))
        self.policy['max_retries'] = 1
        self.assertEqual(self.cycle(decide=pure_policy)['action'], 'block')
        self.assertEqual(self.j.get(second['id'])['phase'], 'prepared')
        self.assertEqual(self.calls, [])
        self.policy['max_retries'] = 2
        self.assertEqual(self.cycle(decide=pure_policy)['phase'], 'waiting')
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.sql('SELECT count(*) FROM attempts'), [(3,)])

    def test_prepared_concurrent_controllers_claim_once(self):
        self.prepare(max_retries=1)
        self.policy['max_retries'] = 1
        self.binding.update(retries_used=1, version=8)
        barrier = threading.Barrier(2)
        def decide(policy, binding, evidence, now):
            barrier.wait(timeout=5)
            return pure_policy(policy, binding, evidence, now)
        controllers = [self.controller(decide=decide) for _ in range(2)]
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda c: c.cycle([self.binding])[0], controllers))
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(sum(r.get('phase') == 'waiting' for r in results), 1)
        self.assertEqual(self.sql('SELECT count(*) FROM attempts'), [(2,)])

    def test_prepared_restart_does_not_bypass_current_policy(self):
        self.prepare(max_retries=1)
        self.binding['retries_used'] = 1
        self.policy['max_retries'] = 1
        cases = [('paused', True), ('terminated', True), ('error_kind', 'auth'),
                 ('error_kind', 'security'), ('error_kind', 'quota'),
                 ('other_run_active', True), ('provider_started', True),
                 ('effects', 'unknown'), ('cleanup_complete', False),
                 ('attestation', None), ('native_status', 'succeeded')]
        for key, value in cases:
            with self.subTest(key=key, value=value):
                old = self.evidence[key]
                self.evidence[key] = value
                self.assertEqual(self.cycle(decide=pure_policy)['action'], 'block')
                self.evidence[key] = old
        self.policy['enabled'] = False
        self.assertEqual(self.cycle(decide=pure_policy)['action'], 'block')
        self.policy['enabled'] = True
        self.policy['max_retries'] = 0
        self.assertEqual(self.cycle(decide=pure_policy)['action'], 'block')
        self.assertEqual(self.calls, [])
        self.assertEqual(self.j.pending()[0]['phase'], 'prepared')

    def test_prepared_action_and_source_guard(self):
        self.prepare()
        self.evidence['recovery_action_id'] = uid(99)
        self.assertEqual(self.cycle(decide=pure_policy)['code'], 'action_mismatch')
        self.evidence['recovery_action_id'] = self.action
        self.evidence['observed_at'] = self.now - 31
        self.assertEqual(self.cycle(decide=pure_policy)['code'], 'stale_evidence')
        self.evidence['observed_at'] = self.now
        self.sql("UPDATE attempts SET evidence=? WHERE id=?",
                 (json.dumps({'status': 'succeeded', 'environment_removed': True}), self.attempt))
        self.assertEqual(self.cycle(decide=pure_policy)['code'], 'source_not_retryable')
        self.assertEqual(self.calls, [])

    def test_prepared_scope_policy_and_profile_drift(self):
        self.prepare()
        self.policy['allowed_repos'] = []
        self.assertEqual(self.cycle(decide=pure_policy)['code'], 'binding_not_allowed')
        self.policy['allowed_repos'] = ['public-repo']
        self.policy['policy_id'] = 'different-policy'
        self.assertEqual(self.cycle(decide=pure_policy)['code'], 'intent_policy_mismatch')
        self.policy['policy_id'] = 'root-policy'
        self.spec['profile'] = uid(99)
        self.sql('UPDATE tasks SET spec=?', (json.dumps(self.spec),))
        self.assertEqual(self.cycle(decide=pure_policy)['code'], 'preferred_profile_mismatch')
        self.assertEqual(self.calls, [])

    def test_uncertain_never_reissues_even_when_policy_retries(self):
        self.resolve_error = True
        self.assertEqual(self.cycle(decide=pure_policy)['phase'], 'uncertain')
        for _ in range(2):
            self.assertEqual(self.cycle(decide=pure_policy)['action'], 'wait')
        self.proof()
        self.assertEqual(self.cycle(decide=pure_policy)['phase'], 'bound')
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.sql('SELECT count(*) FROM claims'), [(1,)])


    def test_decide_mutation_cannot_change_root_budget(self):
        self.binding['retries_used'] = 2
        def decide(policy, binding, evidence, now):
            binding['retries_used'] = 0
            policy['max_retries'] = 2
            return {'action': 'retry', 'code': 'synthetic'}
        self.assertEqual(self.cycle(decide=decide)['code'], 'budget_exhausted')
        self.assertEqual(self.calls, [])
        self.assertEqual(self.binding['retries_used'], 2)



if __name__ == '__main__':
    unittest.main()
