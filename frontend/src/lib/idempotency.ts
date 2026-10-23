/**
 * Idempotency keys for write requests.
 *
 * A key is created once per action and reused for every retry of that
 * action, so a repeated request (double click, network retry) can never
 * create a second entry on the server.
 */
export function newIdempotencyKey(): string {
  const cryptoApi = globalThis.crypto
  if (cryptoApi && typeof cryptoApi.randomUUID === 'function') {
    return cryptoApi.randomUUID()
  }
  return `key-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
}
