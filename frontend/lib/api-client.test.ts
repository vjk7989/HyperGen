import assert from 'node:assert/strict'
import { describe, it } from 'node:test'
import { unwrapApiResult, ApiResultError } from '../studio/lib/unwrapApiResult.ts'
import { createApiClient } from './api-client.ts'

const uploadedAsset = {
  created_at: 1,
  id: 'asset-1',
  media_kind: 'image',
  metadata: {
    mediaType: 'image',
    metadata: { width: 8, height: 8, sizeBytes: 12 },
  },
  mime_type: 'image/png',
  name: 'photo.png',
  origin: 'uploaded',
  path: '/tmp/photo.png',
}

describe('createApiClient', () => {
  it('keeps two clients on independent fetch implementations', async () => {
    const callsA: Array<{ path: string; method: string | undefined }> = []
    const callsB: Array<{ path: string; method: string | undefined }> = []
    const clientA = createApiClient(async (path, init) => {
      callsA.push({ path, method: init?.method })
      return new Response(JSON.stringify(uploadedAsset), { status: 200 })
    })
    const clientB = createApiClient(async (path, init) => {
      callsB.push({ path, method: init?.method })
      return new Response(JSON.stringify({ ok: true }), { status: 200 })
    })

    const file = new File(['pixels'], 'photo.png', { type: 'image/png' })
    const uploaded = await clientA.uploadAsset(file)
    const health = await clientB.getHealth()

    assert.equal(uploaded.ok, true)
    assert.equal(health.ok, true)
    assert.deepEqual(callsA, [{ path: '/api/assets/upload', method: 'POST' }])
    assert.deepEqual(callsB, [{ path: '/health', method: 'GET' }])
  })
})

describe('ApiClient.uploadAsset', () => {
  it('posts multipart FormData to the remote-only upload route', async () => {
    const file = new File(['pixels'], 'photo.png', { type: 'image/png' })
    const calls: Array<{ path: string; method: string | undefined; body: unknown }> = []
    const client = createApiClient(async (path, init) => {
      calls.push({ path, method: init?.method, body: init?.body })
      return new Response(JSON.stringify(uploadedAsset), { status: 200 })
    })

    const result = await client.uploadAsset(file)

    assert.equal(calls.length, 1)
    assert.equal(calls[0]?.path, '/api/assets/upload')
    assert.equal(calls[0]?.method, 'POST')
    assert.ok(calls[0]?.body instanceof FormData)
    assert.equal(calls[0]?.body.get('file'), file)
    assert.deepEqual(result, { ok: true, data: uploadedAsset })
    assert.equal(unwrapApiResult(result).id, 'asset-1')
  })

  it('normalizes network, invalid JSON, and HTTP error results', async () => {
    const file = new File(['pixels'], 'photo.png', { type: 'image/png' })

    const network = await createApiClient(async () => {
      throw new Error('offline')
    }).uploadAsset(file)
    assert.deepEqual(network, {
      ok: false,
      status: 'default',
      error: { code: 'NETWORK_ERROR', message: 'offline' },
    })

    const invalidJson = await createApiClient(
      async () => new Response('<html>', { status: 200 }),
    ).uploadAsset(file)
    assert.equal(invalidJson.ok, false)
    if (invalidJson.ok) assert.fail('expected invalid JSON to fail')
    assert.equal(invalidJson.status, 'default')
    assert.equal(invalidJson.error.code, 'INVALID_SUCCESS_RESPONSE')

    const clientError = await createApiClient(
      async () => new Response(JSON.stringify({ code: 'TOO_LARGE', message: 'too big' }), { status: 413 }),
    ).uploadAsset(file)
    assert.deepEqual(clientError, {
      ok: false,
      status: '4XX',
      error: { code: 'TOO_LARGE', message: 'too big' },
    })

    const serverError = await createApiClient(
      async () => new Response(JSON.stringify({ code: 'BUSY', message: 'unavailable' }), { status: 503 }),
    ).uploadAsset(file)
    assert.deepEqual(serverError, {
      ok: false,
      status: '5XX',
      error: { code: 'BUSY', message: 'unavailable' },
    })

    try {
      unwrapApiResult(clientError)
      assert.fail('expected unwrapApiResult to throw')
    } catch (error) {
      assert.ok(error instanceof ApiResultError)
      assert.equal(error.code, 'TOO_LARGE')
      assert.equal(error.status, '4XX')
    }
  })
})

