# Native Cargo verifier

The operator-side modules now implement immutable Git export, validated source
transport and actual native Darwin Cargo execution. They do not enable repository
generation in the existing credential-bearing Antigravity pilot. Paperclip still
owns task assignment and review. No background scheduler is introduced.

`python -m concord_paperclip.git_snapshot --repository REPO --commit FULL_SHA
--output SNAPSHOT` reads committed Git blobs only. Dirty and untracked files are
excluded. It does not checkout, invoke filters, follow symlinks, resolve LFS or
fetch submodules. Unsupported incomplete inputs fail. The operator must review
the repository's data classification before exporting it.

The source envelope binds file bytes, modes and inert link targets to the commit.
SHA-256 identifies the complete canonical envelope. Its decoder rejects duplicate
keys, size violations, traversal, private directory components and component-level
Unicode/case collisions. Backslash is a literal POSIX filename character.

## Operator setup

Install trusted Python package code and a pinned Rust distribution in locations
that build processes cannot modify. Create a dedicated non-login UID/GID, a
root-owned work root and a root-owned policy JSON. The policy contains exactly:

```json
{
  "work_root": "/private/var/tmp/native-verifier",
  "toolchain": "/opt/native-verifier/rust",
  "developer": "/Library/Developer/CommandLineTools",
  "sdk": "/Library/Developer/CommandLineTools/SDKs/MacOSX26.0.sdk",
  "uid": 5900,
  "gid": 5900,
  "target": "aarch64-apple-darwin",
  "timeout": 90,
  "max_output": 1048576
}
```

These are example operator paths and an example identity, not installation
instructions to overwrite an existing account. All paths must be canonical real
paths and root-owned. Use the actual resolved SDK path. The trusted root launcher
invokes `python -I -m concord_paperclip.native_cargo --policy POLICY --sha256 SHA256
--recipe cargo-test --task-id TASK_UUID --run-id RUN_UUID`, feeding snapshot bytes
on stdin. Never permit callers to replace the executable, policy, Python import
path or recipe argv. There is deliberately no arbitrary shell-command option.

The launcher verifies native architecture, ownership and Apple signatures for
the small protected service allowlist. It serializes use of the build UID, drops
UID/GID and supplementary groups, strips inherited environment and credentials,
and applies resource, output and wall-time limits. Seatbelt denies network and
reads outside explicit system/toolchain/SDK/source paths. Source is root-owned
read-only input; writable HOME, temporary files and Cargo target are per-run.
No source-controlled `.cargo/config.toml` is loaded from the source directory:
Cargo starts in the independent scratch directory with an explicit manifest.

Cargo always uses `--offline --locked`. Current recipes require dependencies
already supplied as source: automatic dependency downloads and a general vendor
cache are not implemented. A dependency-free Rust fixture has been executed
successfully through all three recipes on native Apple Silicon macOS. A full PBS
client build has not yet passed through this executor.

## Evidence and limitations

The root-owned receipt binds task UUID, run UUID, commit, source digest, policy
digest, recipe, native target, build UID, toolchain binary digests, output digest
and bounded process status. Cleanup kills remaining build-UID jobs, including
children that leave the original process group, then removes source and scratch.
Kernel executable identity distinguishes protected Apple per-user services from
job processes; argv text is never trusted. Exempted services are recorded.

Seatbelt and a separate UID are a host isolation boundary, not a VM. Apple can
change sandbox behavior across OS releases; production rollout requires native
negative-access tests on the actual supported versions. The receipt itself is a
local operator artifact, not a remotely signed attestation. Retention/cleanup of
bounded root-owned receipts remains the operator's responsibility.

Before advertising repository support in Paperclip, wire staging and receipts
into its existing lifecycle, implement cancellation/recovery, supply pinned
offline dependencies, and remove generated-code testing from the original
provider-credential pod. These steps remain outstanding.
