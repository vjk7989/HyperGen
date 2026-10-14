# Video providers

HyperGen can run text-to-video locally or submit it to one configured API provider. Choose **Local models** or **API provider** during first run. The same provider editor is available later in Settings and when generation is blocked by missing setup.

## How selection works

- HyperGen keeps one active video provider profile.
- The normal model picker selects a model offered by that active provider.
- Curated providers include a default endpoint and suggested model IDs. The model ID remains editable for new, preview, or account-specific models.
- **Test and save** checks the configuration without intentionally creating a billable generation. Current validation confirms configuration and credential presence; a provider may still reject a later request because of account access, quota, model availability, or policy.
- Requests created before provider support existed continue to use local LTX when they have no provider identifier.

Only **text-to-video** uses the general provider boundary in this release. Image-to-video, audio-to-video, Retake, Extend, LoRA, and local generation pipelines keep their existing behavior.

## Included providers

| Provider                                                                  | Get credentials                                                                                | Default endpoint                                   | Suggested models                      |
| ------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------- | -------------------------------------------------- | ------------------------------------- |
| Local models                                                              | [Hugging Face](https://huggingface.co/settings/tokens) sign-in may be needed for gated weights | On-device                                          | LTX local model selected in Settings  |
| [LTX API](https://docs.ltx.io/quickstart)                                 | [LTX Console](https://console.ltx.io/)                                                         | `https://api.ltx.io`                               | `ltx-2-5-fast`, `ltx-2-5-pro`         |
| [fal.ai](https://docs.fal.ai/)                                            | [fal dashboard](https://fal.ai/dashboard/keys)                                                 | `https://queue.fal.run`                            | Kling Video v3 text-to-video variants |
| [Replicate](https://replicate.com/docs/reference/http/)                   | [Replicate tokens](https://replicate.com/account/api-tokens)                                   | `https://api.replicate.com/v1`                     | Seedance 2.0 variants                 |
| [Runway](https://docs.dev.runwayml.com/)                                  | [Runway developer portal](https://dev.runwayml.com/)                                           | `https://api.dev.runwayml.com/v1`                  | `gen4.5`                              |
| [Luma Dream Machine](https://docs.lumalabs.ai/reference/creategeneration) | [Luma platform](https://platform.lumalabs.ai/)                                                 | `https://api.lumalabs.ai/dream-machine/v1`         | `ray-flash-2`, `ray-2`                |
| [Google Veo](https://ai.google.dev/gemini-api/docs/veo)                   | [Google AI Studio](https://aistudio.google.com/app/apikey)                                     | `https://generativelanguage.googleapis.com/v1beta` | Veo 3.1 preview variants              |
| Custom endpoint                                                           | Optional bearer token                                                                          | User supplied                                      | User supplied                         |

Provider names and models belong to their respective owners. Availability, pricing, quotas, terms, and accepted parameters can change independently of HyperGen.

## Capability-driven controls

HyperGen reads the active provider's capability description before showing or submitting shared options. This prevents known unsupported combinations from reaching a potentially billable API request.

| Provider        | Aspect ratio | Resolution     | Duration | FPS            | Audio       |
| --------------- | ------------ | -------------- | -------- | -------------- | ----------- |
| LTX API         | Editable     | Editable       | Editable | Editable       | Optional    |
| fal.ai          | Editable     | Provider fixed | Editable | Provider fixed | Optional    |
| Replicate       | Editable     | Editable       | Editable | Provider fixed | Optional    |
| Runway          | Editable     | Editable       | Editable | Provider fixed | Unsupported |
| Luma            | Editable     | Editable       | Editable | Provider fixed | Unsupported |
| Google Veo      | Editable     | Editable       | Editable | Provider fixed | Required    |
| Custom endpoint | Editable     | Editable       | Editable | Editable       | Optional    |

The exact values accepted by a provider still depend on the selected model. A provider can reject an otherwise valid shared request if the account or model has narrower rules.

## Credentials and storage

Provider API keys are stripped of surrounding whitespace and stored locally in plaintext with the provider profiles. HyperGen's settings responses expose `hasApiKey` metadata instead of secret values, and application logs redact credentials. OS keychain storage is deferred.

Anyone who can read your operating-system account's HyperGen app-data directory may be able to read the stored credentials. Use restricted keys where the provider supports them, rotate exposed credentials, and avoid sharing the settings directory or raw diagnostic files.

All curated cloud providers require a credential. A custom endpoint may run without authentication; when a key is supplied HyperGen sends it as a bearer token. See the [custom provider contract](custom-provider.md).

## Data, billing, and provider terms

Local generation keeps prompts and source media on the device, apart from separate network operations you request such as model downloads or update checks. API generation sends the prompt and shared generation settings to the selected provider. Features that accept media may send those inputs to their own existing service path.

The selected provider processes the request under its own privacy policy, retention rules, safety policy, pricing, and model terms. HyperGen does not operate a generation proxy, receive provider charges, or guarantee that a suggested model is enabled for an account. Check the provider dashboard before generation and monitor its usage there.

See [Privacy](PRIVACY.md) for local storage and network behavior.

## Custom and self-hosted services

Select **Custom endpoint**, enter the base URL and model ID, and add a key only when the server requires bearer authentication. Public endpoints must use HTTPS. HTTP is accepted for localhost, loopback, link-local, and private-network addresses used for self-hosting.

The server must implement HyperGen's asynchronous [custom text-to-video contract](custom-provider.md).
