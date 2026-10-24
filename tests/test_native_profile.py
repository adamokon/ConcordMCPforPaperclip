"""Unit tests for native macOS Seatbelt profile and clean Cargo environment."""

import os
import unittest
from concord_paperclip.native_profile import NativePolicyError, environment, profile


class TestNativeProfile(unittest.TestCase):
    def setUp(self):
        self.ws = "/opt/workspace"
        self.tc = "/opt/toolchain"
        self.dev = "/opt/developer"
        self.sdk = "/opt/sdk"

    def test_profile_permissions_and_exclusions(self):
        pol = profile(self.ws, self.tc, self.dev)
        for expected in [
            "(version 1)",
            "(deny default)",
            "(allow process-exec process-fork sysctl-read file-read-metadata)",
            "(allow signal (target self) (target children))",
            '(subpath "/opt/developer")',
            '(subpath "/opt/toolchain")',
            '(subpath "/opt/workspace")',
            '(subpath "/System/Library")',
            '(subpath "/System/Volumes/Preboot/Cryptexes/OS")',
            '(subpath "/usr/bin")',
            '(subpath "/usr/sbin")',
            '(subpath "/usr/lib")',
            '(subpath "/usr/libexec")',
            '(subpath "/usr/share")',
            '(literal "/")',
            '(literal "/dev/null")',
            '(literal "/dev/random")',
            '(literal "/dev/urandom")',
            '(literal "/private/etc/localtime")',
            '(literal "/private/etc/ssl/openssl.cnf")',
            f'(allow file-write* (subpath "{self.ws}") (literal "/dev/null"))',
            "(deny network*)",
        ]:
            self.assertIn(expected, pol)
        for bad in ['(subpath "/System")', '(subpath "/usr")', '(subpath "/usr/local")', "(allow default)", "mach-lookup", "(allow signal\n", "(allow signal)"]:
            self.assertNotIn(bad, pol)
        self.assertEqual(pol.count("file-write*"), 1)

    def test_quoting_rule_injection(self):
        pol = profile('/opt/ws"inject', self.tc, self.dev)
        self.assertIn(r'"/opt/ws\"inject"', pol)
        self.assertNotIn('/opt/ws"inject', pol)

    def test_invalid_path_variants(self):
        invalids = [
            123, None, "", "a" * 2049, "rel/path", "/trail/", "/dup//path",
            "/dot/./path", "/dotdot/../path", "/back\\slash", "/ctrl\npath",
            "/ctrl\x00path", "/surr\ud800path", "/", "/Users", "/Volumes",
            "/System", "/Library", "/private", "/private/var", "/usr",
        ]
        for inv in invalids:
            with self.subTest(inv=inv):
                self.assertRaises(NativePolicyError, profile, inv, self.tc, self.dev)
                self.assertRaises(NativePolicyError, environment, inv, self.tc, self.sdk)

    def test_clean_environment(self):
        old_env = dict(os.environ)
        try:
            os.environ.update({"HTTP_PROXY": "http://bad", "TOKEN": "secret", "SSH_AUTH_SOCK": "/sock"})
            env = environment(self.ws, self.tc, self.sdk)
            expected = {
                "PATH": "/usr/bin:/bin", "HOME": f"{self.ws}/home",
                "CARGO_HOME": f"{self.ws}/cargo-home", "TMPDIR": f"{self.ws}/tmp",
                "RUSTC": f"{self.tc}/bin/rustc", "RUSTDOC": f"{self.tc}/bin/rustdoc",
                "SDKROOT": self.sdk, "LANG": "C.UTF-8",
            }
            self.assertEqual(env, expected)
            self.assertTrue(env["RUSTDOC"].startswith("/"))
            self.assertNotIn("HTTP_PROXY", env)
            self.assertNotIn("TOKEN", env)
        finally:
            os.environ.clear()
            os.environ.update(old_env)


if __name__ == "__main__":
    unittest.main()
