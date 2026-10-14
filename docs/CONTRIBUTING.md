# Contributing to HyperGen

Thanks for taking the time to contribute!

## Getting started (development)

Prereqs:

- Node.js
- `uv` (Python package manager)
- Python 3.12+
- Git

Setup:

```bash
pnpm setup:dev
```

Run:

```bash
pnpm dev
```

Debug:

```bash
pnpm dev:debug
```

Typecheck:

```bash
pnpm typecheck
```

Provider architecture and the external REST contract are documented in [`PROVIDERS.md`](PROVIDERS.md) and [`custom-provider.md`](custom-provider.md). Keep provider work limited to shared text-to-video behavior unless a proposal explicitly expands the scope.

## What we accept right now

- Bug fixes and small improvements
- Documentation updates
- Small, targeted UI fixes

**Frontend policy:** the frontend is under active refactor. Please avoid large UI/state rewrites for now — open an issue first so we can align on the target direction.

## Proposing larger work

Before starting a larger change (especially frontend architecture/state), please open an issue with:

- The problem you’re trying to solve
- The proposed approach (1–2 paragraphs is fine)
- Scope (areas/files likely to change)
- Any UX or compatibility impact

Wait for maintainer alignment before investing in a major refactor.

## Checks

Run the checks that cover your change. Before requesting release review, run the full quality gate:

```bash
pnpm format-check
pnpm typecheck
pnpm lint
pnpm scripts:test
pnpm openapi:check
pnpm backend:test
pnpm build:frontend
```

Provider changes should include focused tests for credential redaction, configuration defaults, URL safety, capability validation, queue state transitions, cancellation, and stable error mapping as applicable. Do not use real billable provider calls in automated tests.

Native release packages are produced only by GitHub Actions. A local package can be used for development smoke tests, but it is not an official artifact. See [`INSTALLER.md`](INSTALLER.md).
