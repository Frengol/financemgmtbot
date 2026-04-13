const configuredApiBaseUrl = (import.meta.env.VITE_API_BASE_URL || '').trim().replace(/\/$/, '');
const configuredReleaseId = (import.meta.env.VITE_APP_RELEASE || '').trim();
const SAFE_TOKEN_PATTERN = /^[A-Za-z0-9_:-]{1,64}$/;

type ClientTelemetryEvent = {
  event: string;
  phase: string;
  clientEventId?: string;
  clientRequestId?: string;
  releaseId?: string;
  pagePath?: string;
  apiOrigin?: string;
  online?: boolean;
  httpStatus?: number;
  errorCode?: string;
  diagnostic?: string;
  requestId?: string;
  corsSuspected?: boolean;
};

function generateClientEventId() {
  const randomUuid = typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
    ? crypto.randomUUID().replace(/-/g, '')
    : Math.random().toString(16).slice(2);
  return `cli_${randomUuid.slice(0, 24)}`;
}

function sanitizeToken(value?: string | null) {
  const candidate = (value || '').trim();
  return SAFE_TOKEN_PATTERN.test(candidate) ? candidate : undefined;
}

export function resolveApiOrigin() {
  if (!configuredApiBaseUrl) {
    return window.location.origin;
  }

  try {
    return new URL(configuredApiBaseUrl).origin;
  } catch {
    return window.location.origin;
  }
}

function buildPublicApiUrl(path: string) {
  return `${configuredApiBaseUrl || window.location.origin}${path}`;
}

function resolveTelemetryUrl() {
  return buildPublicApiUrl('/api/client-telemetry');
}

function resolvePagePath(value?: string) {
  const candidate = (value || window.location.pathname || '/').split('?')[0].split('#')[0].trim();
  if (!candidate.startsWith('/')) {
    return window.location.pathname || '/';
  }
  return candidate.slice(0, 160);
}

function sanitizeHttpStatus(value?: number) {
  if (typeof value !== 'number' || Number.isNaN(value)) {
    return undefined;
  }
  if (value < 0 || value > 599) {
    return undefined;
  }
  return Math.trunc(value);
}

function buildTelemetryPayload(input: ClientTelemetryEvent) {
  const clientEventId = sanitizeToken(input.clientEventId) || generateClientEventId();
  const releaseId = sanitizeToken(input.releaseId) || sanitizeToken(configuredReleaseId) || 'dev-local';
  const pagePath = resolvePagePath(input.pagePath);
  const apiOrigin = input.apiOrigin || resolveApiOrigin();

  return {
    event: sanitizeToken(input.event) || 'frontend_event',
    phase: sanitizeToken(input.phase) || 'unknown_phase',
    clientEventId,
    clientRequestId: sanitizeToken(input.clientRequestId),
    releaseId,
    pagePath,
    apiOrigin,
    online: typeof input.online === 'boolean'
      ? input.online
      : typeof navigator !== 'undefined' && typeof navigator.onLine === 'boolean'
        ? navigator.onLine
        : undefined,
    httpStatus: sanitizeHttpStatus(input.httpStatus),
    errorCode: sanitizeToken(input.errorCode),
    diagnostic: sanitizeToken(input.diagnostic),
    requestId: sanitizeToken(input.requestId),
    corsSuspected: typeof input.corsSuspected === 'boolean' ? input.corsSuspected : undefined,
  };
}

export function ensureSupportCodeInMessage(message: string, clientEventId?: string) {
  if (!clientEventId || /codigo de suporte:/i.test(message)) {
    return message;
  }
  return `${message} Codigo de suporte: ${clientEventId}`;
}

export function emitClientTelemetry(input: ClientTelemetryEvent) {
  const payload = buildTelemetryPayload(input);
  const serializedPayload = JSON.stringify(payload);
  const targetUrl = resolveTelemetryUrl();

  if (typeof fetch === 'function') {
    void fetch(targetUrl, {
      method: 'POST',
      mode: 'cors',
      keepalive: true,
      headers: {
        'Content-Type': 'text/plain;charset=UTF-8',
      },
      body: serializedPayload,
    }).catch(() => {
      try {
        if (typeof navigator !== 'undefined' && typeof navigator.sendBeacon === 'function') {
          navigator.sendBeacon(targetUrl, serializedPayload);
        }
      } catch {
        // Best-effort diagnostics should never break the user flow.
      }
    });
    return payload.clientEventId;
  }

  try {
    if (typeof navigator !== 'undefined' && typeof navigator.sendBeacon === 'function') {
      navigator.sendBeacon(targetUrl, serializedPayload);
    }
  } catch {
    // Best-effort diagnostics should never break the user flow.
  }

  return payload.clientEventId;
}
