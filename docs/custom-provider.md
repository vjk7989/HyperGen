# Custom text-to-video provider contract

HyperGen can use a self-hosted or third-party service that implements this asynchronous JSON API. Configure the service's **base URL**, **model ID**, and optional API key under **Custom endpoint**.

HyperGen appends the paths below to the base URL. A base such as `https://video.example.com/api` therefore receives submissions at `https://video.example.com/api/v1/text-to-video`.

## Authentication

When an API key is configured, HyperGen sends this header on submission, polling, and cancellation:

```http
Authorization: Bearer <api-key>
```

Authentication is optional. Leave the API key empty for a service that does not require it.

For the final video download, HyperGen sends the bearer credential only when the result URL has the same scheme, host, and effective port as the configured base URL. It does not forward the credential to a different origin. Cross-origin result URLs must be directly downloadable without that credential, for example through a short-lived signed URL.

## 1. Submit a job

```http
POST /v1/text-to-video
Content-Type: application/json
```

Request body:

```json
{
  "prompt": "A paper boat crossing a rain puddle",
  "model": "my-video-model-v1",
  "aspect_ratio": "16:9",
  "resolution": "720p",
  "duration": 5,
  "fps": 24,
  "generate_audio": false
}
```

Fields:

| Field            | Type           | Meaning                                              |
| ---------------- | -------------- | ---------------------------------------------------- |
| `prompt`         | string         | User's text prompt                                   |
| `model`          | string         | Editable model ID from the HyperGen provider profile |
| `aspect_ratio`   | string         | Requested frame aspect ratio                         |
| `resolution`     | string         | Requested output resolution                          |
| `duration`       | number or null | Requested duration in seconds                        |
| `fps`            | number         | Requested frames per second                          |
| `generate_audio` | boolean        | Whether the provider should generate audio           |

Return HTTP `200`, `201`, or `202` with:

```json
{
  "id": "job_01JABC123"
}
```

The `id` must be a non-empty URL-path-safe identifier matching `[A-Za-z0-9][A-Za-z0-9._-]*`. HyperGen inserts it into later paths without additional escaping. Additional response fields are ignored.

## 2. Poll job status

```http
GET /v1/text-to-video/{id}
```

Return HTTP `200` with:

```json
{
  "state": "running",
  "progress": 42,
  "result_url": null,
  "error": null
}
```

`state` must be exactly one of:

- `queued`
- `running`
- `succeeded`
- `failed`
- `cancelled`

`progress` is required for every state and must be a number from `0` through `100`. HyperGen rounds fractional values for its queue display. A successful response must include a valid HTTP or HTTPS `result_url`. `error` is optional; this client currently maps `failed` and `cancelled` to a stable provider-rejection error rather than displaying provider-supplied error text.

Example success:

```json
{
  "state": "succeeded",
  "progress": 100,
  "result_url": "https://video.example.com/downloads/job_01JABC123.mp4"
}
```

HyperGen polls approximately every five seconds and waits for up to one hour. The download must answer HTTP `200` with a non-empty response body.

## 3. Cancel a job

```http
POST /v1/text-to-video/{id}/cancel
Content-Type: application/json

{}
```

Return HTTP `200`, `202`, or `204` after accepting the cancellation. HyperGen calls this endpoint when a user cancels an active job. Other responses are treated as cancellation failures.

## URL safety rules

- Public base URLs and public result URLs must use HTTPS.
- HTTP base URLs are permitted for `localhost` and numeric loopback, link-local, or private-network addresses. Result URLs also accept `*.localhost`.
- Base URLs must not contain user information, passwords, query strings, or fragments.
- Result URLs may contain query strings for signed downloads, but must not contain user information, passwords, or fragments.
- Redirect handling is controlled by HyperGen's HTTP client. Services should return a final safe URL and must not rely on a redirect to receive the bearer credential.

These rules let a local service run at an address such as `http://127.0.0.1:9000` while preventing accidental cleartext credentials to a public host.

## Error handling

- HTTP `401` and `403` become authentication failures.
- HTTP `429` and `5xx` rejections are marked retryable.
- Network failures, malformed JSON, invalid states or progress, unsafe URLs, empty downloads, and timeouts become stable HyperGen provider errors.
- Unknown JSON fields are ignored so servers can add their own metadata.

Return a non-success status for a request that cannot be accepted. Do not report `succeeded` until the result URL is ready to download.
