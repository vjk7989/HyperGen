# HyperGen handoff

Last updated: 2026-10-14

## Current state

HyperGen is a public, cross-platform desktop studio with local generation,
multiple API providers, custom endpoints, Explore mode, project history,
editing tools, and authenticated Remote access over LAN or Cloudflare.

The current repository reset removes inherited product identity from public
documentation, UI assets, runtime logs, compatibility protocols, storage keys,
and infrastructure links. Exact third-party model/provider identifiers and
legal notices remain where technically or legally required.

The public source repository was recreated from a clean HyperGen root history at
`https://github.com/vjk7989/HyperGen`. The pinned Windows runtime dependency is
published under the `runtime-deps-v1` prerelease and its public URL, size, and
SHA-256 digest have been verified.

## Architecture map

- `frontend/` contains the desktop renderer and remote browser UI.
- `frontend/studio/` contains generation, asset, and editor surfaces.
- `electron/` owns app lifecycle, native IPC, secure URL opening, updates, and
  the Python backend process.
- `backend/` owns FastAPI routes, generation queues, providers, model execution,
  persistence, and Remote access.
- `shared/` contains deep-link and cross-process contracts.
- `.github/workflows/release.yml` builds and verifies native packages.

## Product identity contracts

- Product: `HyperGen`
- Package: `hypergen`
- App ID: `io.github.vjk7989.hypergen`
- Protocol: `hypergen://`
- Public repository and update source: `vjk7989/HyperGen`
- Product telemetry: disabled

The branding guard rejects inherited product names, domains, protocol names,
and artifact buckets outside the legal and technical allowlist. `LICENSE.txt`
and `NOTICES.md` must remain in source and packaged distributions.

## Generation contracts

- Workspace access does not require a model or API key.
- Generation readiness is checked immediately before submission.
- Provider setup is dismissible and never auto-submits a billable request.
- Text-to-video provider settings redact credentials from responses and logs.
- Custom public endpoints require HTTPS; private and loopback HTTP are allowed.

## Remote contracts

- Same Wi-Fi mode binds to the LAN.
- Across internet mode binds the origin to loopback and uses a pinned bundled
  Cloudflare tunnel client.
- The one-time pairing token is not passed to tunnel arguments or logs.
- Unauthenticated application API requests remain rejected.
- Closing HyperGen terminates the tunnel process.

## Release contracts

- Official packages are built only on native GitHub Actions runners.
- Windows x64 publishes NSIS; Linux x64 publishes AppImage and DEB; macOS arm64
  publishes DMG and ZIP.
- Preview packages are unsigned.
- Update metadata and runtime dependency downloads point to HyperGen releases.
- The release workflow creates and verifies the exact remote release tag before
  creating or reusing a draft. This is required because GitHub draft releases
  do not create a fetchable Git tag by themselves.

## Current release status

- Runtime dependency release: `runtime-deps-v1` is public and verified.
- Run `38543813493` passed the complete quality gate, then exposed the draft-tag
  issue described above.
- The exact-tag workflow fix and 31/31 release contract tests pass locally.
- The next step is to push the fix, rerun `v0.1.0-preview.1`, and record the
  published native assets and checksums here.

## Verification commands

Run from the repository root:

```powershell
pnpm branding:check
pnpm format-check
pnpm typecheck
pnpm lint
pnpm run scripts:test
pnpm backend:test
pnpm openapi:check
pnpm build:frontend
pnpm build:remote
npx --yes @nanonets/graft build
npx --yes @nanonets/graft check
```

See `to-do.md` for active status and
`docs/test-reports/phase-10.md` for the current verification ledger.
