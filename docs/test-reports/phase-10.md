# Phase 10 Test Report: HyperGen repository identity reset

Date: 2026-10-14

## Scope

This phase removes inherited product identity from HyperGen-owned UI, source paths, protocols, storage keys, logs, public documentation, media links, update sources, and repository history. Exact third-party model/provider identifiers and required legal notices remain accurate.

## Implemented

- Renamed the main renderer module tree to `frontend/studio` and renamed code-owned symbols and CSS scope to HyperGen Studio.
- Renamed the Python entry point to `backend/hypergen_server.py` and changed API/log titles to HyperGen.
- Removed the retired desktop protocol alias and old app-data migration path.
- Replaced visible legacy logos and remote sample media with HyperGen or bundled assets.
- Pointed updater, repository metadata, and the Windows runtime dependency to `vjk7989/HyperGen`.
- Rebuilt README, ADR, handoff, and delivery ledger around HyperGen.
- Strengthened the branding guard while preserving legal files and exact dependency identifiers.

## Verification

| Gate                                 | Result                                                                |
| ------------------------------------ | --------------------------------------------------------------------- |
| Focused branding/deep-link tests     | 34/34 passed                                                          |
| Focused backend media/catalog tests  | 49/49 passed                                                          |
| Repaired storage/asset regressions   | 13/13 passed                                                          |
| Full Node suite                      | 1,504/1,504 passed                                                    |
| Full Python suite                    | 2,536 passed; 13 skipped                                              |
| TypeScript typecheck                 | Passed                                                                |
| Python Pyright                       | Passed, 0 errors                                                      |
| ESLint                               | Passed                                                                |
| Format check                         | Passed, 481 checked; 42 known debt files skipped by repository policy |
| Product branding guard               | Passed                                                                |
| OpenAPI generation                   | Passed; generated title is `HyperGen Generation Server`               |
| Desktop and Remote production builds | Passed                                                                |
| Graft build/check                    | 12,190 nodes, 32,772 edges; graph in sync                             |
| Tracked-path scan                    | Zero legacy product-name paths                                        |

## OpenCode

Independent report: `docs/test-reports/phase-10-opencode.md`.

- Discovery session: `ses_ec64ad62affeD27hqN8vbaKUvW`
- Corrected test session: `ses_ec648f7c1ffenFXUDb5pjkzX2c`
- Corrected active focused set: 25/25 passed
- OpenCode identified and documented a false-positive command that referenced three removed test filenames before rerunning the active files.

## Runtime dependency

Prepared asset:

- File: `natten-0.21.6+torch2100cu128-cp313-cp313-win_amd64.whl`
- Size: 76,533,098 bytes
- SHA-256: `BC7DFFE1D077322662B1DA5E7CADA58419D8B2ACBCB79E63A64537CA1A6C55A6`
- Target release: `runtime-deps-v1`

## Repository and release

- Public repository: `https://github.com/vjk7989/HyperGen`
- Clean root commit: `13ac6e0`
- Repository remotes: HyperGen `origin` only
- Runtime dependency release: `https://github.com/vjk7989/HyperGen/releases/tag/runtime-deps-v1`
- Runtime asset public check: HTTP 200, 76,533,098 bytes

The native preview workflow completed successfully after the two diagnosed and
repaired failures recorded below.

### Release run 38543293952

The first run stopped in the quality gate before creating a draft release. Linux Pyright correctly rejected direct access to Windows-only `ctypes` members in `backend/remote/cloudflare_tunnel.py`. The Windows Job Object boundary now resolves those members dynamically behind typed protocols.

Verification after the fix:

- Native-platform Pyright: 0 errors
- Linux-target Pyright: 0 errors
- Cloudflare lifetime, tunnel, and controller tests: 15/15 passed

### Release run 38543813493

The second run passed the complete Linux quality gate, including all Node and
Python tests, types, lint, formatting, branding, OpenAPI drift, Graft, and the
frontend build. Draft creation then failed because GitHub does not materialize
a Git tag for an unpublished draft release, while the workflow immediately
tried to fetch that tag.

The workflow now creates the exact remote tag at `GITHUB_SHA`, fetches it back,
proves its commit, and only then creates or reuses the draft. Draft creation
uses `--verify-tag`. A focused regression test verifies this ordering.

- Release workflow contract tests: 31/31 passed
- Formatting check for the regression test: passed

### Release run 38547151639

The corrected run completed successfully on 2026-10-14. The full quality gate,
draft preparation, all three native platform jobs, and final hosted-release
verification/publish job passed. The public tag, release target, and Git commit
all resolve to `ca16866849e5fdef5aeeaac943361356808b17d8`.

- Actions: `https://github.com/vjk7989/HyperGen/actions/runs/38547151639`
- Release: `https://github.com/vjk7989/HyperGen/releases/tag/v0.1.0-preview.1`
- State: published prerelease, not a draft
- Windows x64 NSIS SHA-256: `7c4e3de2f7f392d37fd386a85ff9ecf72a2e8439ad3ed01df49d9c354f3555f2`
- Linux x64 AppImage SHA-256: `544644367a9e8a0927203cade9934875456ecfb08d332414eadd45fa5f6685e4`
- Linux x64 DEB SHA-256: `84622570b7be0e0c79f832d6e228705bb61846f0ce70a3dcf95b416987c76585`
- macOS arm64 DMG SHA-256: `a7c976ee812ff59db5cb28092ee38a002643f88ba802006040ebcd7869625467`
- macOS arm64 ZIP SHA-256: `5bb877676e507cf8e3e3d90af69465bd00a834e907464bfb32805ef3ac33bd98`

The release also contains updater metadata, blockmaps, per-platform checksum
files, dependency hash, runtime manifests, and split downloadable Windows and
Linux runtime archives. The final workflow verifier checked their names, sizes,
digests, updater references, runtime reconstruction metadata, branding, and
release commit before publication.
