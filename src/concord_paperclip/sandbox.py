"""Credential-free test Job: separate namespace, copied files, no PVC or SA token."""

import base64
import hashlib
import json

from .policy import BridgeError

NAMESPACE = "concord-tests"


def resources(record, image, node_selector, nonce, app_label="concord-verifier",
              seccomp_profile="concord-verifier.json"):
    digest = record["digest"]
    name = "verify-" + hashlib.sha256((digest + nonce).encode()).hexdigest()[:24]
    data = {}
    for f in record["manifest"]["files"]:
        path = f["path"]
        if "/" in path or path in {"verify_runner.py"}:
            raise BridgeError("SANDBOX_TOP_LEVEL_FILES_REQUIRED")
        if path.endswith(".py") or path == "bridge_question.json":
            data[path] = base64.b64decode(f["content_base64"], validate=True).decode("utf-8")
    has_tests = any(p.startswith("test") and p.endswith(".py") for p in data)
    if not has_tests and "bridge_question.json" not in data:
        raise BridgeError("NO_INDEPENDENT_TESTS")
    if len(json.dumps(data).encode()) > 500000:
        raise BridgeError("SANDBOX_INPUT_LIMIT")
    # -I and -S prevent inherited Python configuration. The only sys.path
    # extension is the read-only copied workspace. No provider HOME is mounted.
    data["verify_runner.py"] = (
        "import sys,unittest\n"
        "sys.path.insert(0,'/workspace')\n"
        "suite=unittest.defaultTestLoader.discover('/workspace')\n"
        "if suite.countTestCases()==0: raise SystemExit(3)\n"
        "r=unittest.TextTestRunner(verbosity=1).run(suite)\n"
        "raise SystemExit(0 if r.wasSuccessful() else 1)\n"
    )
    if not has_tests:
        # A question-only batch is not code acceptance. Validate the protocol
        # sidecar without importing or executing any partial generated code.
        data["verify_runner.py"] = (
            "import json,pathlib\n"
            "v=json.loads(pathlib.Path('/workspace/bridge_question.json').read_text())\n"
            "assert isinstance(v,dict) and isinstance(v.get('question'),str)\n"
            "assert 1<=len(v['question'])<=8000\n"
        )
    common = {"name": name, "namespace": NAMESPACE,
              "labels": {"app": app_label, "manifest": digest[:40]}}
    configmap = {"apiVersion": "v1", "kind": "ConfigMap", "metadata": common, "immutable": True, "data": data}
    job = {"apiVersion": "batch/v1", "kind": "Job", "metadata": common, "spec": {
        "activeDeadlineSeconds": 60, "backoffLimit": 0, "ttlSecondsAfterFinished": 600,
        "template": {"metadata": {"labels": {"app": app_label}}, "spec": {
            "restartPolicy": "Never", "automountServiceAccountToken": False,
            "enableServiceLinks": False, "hostNetwork": False, "hostPID": False, "hostIPC": False,
            "nodeSelector": node_selector,
            "tolerations": [{"key": k, "operator": "Equal", "value": v, "effect": "NoSchedule"}
                            for k, v in node_selector.items()],
            "securityContext": {"runAsNonRoot": True, "runAsUser": 65532, "runAsGroup": 65532,
                                "seccompProfile": {"type": "RuntimeDefault"}},
            "containers": [{"name": "tests", "image": image, "imagePullPolicy": "Never",
                "command": ["/usr/bin/python3", "-I", "-S", "-B", "/workspace/verify_runner.py"],
                "env": [{"name": "HOME", "value": "/tmp"}],
                "securityContext": {"allowPrivilegeEscalation": False, "readOnlyRootFilesystem": True,
                                    "capabilities": {"drop": ["ALL"]},
                                    "seccompProfile": ({"type": "Localhost", "localhostProfile": seccomp_profile}
                                        if app_label == "concord-verifier" else {"type": "RuntimeDefault"})},
                "resources": {"requests": {"cpu": "100m", "memory": "64Mi"},
                              "limits": {"cpu": "1", "memory": "256Mi"}},
                "volumeMounts": [{"name": "source", "mountPath": "/workspace", "readOnly": True},
                                 {"name": "tmp", "mountPath": "/tmp"}]}],
            "volumes": [{"name": "source", "configMap": {"name": name}},
                        {"name": "tmp", "emptyDir": {"medium": "Memory", "sizeLimit": "16Mi"}}]
        }}}}
    return name, configmap, job


def namespace_policy():
    return [
        {"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": NAMESPACE,
         "labels": {"pod-security.kubernetes.io/enforce": "restricted"}}},
        {"apiVersion": "networking.k8s.io/v1", "kind": "NetworkPolicy",
         "metadata": {"name": "deny-all", "namespace": NAMESPACE},
         "spec": {"podSelector": {}, "policyTypes": ["Ingress", "Egress"], "ingress": [], "egress": []}},
    ]
