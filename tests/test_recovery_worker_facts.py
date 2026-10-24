import json
from types import SimpleNamespace

import pytest

from concord_paperclip.worker_io import execute


RUN = "11111111-1111-4111-8111-111111111111"


@pytest.mark.parametrize("workspace", ["missing", "directory", "dangling_symlink"])
def test_preflight_workspace_fact_never_reads_artifacts(tmp_path, monkeypatch, workspace):
    home = tmp_path / "home"
    root = home / "workspaces" / RUN
    root.parent.mkdir(parents=True)
    if workspace == "directory":
        root.mkdir()
        (root / "result.json").write_text("untrusted model content")
    elif workspace == "dangling_symlink":
        root.symlink_to(tmp_path / "missing-target")
    monkeypatch.setattr("concord_paperclip.worker_io.subprocess.run", lambda *a, **k:
                        SimpleNamespace(returncode=0, stdout=json.dumps({"items": []}).encode()))
    config = {"kubectl": "fixed", "profiles": {"agent": {
        "home": str(home), "kubeconfig": "fixed", "namespace": "fixed"}}}
    assert execute(config, {"action": "preflight", "profile": "agent", "run_id": RUN}) == {
        "environment_removed": True, "workspace_absent": workspace == "missing"}
    assert execute(config, {"action": "check", "profile": "agent", "run_id": RUN}) == {
        "environment_removed": True}


def test_preflight_keeps_residual_job_pending(tmp_path, monkeypatch):
    monkeypatch.setattr("concord_paperclip.worker_io.subprocess.run", lambda *a, **k:
                        SimpleNamespace(returncode=0, stdout=json.dumps({"items": [{
                            "metadata": {"labels": {"agy.binzoo.io/run-id": RUN}}}]}).encode()))
    config = {"kubectl": "fixed", "profiles": {"agent": {
        "home": str(tmp_path), "kubeconfig": "fixed", "namespace": "fixed"}}}
    assert execute(config, {"action": "preflight", "profile": "agent", "run_id": RUN}) == {"pending": True}
