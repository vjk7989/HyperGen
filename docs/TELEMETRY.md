# Telemetry

HyperGen sends no product telemetry or analytics.

The application does not transmit usage events, hardware profiles, feature activity, prompts, generated media, file paths, or crash reports to the HyperGen project. There is no telemetry preference because the application does not operate a telemetry service.

## Local diagnostics

HyperGen writes operational logs on the user's device so startup, model downloads, generation failures, and local services can be diagnosed. These files remain local unless the user chooses to share them.

Remote communicates with the HyperGen instance either directly on the local
network or through Cloudflare Tunnel when the user explicitly selects Across
the internet. Pairing grants and authenticated sessions protect both modes.
This traffic is not sent to the HyperGen project.

## Provider requests

Network requests required by a feature are separate from product telemetry. Examples include downloading model files from Hugging Face, checking GitHub Releases for application updates, or calling an API provider that the user configures. Data sent to those services is governed by the selected service and the user's configuration.

Local generation does not upload prompts or media to HyperGen. API backed features send only the inputs needed for the requested operation to the configured provider.

Provider credentials are stored locally in plaintext in this release. HyperGen returns only key-presence metadata through settings APIs and redacts credentials from logs. See [`PRIVACY.md`](PRIVACY.md) for credential storage, provider data flows, billing, and custom-download authentication details.
