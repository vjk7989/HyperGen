# Privacy

HyperGen is a desktop application. The HyperGen project does not operate an account service, generation proxy, or product analytics service.

## Data kept on the device

HyperGen stores application settings, provider profiles, project data, generation history, generated files, downloaded model files, and operational logs in the local app-data and model directories described in the [README](../README.md#first-run--data-locations).

Provider API keys are currently stored in plaintext in the local `video-providers.json` settings file. HyperGen trims them before storage, returns only `hasApiKey` metadata through provider settings APIs, and redacts credentials from application logs. OS keychain storage is deferred. Anyone with access to the operating-system account and HyperGen app-data directory may be able to read these credentials.

## Network activity

HyperGen makes network requests when a requested feature needs them:

- Hugging Face authentication, license retrieval, and local model downloads
- Text-to-video requests to the active LTX API, fal.ai, Replicate, Runway, Luma, Google Veo, or custom provider
- Existing API-backed image, prompt enhancement, text encoding, Retake, or other provider-specific features
- GitHub Releases update checks and package downloads
- Remote traffic directly on the local network when Same Wi-Fi mode is selected
- Encrypted Remote traffic relayed by Cloudflare Tunnel when Across the internet mode is selected

Local text-to-video does not upload the prompt or generated video to the HyperGen project. API text-to-video sends the prompt, model ID, and requested generation settings to the selected provider. A feature with media inputs may also send those inputs to the configured external service. The provider handles that data under its own privacy, retention, safety, and legal terms.

Custom-provider credentials are sent as bearer tokens to the configured base origin. HyperGen forwards that credential to a result download only when its origin matches the base URL. See the [custom provider contract](custom-provider.md) for the complete rule.

Across the internet Remote mode creates a temporary `trycloudflare.com` address
and sends paired browser traffic through Cloudflare's network to the HyperGen
instance. The tunnel runs only while that mode is active. HyperGen continues to
require one-time pairing and authenticated sessions; it does not send Remote
traffic or pairing credentials to the HyperGen project.

## Billing

Cloud generation may incur charges directly from the provider. HyperGen does not collect payment, add a surcharge, or receive billing information. Configuration validation is designed not to submit a generation, but it cannot confirm future quota, model access, content acceptance, or cost. Review the provider's current pricing and monitor usage in its dashboard.

## Telemetry and logs

HyperGen sends no product telemetry, hardware analytics, feature events, prompts, media, file paths, or crash reports to the HyperGen project. Operational logs remain on the device unless the user chooses to share them. Review logs before sharing even though known credentials are redacted.

See [Telemetry](TELEMETRY.md) for the shorter telemetry statement.
