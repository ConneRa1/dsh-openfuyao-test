/** Errors surfaced by the openFuyao plugin. */

export class OpenFuyaoError extends Error {
  /**
   * @param {string} message
   * @param {{code?: string, status?: number, details?: unknown, cause?: unknown}} [options]
   */
  constructor(message, options = {}) {
    super(message, options.cause === undefined ? undefined : { cause: options.cause });
    this.name = 'OpenFuyaoError';
    this.code = options.code ?? 'OPENFUYAO_ERROR';
    this.status = options.status ?? 0;
    this.details = options.details;
  }
}

const CONNECTION_CODES = new Set([
  'ECONNREFUSED',
  'ECONNRESET',
  'EHOSTUNREACH',
  'ENETUNREACH',
  'ENOTFOUND',
  'EAI_AGAIN',
]);

/** @param {unknown} error */
export function isConnectionError(error) {
  let current = error;
  for (let depth = 0; current && depth < 5; depth += 1) {
    if (typeof current === 'object' && CONNECTION_CODES.has(current.code)) return true;
    current = current.cause;
  }
  return false;
}

/** @param {unknown} error */
export function isTimeoutError(error) {
  let current = error;
  for (let depth = 0; current && depth < 5; depth += 1) {
    if (current.name === 'TimeoutError' || current.code === 'UND_ERR_CONNECT_TIMEOUT') {
      return true;
    }
    current = current.cause;
  }
  return false;
}

/** @param {unknown} error */
export function describeError(error) {
  if (error instanceof Error) return error.message;
  return String(error);
}
