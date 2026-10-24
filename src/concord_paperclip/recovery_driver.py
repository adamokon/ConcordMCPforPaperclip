"""Durable orchestration; the injected Antigravity decide function owns policy.

Callbacks: inspect(binding), decide(policy, binding, evidence, now), and
 resolve(intent, evidence). decide returns action/code; the recovery action UUID
 comes only from validated fresh evidence. Callback inputs are detached copies.
 Root gateway owns native attestations, effects validation and authorization.
 Pending tasks must be supplied with their ORIGINAL seven-UUID source binding.
"""
import copy
import time
from .recovery_state import (RecoveryStateError, canonical, finite, integer,
                            nonempty, require)

UUID_FIELDS = ('task_id', 'issue_id', 'agent_id', 'source_run_id', 'attempt_id',
               'company_id', 'project_id')
RUN_FIELDS = ('task_id', 'issue_id', 'agent_id', 'company_id', 'project_id',
              'source_run_id', 'recovery_action_id')
STATUSES = ('queued', 'running', 'succeeded', 'failed', 'cancelled', 'timed_out', 'unknown')


class RecoveryController:
    def __init__(self, journal, inspect, resolve, decide, policy, clock=time.time):
        self.journal, self.inspect, self.resolve, self.decide = journal, inspect, resolve, decide
        self.policy, self.clock = copy.deepcopy(policy), clock
        self._policy()

    def _policy(self):
        p = self.policy
        require(isinstance(p, dict), 'invalid_policy')
        require(type(p.get('enabled')) is bool and nonempty(p.get('policy_id')), 'invalid_policy')
        require(integer(p.get('max_retries'), 0, 2), 'invalid_policy')
        require(finite(p.get('max_evidence_age')) and 1 <= p['max_evidence_age'] <= 60, 'invalid_policy')
        for key in ('company_id', 'project_id'):
            require(canonical(p.get(key)), 'invalid_policy')
        require(type(p.get('allowed_repos')) is list and
                all(nonempty(x) for x in p['allowed_repos']), 'invalid_policy')
        require(type(p.get('allowed_agents')) is list and
                all(canonical(x) for x in p['allowed_agents']), 'invalid_policy')

    def _binding(self, b):
        require(isinstance(b, dict), 'invalid_binding')
        require(all(canonical(b.get(k)) for k in UUID_FIELDS), 'invalid_binding')
        require(integer(b.get('retries_used'), 0) and integer(b.get('version'), 0), 'invalid_binding')
        p = self.policy
        require(b.get('repo') in p['allowed_repos'] and b['agent_id'] in p['allowed_agents'] and
                b['company_id'] == p['company_id'] and b['project_id'] == p['project_id'], 'binding_not_allowed')

    def _evidence(self, b, e):
        require(isinstance(e, dict), 'invalid_evidence')
        require(all(canonical(e.get(k)) and e[k] == b[k] for k in UUID_FIELDS), 'evidence_mismatch')
        try:
            now = self.clock()
        except Exception as exc:
            raise RecoveryStateError('invalid_clock') from exc
        require(finite(now), 'invalid_clock')
        require(finite(e.get('observed_at')) and
                0 <= now - e['observed_at'] <= self.policy['max_evidence_age'], 'stale_evidence')
        require(e.get('native_status') in STATUSES, 'invalid_evidence')
        for key in ('cleanup_complete', 'other_run_active', 'paused', 'terminated'):
            require(type(e.get(key)) is bool, 'invalid_evidence')
        require('provider_started' in e and
                (e['provider_started'] is None or type(e['provider_started']) is bool), 'invalid_evidence')
        require(e.get('effects') in ('not_performed', 'completed', 'unknown'), 'invalid_evidence')
        require('attestation' in e and e['attestation'] in
                ('trusted_pre_provider_v1', 'trusted_worker_result_v1', None), 'invalid_evidence')
        require('error_kind' in e and e['error_kind'] in
                ('pre_provider_transient', 'auth', 'quota', 'security', 'provider_failure', 'unknown', None),
                'invalid_evidence')
        require('recovery_action_id' in e and (e['recovery_action_id'] is None or
                canonical(e['recovery_action_id'])), 'invalid_evidence')
        require('new_run' in e, 'invalid_evidence')
        n = e['new_run']
        if n is not None:
            require(isinstance(n, dict) and canonical(n.get('id')) and
                    all(canonical(n.get(k)) for k in RUN_FIELDS), 'invalid_successor')
            require(n.get('status') in ('queued', 'running', 'succeeded'), 'invalid_successor')
            require(all(n[k] == b[k] for k in RUN_FIELDS if k != 'recovery_action_id'), 'successor_mismatch')
            require(n['id'] != b['source_run_id'] and
                    n['recovery_action_id'] == e['recovery_action_id'], 'successor_mismatch')
        return now

    def cycle(self, tasks):
        require(type(tasks) is list, 'invalid_tasks')
        outcomes = []
        # Retrieval failure must stop the cycle, never assume no pending work.
        pending = {i['task_id']: i for i in self.journal.pending()}
        seen = set()
        for original in tasks:
            task_id = original.get('task_id') if isinstance(original, dict) else None
            result = {'task_id': task_id}
            try:
                b = copy.deepcopy(original)
                self._binding(b)
                require(task_id not in seen, 'duplicate_task')
                seen.add(task_id)
                intent = pending.get(task_id)
                if intent:
                    for key in ('task_id', 'issue_id', 'agent_id', 'source_run_id'):
                        require(b[key] == intent[key], 'intent_binding_mismatch')
                    require(b['attempt_id'] == intent['source_attempt_id'], 'intent_binding_mismatch')
                    require(intent['policy_id'] == self.policy['policy_id'], 'intent_policy_mismatch')
                try:
                    e = copy.deepcopy(self.inspect(copy.deepcopy(b)))
                except Exception as exc:
                    raise RecoveryStateError('inspect_error') from exc
                now = self._evidence(b, e)
                evaluation = copy.deepcopy(b)
                if intent and intent['phase'] == 'prepared':
                    # retries_used may include our already reserved slot. Prior slots
                    # remain charged; neither policy nor configured max is changed.
                    evaluation['retries_used'] = max(0, b['retries_used'] - 1,
                                                     intent['retry_number'] - 1)
                try:
                    decision = copy.deepcopy(self.decide(copy.deepcopy(self.policy),
                                                        copy.deepcopy(evaluation), copy.deepcopy(e), now))
                except Exception as exc:
                    raise RecoveryStateError('decide_error') from exc
                require(isinstance(decision, dict), 'invalid_decision')
                action = decision.get('action')
                require(action in ('retry', 'bind', 'receive', 'wait', 'block'), 'invalid_decision')
                result['action'] = action
                if action == 'bind':
                    require(intent is not None and e['new_run'] is not None, 'successor_unproven')
                    require(e['recovery_action_id'] == intent['recovery_action_id'], 'action_mismatch')
                    bound = self.journal.bind(intent['id'], e['new_run'])
                    result.update(intent_id=bound['id'], phase=bound['phase'])
                elif action == 'retry':
                    if intent and intent['phase'] != 'prepared':
                        result.update(action='wait', intent_id=intent['id'], phase=intent['phase'])
                    else:
                        require(self.policy['enabled'], 'policy_disabled')
                        require(evaluation['retries_used'] < self.policy['max_retries'], 'budget_exhausted')
                        require(canonical(e['recovery_action_id']), 'invalid_action')
                        if intent:
                            require(e['recovery_action_id'] == intent['recovery_action_id'], 'action_mismatch')
                        if intent is None:
                            intent = self.journal.prepare(b['task_id'], b['version'], b['source_run_id'],
                                                          self.policy['policy_id'], self.policy['max_retries'],
                                                          e['recovery_action_id'])
                        for key in ('task_id', 'issue_id', 'agent_id', 'source_run_id'):
                            require(intent[key] == b[key], 'intent_binding_mismatch')
                        require(intent['source_attempt_id'] == b['attempt_id'], 'intent_binding_mismatch')
                        require(intent['recovery_action_id'] == e['recovery_action_id'], 'action_mismatch')
                        for key in ('company_id', 'project_id'):
                            if key in intent:
                                require(intent[key] == b[key], 'intent_binding_mismatch')
                        pending[task_id] = intent
                        # BEGIN IMMEDIATE makes this one-shot even across controllers.
                        intent = self.journal.requesting(intent['id'])
                        try:
                            self.resolve(copy.deepcopy(intent), copy.deepcopy(e))
                        except Exception:
                            intent = self.journal.uncertain(intent['id'])
                        else:
                            intent = self.journal.waiting(intent['id'])
                        result.update(intent_id=intent['id'], phase=intent['phase'])
                elif intent:
                    result.update(intent_id=intent['id'], phase=intent['phase'])
            except RecoveryStateError as exc:
                result.update(action='error', code=exc.code)
            except Exception:
                result.update(action='error', code='controller_error')
            outcomes.append(result)
        return outcomes
