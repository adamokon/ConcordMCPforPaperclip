"""Independent integration checks at the actual receiver entrypoint."""
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from concord_paperclip.automation import gateway
from concord_paperclip.policy import BridgeError


class ActualGatewayIntegration(unittest.TestCase):
    def test_trusted_credentials_and_request_command_remains_data(self):
        command = ['fixed-reader', '{credentials}/key']
        request = {'gateway_command': ['untrusted-must-remain-data'], 'action': 'receive'}
        with patch.dict(os.environ, {'CREDENTIALS_DIRECTORY': '/synthetic/credential dir'}):
            with patch('concord_paperclip.gateway_transport.call',
                       return_value={'ok': True, 'result': {'received': True}}) as call:
                self.assertEqual(gateway({'gateway_command': command}, request), {'received': True})
                call.assert_called_once_with(['fixed-reader', '/synthetic/credential dir/key'],
                                             request, timeout=110, limit=2000000)
        self.assertEqual(command, ['fixed-reader', '{credentials}/key'])

    def test_next_real_exchange_succeeds_without_state_repair(self):
        with tempfile.TemporaryDirectory() as directory:
            flag = Path(directory) / 'flag'
            code = ("import sys,json;from pathlib import Path;sys.stdin.read();p=Path(sys.argv[1]);"
                    "sys.exit(42) if p.exists() else print(json.dumps({'ok':True,'result':{'ready':True}}))")
            config = {'gateway_command': [sys.executable, '-c', code, str(flag)]}
            flag.write_text('synthetic transport failure')
            with self.assertRaises(BridgeError) as caught:
                gateway(config, {'action': 'probe'})
            self.assertEqual(caught.exception.code, 'GATEWAY_UNAVAILABLE')
            flag.unlink()
            self.assertEqual(gateway(config, {'action': 'probe'}), {'ready': True})

    def test_response_bound_interrupts_a_still_running_producer(self):
        code = ("import sys,time;sys.stdin.read();"
                "sys.stdout.buffer.write(b'x'*2000001);sys.stdout.buffer.flush();time.sleep(4)")
        started = time.monotonic()
        with self.assertRaises(BridgeError) as caught:
            gateway({'gateway_command': [sys.executable, '-c', code]}, {'action': 'probe'})
        self.assertEqual(caught.exception.code, 'GATEWAY_UNAVAILABLE')
        self.assertLess(time.monotonic() - started, 2.0)
