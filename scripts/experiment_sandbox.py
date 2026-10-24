"""Operator acceptance: real credential and network isolation, with positive controls.

Run on the trusted gateway host, with its root-owned configuration. Targets must
be harmless TCP listeners reachable from the worker host, supplied by the operator.
No credentials or response bodies are read or returned.
"""

import argparse
import base64
import hashlib
import json
import subprocess

from concord_paperclip.gateway import call_apply, verify
from concord_paperclip.sandbox import NAMESPACE
from concord_paperclip.store import canonical


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--target", action="append", required=True, help="IPv4:port positive control")
    args = parser.parse_args()
    with open(args.config) as stream:
        config = json.load(stream)
    targets = []
    import ipaddress
    for target in args.target:
        host, port = target.split(":")
        targets.append((str(ipaddress.IPv4Address(host)), int(port)))
    for host, port in targets:
        # Same node, outside the denied namespace: the listener must be live.
        command = config["positive_control_command"] + ["-c",
            "import socket;socket.create_connection((" + repr(host) + "," + repr(port) + "),3).close()"]
        subprocess.run(command, check=True, capture_output=True, timeout=10)
    code = '''import errno,os,pathlib,socket,unittest
class Isolation(unittest.TestCase):
 def test_identity_and_credentials(self):
  self.assertEqual(os.getuid(),65532)
  self.assertFalse(pathlib.Path('/var/run/secrets/kubernetes.io/serviceaccount/token').exists())
  self.assertFalse(pathlib.Path('/home/agent/.gemini/antigravity-cli/antigravity-oauth-token').exists())
  self.assertFalse(any(k in os.environ for k in ['PAPERCLIP_API_KEY','GOOGLE_API_KEY','SSH_AUTH_SOCK']))
 def test_read_only_root(self):
  with self.assertRaises(OSError): pathlib.Path('/etc/concord-isolation-probe').write_text('probe')
 def test_network(self):
  for target in TARGETS:
   try: s=socket.create_connection(target,2)
   except OSError as e:
    self.assertEqual(e.errno,errno.EPERM,repr(e))
   else:
    s.close();self.fail('Network escaped deny-all')
'''.replace("TARGETS", repr(targets))
    def record(source):
        data = source.encode()
        manifest = {"schema_version": 1, "purpose": "isolation acceptance", "files": [
            {"path": "test_isolation.py", "size": len(data), "sha256": hashlib.sha256(data).hexdigest(),
             "content_base64": base64.b64encode(data).decode()}]}
        return {"manifest": manifest, "digest": hashlib.sha256(canonical(manifest).encode()).hexdigest()}
    # Positive control in the SAME namespace/image/UID, but an operator-only
    # label temporarily permits exactly these targets. Verifier pods never get it.
    label = "concord-isolation-positive"
    allow = {"apiVersion": "networking.k8s.io/v1", "kind": "NetworkPolicy",
             "metadata": {"name": label, "namespace": NAMESPACE}, "spec": {
             "podSelector": {"matchLabels": {"app": label}}, "policyTypes": ["Egress"],
             "egress": [{"to": [{"ipBlock": {"cidr": host + "/32"}}],
                         "ports": [{"protocol": "TCP", "port": port}]} for host, port in targets]}}
    positive_code = ("import socket,unittest\nclass Positive(unittest.TestCase):\n"
                     " def test_listeners(self):\n"
                     "  for target in " + repr(targets) + ": socket.create_connection(target,3).close()\n")
    call_apply(config["kubectl_command"], allow)
    try:
        positive = verify(config, record(positive_code), control_label=label)
        result = verify(config, record(code))
    finally:
        subprocess.run(config["kubectl_command"] + ["delete", "networkpolicy", label, "-n", NAMESPACE,
                                                    "--ignore-not-found"], capture_output=True, timeout=15)
    print(canonical({"positive_controls": len(targets), "positive_pod": positive, "verification": result}))
    if result["status"] != "passed" or positive["status"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
