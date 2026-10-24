# Version and recovery review on 2026-10-24

Checked official release and public advisory endpoints before the final 0.3.0
installation. Rechecked the same official release/advisory and signature metadata
at 19:18 UTC before the 0.3.1 build; dependencies and platform versions remain
unchanged. This is a scoped compatibility decision, not a security certification.

| Component | Selected reference | Live release observation and reason |
|---|---|---|
| This bridge | 0.3.1; reviewed changes based on `9e798c337ecc516cf386822c41ddda9486a3ad5e` | Real native-readiness diagnostic fix after autonomous receipt/review. Final Git commit and package SHA256 are recorded in each local release manifest. |
| Python MCP SDK | 1.30.0, tag commit `8c2fa6eabacde869d75568e33b9d466b58c2f512` | Official latest is 2.3.0. Retain the tested 1.x API; 1.30.0 is the published 1.x fix for schema-reference fetching, OAuth discovery, redirects and HTTP session issues. No major dependency migration in this change. |
| Optional upstream Concord | 0.16.0, `f00d7c812ff708979b1784c48b0201096bc8bad5` | Matches official latest and the actual upstream MCP integration previously tested. Its advisory list was empty at check time; absence is not proof of safety. Not bundled in the bridge. |
| Paperclip integration target | Existing 2026.1005.0 deployment | Official latest is 2026.1023.0. Preserve the installed environment and authentication integration while testing its actual API. A platform upgrade needs its own compatibility and security review. |

Sources: [MCP releases](https://github.com/modelcontextprotocol/python-sdk/releases),
[MCP advisories](https://github.com/modelcontextprotocol/python-sdk/security/advisories),
[Concord release](https://github.com/Get-Concord-AI/concord-mcp/releases/tag/v0.16.0),
[Concord advisories](https://github.com/Get-Concord-AI/concord-mcp/security/advisories),
[Paperclip releases](https://github.com/paperclipai/paperclip/releases),
[Paperclip advisories](https://github.com/paperclipai/paperclip/security/advisories).

The official GitHub commit API reported `verification.verified=true` and
`reason=valid` for both selected upstream tag commits. This is verification
reported by GitHub; no independent local signature trust chain is claimed.
Response checksums and verification metadata are retained with private operator
evidence. Python distribution hashes are pinned in `uv.lock`; the selected
bridge wheel and sdist receive separate SHA256 sums in the release archive.
The bridge commit is not represented as vendor signed.

Reviewing Paperclip's published advisories does not certify the existing custom
deployment or inherited provider connectors. In particular,
[GHSA-gqqj-85qm-8qhf](https://github.com/paperclipai/paperclip/security/advisories/GHSA-gqqj-85qm-8qhf)
describes provider-connected app authority and lists no patched version.
The pilot uses only bounded public/synthetic content. It neither tests all
provider-side connectors nor changes their permissions. The new completion
capability separately restricts exact task, manifest, review and native card;
it does not expand the bridge's persistent API key.

The supported verification matrix is Python 3.11 and 3.13 on Linux, with local
macOS checks and a Linux-only process visibility test skipped on macOS. Actual
service acceptance is against the installed target, not inferred from unit tests.

## Offline recovery boundary

A release source tarball is a snapshot, not Git history. The local release archive
also contains a full bridge Git bundle, verified by cloning it into a temporary
bare repository and running `git fsck`. The optional Concord archive has a
separate full bare mirror and bundle. Existing shallow worktrees are not described
as full archives. Upstream licensing stays separate.

There are no bridge Git submodules or LFS pointers in the reviewed tree.
A lockfile records dependency versions and hashes; it is not an offline package
repository. No complete offline Python wheelhouse, upstream Node dependency store,
container registry or cluster recovery backup is claimed. Reproduction still needs
those dependencies unless provisioned separately. Credentials, native database,
provider sessions and site configuration are outside the public Git history and
source packages; recover them through the approved private operator process.
