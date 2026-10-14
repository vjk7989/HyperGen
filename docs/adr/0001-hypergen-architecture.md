# ADR 0001: HyperGen desktop architecture

- Status: Accepted
- Last updated: 2026-10-14

## Context

HyperGen provides one desktop workspace for local and API-backed media
generation. Users need to be able to explore the interface without completing
model or credential setup, then configure generation only when they choose to
submit a job. The product must work on Windows, Linux, and macOS, support secure
remote control, avoid product telemetry, and publish releases from its own
public repository.

## Decisions

### Product identity

The product name is **HyperGen**, the package name is `hypergen`, the
application identifier is `io.github.vjk7989.hypergen`, and the only desktop
deep-link protocol is `hypergen://`. Application data lives under a HyperGen
directory. Update metadata, runtime downloads, documentation, and release
artifacts use `vjk7989/HyperGen`.

Product surfaces and public documentation do not use inherited product names,
domains, logos, repositories, or compatibility identifiers. Exact third-party
model, provider, package, and repository identifiers remain where they are
required to download or invoke that dependency. Copyright and license notices
remain in `LICENSE.txt` and `NOTICES.md`.

### Application readiness

Workspace availability and generation readiness are separate states. First run
supports Local setup, API setup, and Explore. Explore persists the same setup
completion marker and opens the complete workspace without a configured
generation path.

Every generation attempt runs a preflight resolver. Ready configurations may
continue. Missing provider credentials, unavailable local models, and status
failures open a dismissible setup or retry surface. Completing setup never
submits the previous request; the user must press Generate again.

### Provider boundary

Only text-to-video uses the general provider registry. Each adapter owns
authentication, submission, polling, cancellation, download, error mapping,
and shared option translation. Existing local and specialized pipelines retain
their own executors.

Provider descriptors expose curated defaults and editable model IDs. Settings
responses return redacted configuration state and never return credentials.
Credentials remain in the existing local plaintext settings store for this
preview; operating-system keychain storage is deferred.

Custom providers implement the asynchronous contract documented in
`docs/custom-provider.md`. Public endpoints require HTTPS. HTTP is allowed only
for loopback and private network self hosting.

### Remote access

Remote has explicit Off, Same Wi-Fi, and Across internet modes. Same Wi-Fi
binds to the LAN interface. Internet mode binds only to loopback and starts the
bundled pinned `cloudflared` process after the Remote server is ready.

Both modes use one-time QR grants, authenticated sessions, device revocation,
allowlisted routes, and signed media URLs. Temporary Cloudflare hostnames are
validated before display. The tunnel process is owned by HyperGen and stops
with the backend.

### Distribution

GitHub Actions is the only official package builder. Native jobs build unsigned
Windows x64, Linux x64, and macOS arm64 packages, verify metadata and manifests,
and publish one draft release only after all platforms pass. Self-update feeds
and downloadable runtime dependencies point only to HyperGen releases.

HyperGen sends no product telemetry. Network requests occur for explicit user
features such as provider calls, model downloads, update checks, and Remote
internet mode.

## Consequences

- Users can browse projects, history, tools, and settings before configuring
  generation.
- Provider setup is reusable across first run, Settings, and generation
  preflight.
- A temporary Internet Remote address changes on every tunnel restart.
- Preview packages remain unsigned until signing credentials are supplied.
- Legal notices and exact dependency names remain visible in their appropriate
  technical or legal contexts.
