"""Real SDK subprocess sessions plus synthetic, credential-free verifier receipts."""

import asyncio
import json
import os
import sys

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from concord_paperclip.automation import receive
from concord_paperclip.config import load_config, verifier_config
from concord_paperclip.policy import BridgeError
from test_automation import receipt


def replace_config(path, config):
    temporary = path.with_suffix('.new')
    temporary.write_text(json.dumps(config))
    temporary.chmod(0o600)
    temporary.replace(path)


def startup(tmp_path):
    return {"principal": "owner", "role": "coordinator", "task_ids": [],
            "base_url": "https://example.invalid", "company_id": "synthetic-company",
            "project_id": "synthetic-project", "database": str(tmp_path / 'bridge.db')}


async def same_session(path, exercise):
    params = StdioServerParameters(command=sys.executable,
                                  env={"PYTHONPATH": os.environ.get("PYTHONPATH", "")},
                                  args=['-m', 'concord_paperclip.cli', '--config', str(path), 'serve'])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            async def receive_results():
                reply = await session.call_tool('paperclip_receive_results', {})
                assert not reply.isError
                return json.loads(reply.content[0].text)['results']

            await exercise(receive_results)


def test_live_policy_add_change_and_fail_closed_in_same_stdio_session(tmp_path):
    path = tmp_path / 'config.json'
    original = startup(tmp_path)
    replace_config(path, original)

    async def exercise(call):
        assert (await call())['code'] == 'VERIFIER_POLICY_REQUIRED'
        current = {**original, 'verifier_seccomp_profile': 'synthetic-v1.json'}
        replace_config(path, current)
        assert await call() == []
        current['verifier_seccomp_profile'] = 'synthetic-v2.json'
        replace_config(path, current)
        assert await call() == []
        # No last-known-good fallback, even when no work exists.
        for policy, code in [(None, 'VERIFIER_POLICY_REQUIRED'), ('', 'VERIFIER_POLICY_REQUIRED'),
                             ([], 'INVALID_VERIFIER_POLICY'), (False, 'INVALID_VERIFIER_POLICY'),
                             (12, 'INVALID_VERIFIER_POLICY'), ('  ', 'INVALID_VERIFIER_POLICY')]:
            replace_config(path, {**original, 'verifier_seccomp_profile': policy})
            assert (await call())['code'] == code
        path.write_text('{invalid')
        assert (await call())['code'] == 'INVALID_CONFIG'
        path.write_text('[]')
        assert (await call())['code'] == 'INVALID_CONFIG'
        path.unlink()
        assert (await call())['code'] == 'UNSAFE_CONFIG'
        target = tmp_path / 'target.json'
        replace_config(target, current)
        path.symlink_to(target)
        assert (await call())['code'] == 'UNSAFE_CONFIG'
        path.unlink()
        path.mkdir()
        assert (await call())['code'] == 'UNSAFE_CONFIG'
        path.rmdir()
        os.mkfifo(path)
        assert (await call())['code'] == 'UNSAFE_CONFIG'
        path.unlink()
        replace_config(path, current)
        path.chmod(0o620)
        assert (await call())['code'] == 'UNSAFE_CONFIG'
        path.chmod(0o602)
        assert (await call())['code'] == 'UNSAFE_CONFIG'
        replace_config(path, current)
        assert await call() == []

    asyncio.run(same_session(path, exercise))


def test_live_boundary_drift_requires_restart_in_same_stdio_session(tmp_path):
    path = tmp_path / 'config.json'
    original = {**startup(tmp_path), 'verifier_seccomp_profile': 'synthetic-v1.json'}
    replace_config(path, original)
    drift = {'principal': 'other', 'role': 'reader', 'task_ids': ['other-task'],
             'database': str(tmp_path / 'other.db'), 'company_id': 'other-company',
             'project_id': 'other-project', 'base_url': 'https://other.invalid',
             'native_agent_id': 'other-native', 'token_file': 'not-read',
             'token_command': ['must-not-execute'], 'credential_name': 'other-credential',
             'gateway_command': ['must-not-execute'], 'trusted_http_hosts': ['other.invalid'],
             'profiles': [{'id': 'other'}], 'max_depth': 2, 'max_children': 3,
             'future_authority_field': 'also-frozen'}

    async def exercise(call):
        assert await call() == []
        for key, value in drift.items():
            replace_config(path, {**original, key: value})
            assert (await call())['code'] == 'CONFIG_RESTART_REQUIRED', key
        replace_config(path, original)
        assert await call() == []
        assert not (tmp_path / 'other.db').exists()

    asyncio.run(same_session(path, exercise))


def test_live_changed_policy_checks_real_receipt_in_same_stdio_session(setup, tmp_path):
    engine, backend, store = setup
    task, result = receipt(engine, backend)
    # Synthetic existing completed execution; no worker or remote service is run.
    engine.observe(task['id'], result['evidence'])
    result['tests']['seccomp'] = 'synthetic-v2.json'
    gateway = tmp_path / 'fixture_gateway.py'
    gateway.write_text('import json\nprint(' + repr(json.dumps({'ok': True, 'result': result})) + ')\n')
    path = tmp_path / 'config.json'
    original = {**startup(tmp_path), 'database': str(store.path),
                'gateway_command': [sys.executable, str(gateway)]}
    replace_config(path, original)
    with store.connect() as c:
        claims = c.execute('SELECT count(*) FROM claims').fetchone()[0]

    async def exercise(call):
        assert (await call())['code'] == 'VERIFIER_POLICY_REQUIRED'
        replace_config(path, {**original, 'verifier_seccomp_profile': 'synthetic-v1.json'})
        assert (await call())[0]['code'] == 'VERIFIER_POLICY_MISMATCH'
        assert engine.inspect(task['id'])['state'] == 'execution_completed'
        replace_config(path, {**original, 'verifier_seccomp_profile': 'synthetic-v2.json'})
        assert (await call())[0]['state'] == 'review_ready'
        assert await call() == []

    asyncio.run(same_session(path, exercise))
    with store.connect() as c:
        assert c.execute('SELECT count(*) FROM claims').fetchone()[0] == claims
        assert c.execute("SELECT count(*) FROM audit WHERE event='independent_tests'").fetchone()[0] == 1
    assert backend.patches == 1  # Initial synthetic dispatch only; receive never closes the issue.


def test_plain_dict_has_no_reload_origin_and_requires_explicit_policy(setup, tmp_path):
    engine, _, _ = setup
    path = tmp_path / 'not-an-origin.json'
    replace_config(path, {'verifier_seccomp_profile': 'synthetic.json'})
    with pytest.raises(BridgeError, match='VERIFIER_POLICY_REQUIRED'):
        receive(engine, {'_origin': str(path)})
    assert receive(engine, {'verifier_seccomp_profile': 'synthetic.json'}) == []


def test_startup_and_reload_reject_symlinked_parent(tmp_path):
    directory = tmp_path / 'real'
    directory.mkdir()
    alias = tmp_path / 'alias'
    alias.symlink_to(directory, target_is_directory=True)
    path = directory / 'config.json'
    replace_config(path, startup(tmp_path))
    with pytest.raises(BridgeError, match='UNSAFE_CONFIG'):
        load_config(alias / 'config.json')
    trusted = load_config(path)
    directory.rename(tmp_path / 'moved')
    directory.symlink_to(tmp_path / 'moved', target_is_directory=True)
    with pytest.raises(BridgeError, match='UNSAFE_CONFIG'):
        verifier_config(trusted)
