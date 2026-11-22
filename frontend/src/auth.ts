import type { AuthSession } from './types';

const STORAGE_KEY = 'insurance-mall-auth-v2';

export function readSession(): AuthSession | null {
  try {
    const value = window.localStorage.getItem(STORAGE_KEY);
    const session = value ? JSON.parse(value) as AuthSession : null;
    return session?.access_token ? session : null;
  } catch {
    window.localStorage.removeItem(STORAGE_KEY);
    return null;
  }
}

export function saveSession(session: AuthSession): void {
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(session));
}

export function clearSession(): void {
  window.localStorage.removeItem(STORAGE_KEY);
}

export function authHeaders(): Record<string, string> {
  const token = readSession()?.access_token;
  return token ? { Authorization: `Bearer ${token}` } : {};
}
