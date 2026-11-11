// Dependency-free frontend tests: run with `npm test` (Node's built-in test runner imports the .ts modules directly).
// They cover the pure logic: the HTTP client's error handling and the architecture layout helpers.
import assert from 'node:assert/strict'
import { afterEach, describe, test } from 'node:test'

import { columnLayout, dependencyLevels, rowLayout } from '../src/services/api/architectureLayout.ts'
import { aiStatusLabel } from '../src/services/api/aiStatus.ts'
import { readChatStream } from '../src/services/api/chatStream.ts'
import { workflowMessageFields } from '../src/services/api/workflowMessage.ts'
import { ApiRequestError, apiRequest, errorMessage } from '../src/services/http.ts'
import { isScanActive, isScanFinished } from '../src/types/repository.ts'
import { ancestorFolders } from '../src/utils/paths.ts'

globalThis.window = globalThis // the client uses window.setTimeout
const realFetch = globalThis.fetch
afterEach(() => {
  globalThis.fetch = realFetch
})

const jsonResponse = (status, body) => new Response(body === undefined ? null : JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

describe('apiRequest', () => {
  test('returns parsed JSON and sends JSON bodies', async () => {
    let seen
    globalThis.fetch = async (url, init) => {
      seen = { url, init }
      return jsonResponse(200, { ok: true })
    }
    const result = await apiRequest('/repositories', { method: 'POST', body: { path: 'C:\\x' } })
    assert.deepEqual(result, { ok: true })
    assert.equal(seen.url, 'http://localhost:8000/api/repositories')
    assert.equal(seen.init.method, 'POST')
    assert.equal(seen.init.body, '{"path":"C:\\\\x"}')
    assert.equal(seen.init.headers['Content-Type'], 'application/json')
  })

  test('204 resolves to undefined', async () => {
    globalThis.fetch = async () => new Response(null, { status: 204 })
    assert.equal(await apiRequest('/repositories/x', { method: 'DELETE' }), undefined)
  })

  test('maps the backend error shape {detail:{code,message}}', async () => {
    globalThis.fetch = async () => jsonResponse(503, { detail: { code: 'ai_not_configured', message: 'No AI provider is configured.' } })
    await assert.rejects(apiRequest('/x'), (error) => {
      assert.ok(error instanceof ApiRequestError)
      assert.equal(error.status, 503)
      assert.equal(error.code, 'ai_not_configured')
      assert.equal(error.message, 'No AI provider is configured.')
      return true
    })
  })

  test('turns FastAPI validation errors into one readable sentence', async () => {
    globalThis.fetch = async () => jsonResponse(422, { detail: [{ loc: ['body', 'path'], msg: 'Field required', type: 'missing' }] })
    await assert.rejects(apiRequest('/x'), (error) => {
      assert.equal(error.code, 'invalid_input')
      assert.match(error.message, /Invalid input \(path\): Field required/)
      return true
    })
  })

  test('connection failures say the backend is unreachable and where it was expected', async () => {
    globalThis.fetch = async () => {
      throw new TypeError('Failed to fetch')
    }
    await assert.rejects(apiRequest('/x'), (error) => {
      assert.equal(error.status, 0)
      assert.equal(error.code, 'backend_unreachable')
      assert.match(error.message, /Cannot reach the CODEMIND backend at http:\/\/localhost:8000/)
      return true
    })
  })

  test('non-JSON error bodies still produce a message', async () => {
    globalThis.fetch = async () => new Response('Internal Server Error', { status: 500 })
    await assert.rejects(apiRequest('/x'), (error) => {
      assert.equal(error.code, 'http_500')
      assert.match(error.message, /HTTP 500/)
      return true
    })
  })

  test('requests that exceed the timeout fail with a timeout error', async () => {
    globalThis.fetch = (_url, init) =>
      new Promise((_resolve, reject) => init.signal.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError'))))
    await assert.rejects(apiRequest('/slow', { timeoutMs: 30 }), (error) => error.code === 'timeout')
  })

  test('errorMessage falls back for non-errors', () => {
    assert.equal(errorMessage(new Error('boom')), 'boom')
    assert.equal(errorMessage('weird', 'fallback'), 'fallback')
  })
})

describe('scan status', () => {
  test('queued scans stay active and are not treated as finished', () => {
    assert.equal(isScanActive('queued'), true)
    assert.equal(isScanFinished('queued'), false)
    assert.equal(isScanActive('running'), true)
    assert.equal(isScanFinished('running'), false)
    assert.equal(isScanActive('completed'), false)
    assert.equal(isScanFinished('completed'), true)
    assert.equal(isScanActive('failed'), false)
    assert.equal(isScanFinished('failed'), true)
  })
})

describe('agent workflow messages', () => {
  test('restores selected agents, individual outputs, statuses, and duration from persisted workflow data', () => {
    const message = workflowMessageFields({
      id: 'assistant-1',
      requestId: 'workflow-1',
      selectedAgents: ['code-intelligence', 'code-recommendation'],
      agentStatuses: { 'code-intelligence': 'completed', 'code-recommendation': 'completed' },
      agentResults: [
        { agent: 'code-intelligence', status: 'completed', answer: 'Found a function.' },
        { agent: 'code-recommendation', status: 'completed', answer: 'Consider simplifying it.' },
      ],
      stage: 'completed',
      durationMs: 1250,
    })

    assert.equal(message.requestId, 'workflow-1')
    assert.deepEqual(message.selectedAgents, ['code-intelligence', 'code-recommendation'])
    assert.equal(message.agentResults[1].answer, 'Consider simplifying it.')
    assert.equal(message.agentSteps.length, 2)
    assert.equal(message.executionStage, 'completed')
    assert.equal(message.durationMs, 1250)
  })

  test('exposes retrieved source evidence separately from model-cited files', () => {
    const message = workflowMessageFields({
      id: 'assistant-2',
      agentResults: [
        {
          agent: 'code-intelligence',
          status: 'completed',
          answer: 'The method returns a name.',
          evidence: [
            { id: 'E1', path: 'atlas/accounts.py', startLine: 10, endLine: 14, focusLine: 12, reason: 'Contains the method.' },
            { id: 'E2', path: 'atlas/accounts.py', startLine: 10, endLine: 14, focusLine: 12, reason: 'Contains the method.' },
            { id: 'E3', path: '', startLine: 0, endLine: 0, reason: 'Repository overview.' },
          ],
        },
      ],
    })

    assert.deepEqual(message.evidenceFiles, [
      { path: 'atlas/accounts.py', line: 12, reason: 'Contains the method.' },
    ])
    assert.equal(message.files, undefined)
  })
})

describe('AI status display', () => {
  test('distinguishes a live connection from unavailable server and missing model', () => {
    assert.equal(aiStatusLabel(null), 'Checking AI status…')
    assert.equal(aiStatusLabel({ state: 'ready' }), 'Ollama connected')
    assert.equal(aiStatusLabel({ state: 'unavailable' }), 'Ollama unavailable')
    assert.equal(aiStatusLabel({ state: 'model_missing' }), 'Ollama model missing')
    assert.equal(aiStatusLabel({ state: 'timeout' }), 'Ollama timed out')
    assert.equal(aiStatusLabel({ state: 'invalid_endpoint' }), 'Invalid Ollama endpoint')
    assert.equal(aiStatusLabel({ state: 'invalid_configuration' }), 'AI not configured')
  })
})

describe('chat streaming', () => {
  test('appends SSE deltas and returns the persisted completion payload', async () => {
    const frames = [
      { type: 'delta', text: 'Widget ' },
      { type: 'delta', text: 'is a class.' },
      { type: 'complete', data: { requestId: 'workflow-1', finalResponse: 'Widget is a class.' } },
    ].map((event) => `data: ${JSON.stringify(event)}\n\n`).join('')
    const response = new Response(new ReadableStream({
      start(controller) {
        controller.enqueue(new TextEncoder().encode(frames.slice(0, 27)))
        controller.enqueue(new TextEncoder().encode(frames.slice(27)))
        controller.close()
      },
    }), { status: 200, headers: { 'Content-Type': 'text/event-stream' } })
    const deltas = []
    const result = await readChatStream(response, (chunk) => deltas.push(chunk))
    assert.deepEqual(deltas, ['Widget ', 'is a class.'])
    assert.equal(result.requestId, 'workflow-1')
    assert.equal(result.finalResponse, 'Widget is a class.')
  })

  test('surfaces provider errors from an SSE stream instead of completing with blank text', async () => {
    const frame = `data: ${JSON.stringify({ type: 'error', data: { code: 'ai_provider_error', message: 'Ollama is unavailable.' } })}\n\n`
    const response = new Response(frame, { status: 200 })
    await assert.rejects(readChatStream(response, () => {}), (error) => {
      assert.equal(error.code, 'ai_provider_error')
      assert.equal(error.message, 'Ollama is unavailable.')
      return true
    })
  })
})

describe('paths', () => {
  test('ancestorFolders lists parent folders outermost first', () => {
    assert.deepEqual(ancestorFolders('a/b/c.ts'), ['a', 'a/b'])
    assert.deepEqual(ancestorFolders('top.ts'), [])
  })
})

describe('architecture layout', () => {
  test('rowLayout gives every node its own position', () => {
    const ids = Array.from({ length: 30 }, (_, i) => `n${i}`)
    const positions = rowLayout(ids, (id) => Number(id.slice(1)) % 3)
    assert.equal(positions.size, 30)
    assert.equal(new Set([...positions.values()].map((p) => `${p.x},${p.y}`)).size, 30)
  })

  test('dependencyLevels orders a chain and survives cycles', () => {
    const chain = dependencyLevels(['a', 'b', 'c'], [{ source: 'a', target: 'b' }, { source: 'b', target: 'c' }])
    assert.ok(chain.get('a') < chain.get('b') && chain.get('b') < chain.get('c'))
    const cyclic = dependencyLevels(['a', 'b'], [{ source: 'a', target: 'b' }, { source: 'b', target: 'a' }])
    assert.equal(cyclic.size, 2)
  })

  test('columnLayout handles a large cyclic graph quickly without overlaps', () => {
    const ids = Array.from({ length: 400 }, (_, i) => `f${i}`)
    const edges = ids.map((id, i) => ({ source: id, target: ids[(i + 1) % ids.length] }))
    const started = Date.now()
    const positions = columnLayout(ids, edges)
    assert.ok(Date.now() - started < 2000)
    assert.equal(new Set([...positions.values()].map((p) => `${p.x},${p.y}`)).size, 400)
  })
})
