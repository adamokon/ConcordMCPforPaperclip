"""Independent regressions for privilege boundaries and malformed facts."""
import copy
import uuid

import pytest

from concord_paperclip.policy import BridgeError
from concord_paperclip.recovery_evidence import derive_evidence
from concord_paperclip.recovery_host import execute
from concord_paperclip.recovery_policy import decide_recovery
from test_recovery_evidence_agent import _make_valid_fixtures


def fixtures():
    b, native, worker, producer, now = _make_valid_fixtures()
    b.update(version=4)
    native['recovery_action_id'] = str(uuid.uuid4())
    policy = dict(enabled=True, policy_id='test', allowed_repos=[b['repo']],
                  allowed_agents=[b['agent_id']], company_id=b['company_id'],
                  project_id=b['project_id'], max_retries=1, max_evidence_age=60)
    return b, native, worker, producer, now, policy


def test_duplicate_proof_keys_rejected():
    b, n, w, p, now, _ = fixtures()
    n['run']['resultJson']['stdout'] = n['run']['resultJson']['stdout'].replace('{', '{"task_id":"forged",', 1)
    evidence = derive_evidence(b, n, w, p, now)
    assert evidence['attestation'] is None
    assert evidence['provider_started'] is None


def test_stale_native_lock_blocks_even_without_active_rows():
    b, n, w, p, now, policy = fixtures()
    n['issue']['checkoutRunId'] = b['source_run_id']
    e = derive_evidence(b, n, w, p, now)
    assert e['other_run_active'] is True
    assert decide_recovery(policy, b, e, now)['action'] != 'retry'


@pytest.mark.parametrize('value', [[], {}, 10**10000], ids=['list','mapping','overflow'])
def test_malformed_values_never_authorize(value):
    b, n, w, p, now, policy = fixtures()
    e = derive_evidence(b, n, w, p, now)
    e['native_status'] = value
    assert decide_recovery(policy, b, e, now)['action'] == 'block'
    e['native_status'] = 'failed'
    e['observed_at'] = value
    assert decide_recovery(policy, b, e, now)['action'] == 'block'


def test_privileged_resolve_rechecks_reserved_budget_and_facts(monkeypatch):
    b, n, w, p, _, policy = fixtures()
    b['retries_used'] = 1
    intent = dict(id=str(uuid.uuid4()), phase='requesting', recovery_action_id=n['recovery_action_id'])
    cfg = dict(profiles={b['agent_id']: 'test-profile'}, recovery=dict(policy=policy,
        context_command=['context'], native_command=['native']))
    calls = []
    def call(command, request):
        calls.append((command, copy.deepcopy(request)))
        if command[0] == 'context':
            return dict(binding=b, intent=intent)
        if request['action'] == 'inspect':
            return dict(native=n, producer=p)
        return {'accepted': True}
    monkeypatch.setattr('concord_paperclip.recovery_host.call', call)
    monkeypatch.setattr('concord_paperclip.gateway.worker', lambda c, q: w)
    q = dict(action='recovery-resolve', task_id=b['task_id'], intent_id=intent['id'])
    assert execute(cfg, q) == {'accepted': True}
    assert calls[-1][1]['worker'] == w
    n['run']['resultJson']['stdout'] = '{}'
    with pytest.raises(BridgeError):
        execute(cfg, q)
    assert sum(r['action'] == 'resolve' for c, r in calls if 'action' in r) == 1


@pytest.mark.parametrize('extra', [{'worker': {}}, {'policy': {}}, {'command': ['arbitrary']}])
def test_gateway_rejects_caller_supplied_authority(extra):
    b, _, _, _, _, policy = fixtures()
    with pytest.raises(BridgeError, match='INVALID_REQUEST'):
        execute({'recovery': {'policy': policy}}, {'action': 'recovery-inspect', 'task_id': b['task_id'], **extra})


def test_disabled_recovery_no_backend_call(monkeypatch):
    monkeypatch.setattr('concord_paperclip.recovery_host.call', lambda *a: pytest.fail('unexpected call'))
    with pytest.raises(BridgeError, match='RECOVERY_DISABLED'):
        execute({}, {'action': 'recovery-inspect', 'task_id': str(uuid.uuid4())})


def test_missing_fixed_binary_is_stable_failure():
    from concord_paperclip.fixed_command import call
    with pytest.raises(BridgeError, match='FIXED_COMMAND_FAILED'):
        call(['/does-not-exist/concord-test-reader'], {})