describe('ApiClient remote devices', () => {
  it('lists and revokes paired devices', async () => {
    const calls: Array<{ path: string; method: string | undefined }> = []
    const client = createApiClient(async (path, init) => {
      calls.push({ path, method: init?.method })
      if (path === '/api/remote/devices') {
        return new Response(JSON.stringify([]), { status: 200 })
      }
      return new Response(JSON.stringify({ status: 'ok' }), { status: 200 })
    })

    const listed = await client.listRemoteDevices()
    const revoked = await client.revokeRemoteDevice('dev-1')

    assert.equal(listed.ok, true)
    assert.equal(revoked.ok, true)
    assert.deepEqual(calls, [
      { path: '/api/remote/devices', method: 'GET' },
      { path: '/api/remote/devices/dev-1/revoke', method: 'POST' },
    ])
  })
})

describe('ApiClient video providers', () => {
  it('lists provider descriptors and redacted profiles', async () => {
    const calls: Array<{ path: string; method: string | undefined }> = []
    const client = createApiClient(async (path, init) => {
      calls.push({ path, method: init?.method })
      return new Response(
        JSON.stringify({ activeProvider: 'local', profiles: [], providers: [] }),
        { status: 200 },
      )
    })

    const result = await client.getVideoProviders()

    assert.equal(result.ok, true)
    assert.deepEqual(calls, [{ path: '/api/video-providers', method: 'GET' }])
  })

  it('updates an encoded provider id with the candidate profile body', async () => {
    const calls: Array<{
      path: string
      method: string | undefined
      body: string | undefined
    }> = []
    const client = createApiClient(async (path, init) => {
      calls.push({
        path,
        method: init?.method,
        body: typeof init?.body === 'string' ? init.body : undefined,
      })
      return new Response(
        JSON.stringify({
          providerId: 'provider/with space',
          baseUrl: 'https://video.example.test',
          modelId: 'model-1',
          hasApiKey: true,
        }),
        { status: 200 },
      )
    })
    const body = {
      baseUrl: 'https://video.example.test',
      modelId: 'model-1',
      apiKey: 'candidate-secret',
    }

    const result = await client.updateVideoProvider('provider/with space', body)

    assert.equal(result.ok, true)
    assert.deepEqual(calls, [
      {
        path: '/api/video-providers/provider%2Fwith%20space',
        method: 'PUT',
        body: JSON.stringify(body),
      },
    ])
  })

  it('validates an encoded provider id with unsaved candidate values', async () => {
    const calls: Array<{
      path: string
      method: string | undefined
      body: string | undefined
    }> = []
    const client = createApiClient(async (path, init) => {
      calls.push({
        path,
        method: init?.method,
        body: typeof init?.body === 'string' ? init.body : undefined,
      })
      return new Response(
        JSON.stringify({
          providerId: 'custom/edge',
          valid: true,
          validationMode: 'connectivity',
        }),
        { status: 200 },
      )
    })
    const candidate = {
      baseUrl: 'http://localhost:9080',
      modelId: 'self-hosted-video',
      apiKey: 'unsaved-secret',
    }

    const result = await client.validateVideoProvider('custom/edge', candidate)

    assert.equal(result.ok, true)
    assert.deepEqual(calls, [
      {
        path: '/api/video-providers/custom%2Fedge/validate',
        method: 'POST',
        body: JSON.stringify(candidate),
      },
    ])
  })

  it('selects the active provider with a typed JSON body', async () => {
    const calls: Array<{
      path: string
      method: string | undefined
      body: string | undefined
    }> = []
    const client = createApiClient(async (path, init) => {
      calls.push({
        path,
        method: init?.method,
        body: typeof init?.body === 'string' ? init.body : undefined,
      })
      return new Response(JSON.stringify({ activeProvider: 'fal' }), {
        status: 200,
      })
    })

    const result = await client.setActiveVideoProvider({ providerId: 'fal' })

    assert.equal(result.ok, true)
    assert.deepEqual(calls, [
      {
        path: '/api/video-providers/active',
        method: 'PUT',
        body: JSON.stringify({ providerId: 'fal' }),
      },
    ])
  })
})
