"""Privileged recovery gateway. All identity and effect facts come from fixed readers."""
import time
import uuid

from .fixed_command import call
from .policy import BridgeError
from .recovery_evidence import derive_evidence
from .recovery_policy import decide_recovery


def execute(config, request):
    from .gateway import worker
    cfg = config.get('recovery', {})
    policy = cfg.get('policy', {})
    if policy.get('enabled') is not True:
        raise BridgeError('RECOVERY_DISABLED')
    action = request.get('action')
    expected_keys = {'action', 'task_id'} | ({'intent_id'} if action == 'recovery-resolve' else set())
    if action not in {'recovery-inspect', 'recovery-resolve'} or set(request) != expected_keys:
        raise BridgeError('INVALID_REQUEST')
    task_id = request['task_id']
    if str(uuid.UUID(task_id)) != task_id:
        raise BridgeError('INVALID_TASK_ID')
    ctx = call(cfg['context_command'] + ['--task', task_id], {})
    b, intent = ctx['binding'], ctx['intent']
    if b['task_id'] != task_id:
        raise BridgeError('CONTEXT_TASK_MISMATCH')
    raw = call(cfg['native_command'], {'action': 'inspect', 'task_id': task_id})
    facts = worker(config, {'action': 'preflight', 'profile': config['profiles'][b['agent_id']],
                            'run_id': b['source_run_id']})
    if facts.get('pending'):
        facts = {'environment_removed': False, 'workspace_absent': False}
    e = derive_evidence(b, raw['native'], facts, raw['producer'], time.time())
    if action == 'recovery-inspect':
        return e
    if (not intent or request['intent_id'] != intent['id'] or intent['phase'] != 'requesting'
            or intent['recovery_action_id'] != e['recovery_action_id']):
        raise BridgeError('RECOVERY_INTENT_MISMATCH')
    # This pending reservation has already consumed one budget unit. Revalidate
    # its original authorization without granting a second request.
    original = {**b, 'retries_used': b['retries_used'] - 1}
    if decide_recovery(policy, original, e, time.time())['action'] != 'retry':
        raise BridgeError('RECOVERY_NOT_AUTHORIZED')
    return call(cfg['native_command'], {'action': 'resolve', 'task_id': task_id,
                                        'intent_id': intent['id'], 'worker': facts})
