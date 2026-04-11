import { beforeEach, describe, expect, it, vi } from 'vitest';

describe('clientTelemetry', () => {
  beforeEach(() => {
    vi.resetModules();
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
    window.history.pushState({}, '', '/financemgmtbot/auth/callback?token=secret#access_token=secret');
  });

  it('sends a sanitized browser telemetry event with sendBeacon when available', async () => {
    vi.stubEnv('VITE_API_BASE_URL', 'https://api.example.com');
    vi.stubEnv('VITE_APP_RELEASE', '20260411abcd');
    const sendBeacon = vi.fn().mockReturnValue(true);
    vi.stubGlobal('navigator', {
      ...navigator,
      onLine: true,
      sendBeacon,
    });

    const { emitClientTelemetry } = await import('./clientTelemetry');
    const clientEventId = emitClientTelemetry({
      event: 'auth_callback_failed',
      phase: 'callback_admin_validation',
      diagnostic: 'frontend_transport_failed',
    });

    expect(clientEventId).toMatch(/^cli_[a-z0-9]+$/i);
    expect(sendBeacon).toHaveBeenCalledTimes(1);
    const [targetUrl, payload] = sendBeacon.mock.calls[0];
    expect(targetUrl).toBe('https://api.example.com/api/client-telemetry');
    const parsedPayload = JSON.parse(payload as string);
    expect(parsedPayload).toMatchObject({
      event: 'auth_callback_failed',
      phase: 'callback_admin_validation',
      releaseId: '20260411abcd',
      pagePath: '/financemgmtbot/auth/callback',
      apiOrigin: 'https://api.example.com',
      online: true,
      diagnostic: 'frontend_transport_failed',
    });
    expect(parsedPayload.pagePath).not.toContain('?');
    expect(parsedPayload.pagePath).not.toContain('#');
  });

  it('falls back to fetch keepalive when sendBeacon is unavailable', async () => {
    vi.stubEnv('VITE_API_BASE_URL', 'https://api.example.com');
    vi.stubEnv('VITE_APP_RELEASE', '20260411abcd');
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 202 }));
    vi.stubGlobal('fetch', fetchMock);
    vi.stubGlobal('navigator', {
      ...navigator,
      onLine: false,
    });

    const { emitClientTelemetry } = await import('./clientTelemetry');
    const clientEventId = emitClientTelemetry({
      event: 'admin_api_transport_failed',
      phase: 'api_request',
      diagnostic: 'frontend_transport_failed',
      corsSuspected: false,
    });

    expect(clientEventId).toMatch(/^cli_[a-z0-9]+$/i);
    await Promise.resolve();
    expect(fetchMock).toHaveBeenCalledWith(
      'https://api.example.com/api/client-telemetry',
      expect.objectContaining({
        method: 'POST',
        keepalive: true,
      }),
    );
  });

  it('uses safe fallback values when telemetry input or release metadata are invalid', async () => {
    vi.stubEnv('VITE_API_BASE_URL', 'not-a-valid-url');
    vi.stubEnv('VITE_APP_RELEASE', '');
    vi.spyOn(Math, 'random').mockReturnValue(0.123456789);
    const sendBeacon = vi.fn().mockReturnValue(false);
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 202 }));
    vi.stubGlobal('crypto', undefined);
    vi.stubGlobal('fetch', fetchMock);
    vi.stubGlobal('navigator', {
      sendBeacon,
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

  it('falls back to window origin and keeps valid http status values', async () => {
    vi.stubEnv('VITE_API_BASE_URL', '');
    vi.stubEnv('VITE_APP_RELEASE', '20260411abcd');
    const sendBeacon = vi.fn().mockReturnValue(true);
    vi.stubGlobal('navigator', {
      ...navigator,
      onLine: true,
      sendBeacon,
    });

    const { emitClientTelemetry } = await import('./clientTelemetry');
    emitClientTelemetry({
      event: 'auth_callback_failed',
      phase: 'callback_admin_validation',
      httpStatus: 204.9,
    });

    const [targetUrl, payload] = sendBeacon.mock.calls[0];
    expect(targetUrl).toBe(`${window.location.origin}/api/client-telemetry`);
    expect(JSON.parse(payload as string)).toMatchObject({
      apiOrigin: window.location.origin,
      httpStatus: 204,
    });
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
