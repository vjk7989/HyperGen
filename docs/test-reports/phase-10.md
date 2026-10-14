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

| Gate | Result |
| --- | --- |
| Focused branding/deep-link tests | 34/34 passed |
| Focused backend media/catalog tests | 49/49 passed |
| Repaired storage/asset regressions | 13/13 passed |
| Full Node suite | 1,504/1,504 passed |
| Full Python suite | 2,536 passed; 13 skipped |
| TypeScript typecheck | Passed |
| Python Pyright | Passed, 0 errors |
| ESLint | Passed |
| Format check | Passed, 481 checked; 42 known debt files skipped by repository policy |
| Product branding guard | Passed |
| OpenAPI generation | Passed; generated title is `HyperGen Generation Server` |
| Desktop and Remote production builds | Passed |
| Graft build/check | 12,190 nodes, 32,772 edges; graph in sync |
| Tracked-path scan | Zero legacy product-name paths |

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

The native preview workflow is the remaining release gate. This section will be updated with the Actions run, published package names, and release checksums after every platform succeeds.
