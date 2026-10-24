"""test_executor_contract.py - Unit tests for repository executor contract."""

import unittest
from concord_paperclip.executor_contract import ContractError, validate_request


def _cap():
    return {
        "schema_version": 1, "repository_transport": True, "credential_free_verifier": True,
        "targets": ["aarch64-apple-darwin", "x86_64-apple-darwin", "x86_64-unknown-linux-gnu"],
        "recipes": ["cargo-check", "cargo-test", "macos-filesystem"],
        "max_files": 10000, "max_bytes": 104857600,
        "source_urls": ["https://git.proxmox.com/git/proxmox-backup.git"],
        "execution_target": "aarch64-apple-darwin",
    }


def _req():
    return {
        "schema_version": 1, "source_url": "https://git.proxmox.com/git/proxmox-backup.git",
        "commit": "78f77d53718b351bebacfa4f56f85134616e0b02", "target": "aarch64-apple-darwin",
        "checks": ["cargo-check", "cargo-test", "macos-filesystem"],
        "allowed_paths": ["Cargo.toml", "src/", "proxmox-backup-client/"],
        "max_files": 500, "max_bytes": 10485760,
    }


class TestExecutorContract(unittest.TestCase):
    def test_matching_native_execution_required(self):
        cap = dict(_cap(), execution_target="x86_64-unknown-linux-gnu")
        self.assertRaises(ContractError, validate_request, _req(), cap)
        self.assertEqual(validate_request(dict(_req(), checks=["cargo-check"]), cap)["checks"], ["cargo-check"])

    def test_trusted_sources_and_malformed_urls(self):
        url = "https://example.org/public/project.git"
        self.assertRaises(ContractError, validate_request, dict(_req(), source_url=url), _cap())
        self.assertEqual(validate_request(dict(_req(), source_url=url), dict(_cap(), source_urls=[url]))["source_url"], url)
        for bad in ("https://[broken/repo.git", "https://example.org:bad/repo.git", "https://example.org/repo.git\n"):
            self.assertRaises(ContractError, validate_request, dict(_req(), source_url=bad), _cap())

    def test_case_insensitive_private_components_and_normal_source_names(self):
        for path in (".GIT/config", "a/.ENV", ".Ssh/key", "a/.Gemini/profile"):
            self.assertRaises(ContractError, validate_request, dict(_req(), allowed_paths=[path]), _cap())
        req = dict(_req(), allowed_paths=[".gitignore", "example.env.txt"])
        self.assertEqual(validate_request(req, _cap()), req)

    def test_accepted_contracts(self):
        req, cap = _req(), _cap()
        self.assertEqual(validate_request(req, cap), req)
        linux_req = dict(_req(), target="x86_64-unknown-linux-gnu", checks=["cargo-check", "cargo-test"])
        self.assertEqual(validate_request(linux_req, cap)["target"], linux_req["target"])
        darwin_compile = dict(_req(), checks=["cargo-check"])
        self.assertEqual(validate_request(darwin_compile, cap)["checks"], ["cargo-check"])

    def test_linux_darwin_mismatch(self):
        req = dict(_req(), target="x86_64-unknown-linux-gnu", checks=["cargo-check", "macos-filesystem"])
        self.assertRaises(ContractError, validate_request, req, _cap())

    def test_unsupported_recipe_and_target(self):
        cap = dict(_cap(), recipes=["cargo-check"])
        self.assertRaises(ContractError, validate_request, _req(), cap)
        cap = dict(_cap(), targets=["x86_64-unknown-linux-gnu"])
        self.assertRaises(ContractError, validate_request, _req(), cap)
        req = dict(_req(), checks=["cargo-check", "rm -rf /"])
        self.assertRaises(ContractError, validate_request, req, _cap())

    def test_missing_transport_or_verifier(self):
        for k in ("repository_transport", "credential_free_verifier"):
            self.assertRaises(ContractError, validate_request, _req(), dict(_cap(), **{k: False}))

    def test_bool_as_int(self):
        for f in ("schema_version", "max_files", "max_bytes"):
            self.assertRaises(ContractError, validate_request, dict(_req(), **{f: True}), _cap())
            self.assertRaises(ContractError, validate_request, _req(), dict(_cap(), **{f: True}))

    def test_unknown_missing_and_invalid_types(self):
        self.assertRaises(ContractError, validate_request, dict(_req(), extra=1), _cap())
        self.assertRaises(ContractError, validate_request, _req(), dict(_cap(), extra=1))
        req_missing = _req()
        del req_missing["commit"]
        self.assertRaises(ContractError, validate_request, req_missing, _cap())
        cap_missing = _cap()
        del cap_missing["targets"]
        self.assertRaises(ContractError, validate_request, _req(), cap_missing)
        self.assertRaises(ContractError, validate_request, "not-a-dict", _cap())
        self.assertRaises(ContractError, validate_request, _req(), "not-a-dict")

    def test_bad_commit(self):
        for bad in ("78f77", "G" * 40, "78f77d53718b351bebacfa4f56f85134616e0b0G", "78F77D53718B351BEBACFA4F56F85134616E0B02", "a" * 41):
            self.assertRaises(ContractError, validate_request, dict(_req(), commit=bad), _cap())

    def test_bad_url_userinfo_query_fragment(self):
        bads = [
            "http://git.proxmox.com/git/proxmox-backup.git",
            "https://user:pass@git.proxmox.com/git/proxmox-backup.git",
            "https://user@git.proxmox.com/git/proxmox-backup.git",
            "https://git.proxmox.com/git/proxmox-backup.git?branch=main",
            "https://git.proxmox.com/git/proxmox-backup.git#head",
            "https://github.com/proxmox/proxmox-backup.git",
        ]
        for bad in bads:
            self.assertRaises(ContractError, validate_request, dict(_req(), source_url=bad), _cap())

    def test_unsafe_paths(self):
        bads = [
            "/etc/passwd", "/src/", "../traversal", "a/../b", "b/..",
            ".", "./dot", "a/./b", "b/.", "a//b", "a//b/", "//", "",
            "src/*.rs", "src/?", "src/[a-z]", "src/{a,b}",
            "foo\\bar", "foo:bar", "src/file\x00.rs", "src/file\n.rs",
            ".git", "src/.git/config", ".env", "cfg/.env", ".ssh/id_rsa", ".gemini/key",
        ]
        for bad in bads:
            self.assertRaises(ContractError, validate_request, dict(_req(), allowed_paths=[bad]), _cap())

    def test_duplicate_lists(self):
        self.assertRaises(ContractError, validate_request, dict(_req(), checks=["cargo-check", "cargo-check"]), _cap())
        self.assertRaises(ContractError, validate_request, dict(_req(), allowed_paths=["src/", "src/"]), _cap())
        self.assertRaises(ContractError, validate_request, _req(), dict(_cap(), targets=["aarch64-apple-darwin", "aarch64-apple-darwin"]))
        self.assertRaises(ContractError, validate_request, _req(), dict(_cap(), recipes=["cargo-check", "cargo-check"]))

    def test_limits(self):
        self.assertRaises(ContractError, validate_request, dict(_req(), max_files=10001), _cap())
        self.assertRaises(ContractError, validate_request, dict(_req(), max_bytes=104857601), _cap())
        for z in (0, -1):
            self.assertRaises(ContractError, validate_request, dict(_req(), max_files=z), _cap())
            self.assertRaises(ContractError, validate_request, dict(_req(), max_bytes=z), _cap())
        self.assertRaises(ContractError, validate_request, _req(), dict(_cap(), max_files=100001))
        self.assertRaises(ContractError, validate_request, _req(), dict(_cap(), max_bytes=1073741825))
        self.assertRaises(ContractError, validate_request, dict(_req(), allowed_paths=[f"f{i}.rs" for i in range(129)]), _cap())
        self.assertRaises(ContractError, validate_request, dict(_req(), allowed_paths=[]), _cap())
        self.assertRaises(ContractError, validate_request, dict(_req(), checks=[]), _cap())

    def test_deep_copy_and_immutability(self):
        req, cap = _req(), _cap()
        out = validate_request(req, cap)
        out["allowed_paths"].append("mutated/")
        out["checks"].append("extra-check")
        out["max_files"] = 999
        self.assertNotIn("mutated/", req["allowed_paths"])
        self.assertNotIn("extra-check", req["checks"])
        self.assertNotEqual(req["max_files"], 999)
        req["allowed_paths"].append("input_mutated/")
        self.assertNotIn("input_mutated/", out["allowed_paths"])


if __name__ == "__main__":
    unittest.main()
