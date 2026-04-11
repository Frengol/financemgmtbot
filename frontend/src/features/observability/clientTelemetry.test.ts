import { beforeEach, describe, expect, it, vi } from 'vitest';

describe('clientTelemetry', () => {
  beforeEach(() => {
    vi.resetModules();
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
    window.sessionStorage.clear();
    window.history.pushState({}, '', '/financemgmtbot/auth/callback?token=secret#access_token=secret');
  });

  it('uses fetch keepalive before sendBeacon when the page is still active', async () => {
    vi.stubEnv('VITE_API_BASE_URL', 'https://api.example.com');
    vi.stubEnv('VITE_APP_RELEASE', '20260411abcd');
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 202 }));
    const sendBeacon = vi.fn().mockReturnValue(true);
    vi.stubGlobal('fetch', fetchMock);
    vi.stubGlobal('navigator', {
      ...navigator,
      onLine: true,
      sendBeacon,
    });

    const { emitClientTelemetry } = await import('./clientTelemetry');
    const clientEventId = emitClientTelemetry({
      event: 'auth_callback_failed',
      phase: 'callback_admin_validation',
      diagnostic: 'frontend_cross_origin_transport_failed',
    });

    expect(clientEventId).toMatch(/^cli_[a-z0-9]+$/i);
    await Promise.resolve();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(sendBeacon).not.toHaveBeenCalled();
    const [targetUrl, requestInit] = fetchMock.mock.calls[0];
    expect(targetUrl).toBe('https://api.example.com/api/client-telemetry');
    const parsedPayload = JSON.parse(requestInit.body as string);
    expect(parsedPayload).toMatchObject({
      event: 'auth_callback_failed',
      phase: 'callback_admin_validation',
      releaseId: '20260411abcd',
      pagePath: '/financemgmtbot/auth/callback',
      apiOrigin: 'https://api.example.com',
      online: true,
      diagnostic: 'frontend_cross_origin_transport_failed',
    });
    expect(parsedPayload.pagePath).not.toContain('?');
    expect(parsedPayload.pagePath).not.toContain('#');
  });

  it('falls back to sendBeacon when the keepalive fetch rejects', async () => {
    vi.stubEnv('VITE_API_BASE_URL', 'https://api.example.com');
    vi.stubEnv('VITE_APP_RELEASE', '20260411abcd');
    const fetchMock = vi.fn().mockRejectedValue(new TypeError('Failed to fetch'));
    const sendBeacon = vi.fn().mockReturnValue(true);
    vi.stubGlobal('fetch', fetchMock);
    vi.stubGlobal('navigator', {
      ...navigator,
      onLine: true,
      sendBeacon,
    });

    const { emitClientTelemetry } = await import('./clientTelemetry');
    const clientEventId = emitClientTelemetry({
      event: 'admin_api_transport_failed',
      phase: 'api_request',
      diagnostic: 'frontend_transport_failed',
    });

    expect(clientEventId).toMatch(/^cli_[a-z0-9]+$/i);
    await Promise.resolve();
    await Promise.resolve();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(sendBeacon).toHaveBeenCalledTimes(1);
    expect(sendBeacon.mock.calls[0][0]).toBe('https://api.example.com/api/client-telemetry');
  });

  it('uses sendBeacon directly when fetch is unavailable', async () => {
    vi.stubEnv('VITE_API_BASE_URL', 'https://api.example.com');
    const sendBeacon = vi.fn().mockReturnValue(true);
    vi.stubGlobal('fetch', undefined);
    vi.stubGlobal('navigator', {
      ...navigator,
      onLine: true,
      sendBeacon,
    });

    const { emitClientTelemetry } = await import('./clientTelemetry');
    emitClientTelemetry({
      event: 'auth_callback_failed',
      phase: 'callback_admin_validation',
      diagnostic: 'frontend_transport_failed',
    });

    expect(sendBeacon).toHaveBeenCalledTimes(1);
    expect(sendBeacon.mock.calls[0][0]).toBe('https://api.example.com/api/client-telemetry');
  });

  it('uses safe fallback values when telemetry input or release metadata are invalid', async () => {
    vi.stubEnv('VITE_API_BASE_URL', 'not-a-valid-url');
    vi.stubEnv('VITE_APP_RELEASE', '');
    vi.spyOn(Math, 'random').mockReturnValue(0.123456789);
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 202 }));
    vi.stubGlobal('crypto', undefined);
    vi.stubGlobal('fetch', fetchMock);
    vi.stubGlobal('navigator', {
      ...navigator,
      onLine: true,
    });

    const { emitClientTelemetry, ensureSupportCodeInMessage } = await import('./clientTelemetry');
    const clientEventId = emitClientTelemetry({
      event: 'bad event',
      phase: 'bad phase',
      pagePath: 'relative/path?token=secret#hash',
      httpStatus: 700,
      errorCode: 'bad code',
      diagnostic: 'bad diagnostic',
      requestId: 'bad request id',
    });

    expect(clientEventId).toMatch(/^cli_[a-z0-9]+$/i);
    await Promise.resolve();
    const [targetUrl, requestInit] = fetchMock.mock.calls[0];
    expect(targetUrl).toBe('not-a-valid-url/api/client-telemetry');
    const parsedPayload = JSON.parse(requestInit.body as string);
    expect(parsedPayload).toMatchObject({
      event: 'frontend_event',
      phase: 'unknown_phase',
      releaseId: 'dev-local',
      pagePath: '/financemgmtbot/auth/callback',
      apiOrigin: window.location.origin,
    });
    expect(parsedPayload).not.toHaveProperty('httpStatus');
    expect(parsedPayload).not.toHaveProperty('errorCode');
    expect(parsedPayload).not.toHaveProperty('diagnostic');
    expect(parsedPayload).not.toHaveProperty('requestId');
    expect(ensureSupportCodeInMessage('Falha sem codigo.', undefined)).toBe('Falha sem codigo.');
  });

  it('falls back to the current origin when the configured API base URL is invalid', async () => {
    vi.stubEnv('VITE_API_BASE_URL', '://broken-url');

    const { resolveApiOrigin } = await import('./clientTelemetry');

    expect(resolveApiOrigin()).toBe(window.location.origin);
  });

  it('adds the client support code only once when formatting user-facing messages', async () => {
    const { ensureSupportCodeInMessage } = await import('./clientTelemetry');

    expect(
      ensureSupportCodeInMessage('Falha temporaria.', 'cli_support_1'),
    ).toBe('Falha temporaria. Codigo de suporte: cli_support_1');
    expect(
      ensureSupportCodeInMessage('Falha temporaria. Codigo de suporte: cli_support_1', 'cli_support_1'),
    ).toBe('Falha temporaria. Codigo de suporte: cli_support_1');
  });
});
