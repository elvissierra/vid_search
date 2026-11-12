// Session and usage helpers for the account UI. Kept free of Vue and axios
// imports so they can be exercised on their own (see tests/test_ui_auth.py).

export const TOKEN_KEY = 'vid_search_token';

export function loadToken(storage) {
  try {
    return storage.getItem(TOKEN_KEY) || '';
  } catch {
    return '';
  }
}

export function saveToken(storage, token) {
  try {
    storage.setItem(TOKEN_KEY, token);
  } catch {
    // storage blocked: the session just lasts until the page closes
  }
}

export function clearToken(storage) {
  try {
    storage.removeItem(TOKEN_KEY);
  } catch {
    // nothing to clear
  }
}

// Header value for a token, or null when logged out (anonymous requests send none).
export function authHeader(token) {
  return token ? `Bearer ${token}` : null;
}

// Whole percent of the free tier used, clamped to 0-100.
export function usagePercent(usage) {
  if (!usage || !usage.limit_seconds) return 0;
  const pct = Math.round((usage.used_seconds / usage.limit_seconds) * 100);
  return Math.min(100, Math.max(0, pct));
}

// 3725 -> "1h 2m", 90 -> "1m 30s", 12 -> "12s".
export function formatDuration(seconds) {
  const total = Math.max(0, Math.round(seconds || 0));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  if (h) return `${h}h ${m}m`;
  if (m) return `${m}m ${s}s`;
  return `${s}s`;
}

// "12m 0s of 1h 0m used".
export function usageLabel(usage) {
  if (!usage) return '';
  return `${formatDuration(usage.used_seconds)} of ${formatDuration(usage.limit_seconds)} used`;
}

export function isOverQuota(usage) {
  return !!usage && usage.used_seconds >= usage.limit_seconds;
}
