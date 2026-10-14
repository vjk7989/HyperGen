# Phase 10 OpenCode Test Report

Date: 2026-10-14  
Scope: independent branding, deep-link, documentation, package-identity, and tracked-path verification  
Coordinator: OpenCode CLI 1.18.35 (`opencode/big-pickle`)  
Production files edited by coordinator: none

## Sessions

- Discovery and initial run: `ses_ec64ad62affeD27hqN8vbaKUvW`
- Corrected focused run: `ses_ec648f7c1ffenFXUDb5pjkzX2c`
- Earlier blocked audit retained for traceability: `ses_ec65c0b26ffeE4GZSUaiGqnyYF`

## Commands and results

### Product branding guard

```powershell
pnpm branding:check
```

Result: **passed**, exit code 0.

Output:

```text
HyperGen product branding check passed.
```

This command executes `scripts/check-product-branding.mjs`. There is no standalone `scripts/check-product-branding.test.ts` file.

### Initial focused test command and diagnosis

```powershell
node --experimental-strip-types --test electron/hypergen-branding.test.ts electron/hypergen-deep-link.test.ts electron/hypergen-public-documentation.test.ts scripts/check-product-branding.test.ts
```

The command returned exit code 0 and reported 6 passing tests, but it was a **false positive for the requested scope**. Only `electron/hypergen-public-documentation.test.ts` existed and ran. Node silently ignored the three missing paths:

- `electron/hypergen-branding.test.ts`
- `electron/hypergen-deep-link.test.ts`
- `scripts/check-product-branding.test.ts`

OpenCode inspected the repository and mapped those stale names to the active test files before continuing.

### Corrected focused test command

```powershell
node --experimental-strip-types --test electron/hypergen-branding-guard.test.ts electron/hypergen-brand-assets.test.ts electron/hypergen-package-identity.test.ts electron/deep-link-inbox.test.ts electron/deep-link-protocol.test.ts electron/hypergen-public-documentation.test.ts
```

Result: **passed**, exit code 0.

- Tests: 25
- Passed: 25
- Failed: 0
- Test suites reported: 5, plus one top-level brand-asset test
- Duration: 393 ms

Coverage by file:

- Deep-link inbox: 8 passed
- Deep-link protocol registration: 2 passed
- HyperGen brand assets: 1 passed
- HyperGen branding guard: 3 passed
- HyperGen package and installer identity: 5 passed
- HyperGen public documentation identity: 6 passed

### Tracked-path identity scan

```powershell
git ls-files | Select-String -Pattern 'ltx-desktop|ltxdesktop|ltx-io|ltx2_server|Ltxio' -CaseSensitive:$false
```

Result: **passed**. Match count: 0.

## Conclusion

The active focused Phase 10 checks pass. The only failure found was in the original test command itself: three stale filenames produced an incomplete but green Node result. The corrected command exercised the current branding, deep-link, package, asset, and documentation tests with 25 of 25 passing.
