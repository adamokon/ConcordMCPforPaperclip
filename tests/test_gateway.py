import pytest

from concord_paperclip.gateway import execute, subset
from concord_paperclip.policy import BridgeError


@pytest.mark.parametrize("payload", [None, [], {"action": "shell", "command": "id"},
    {"action": "probe", "command": "id"}, {"action": "receive", "task_id": "../../private"},
    {"action": "receive", "task_id": "bad", "paths": ["/private"]}])
def test_gateway_rejects_commands_paths_and_extra_keys(payload):
    with pytest.raises((BridgeError, ValueError)):
        execute({}, payload)


def test_resource_adoption_handles_defaults_but_rejects_extra_mounts():
    expected = {"volumes": [{"name": "public", "configMap": {"name": "snapshot"}}]}
    assert subset(expected, {"volumes": [{"name": "public", "configMap": {"name": "snapshot", "defaultMode": 420}}]})
    assert not subset(expected, {"volumes": [{"name": "public", "hostPath": {"path": "/private"}}]})
    assert not subset(expected, {"volumes": expected["volumes"] + [{"name": "extra", "secret": {}}]})
