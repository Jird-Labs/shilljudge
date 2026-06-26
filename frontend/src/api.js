export class ApiError extends Error {
  constructor(code, message) {
    super(message);
    this.code = code;
  }
}

async function apiFetch(url, options = {}) {
  const res = await fetch(url, { credentials: 'include', ...options });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    const detail = body.detail ?? {};
    const code = typeof detail === 'object' ? (detail.error ?? String(res.status)) : String(res.status);
    const message = typeof detail === 'object' ? (detail.message ?? res.statusText) : (detail || res.statusText);
    throw new ApiError(code, message);
  }
  return res.json();
}

export async function checkAuthStatus() {
  try {
    return await apiFetch('/auth/status');
  } catch {
    return { authenticated: false };
  }
}

export async function logout() {
  return apiFetch('/auth/logout', { method: 'POST' });
}

export async function getLeaderboard({ sort = 'score', dir = 'desc', limit = 100, offset = 0 } = {}) {
  const params = new URLSearchParams({ sort, dir, limit: String(limit), offset: String(offset) });
  return apiFetch(`/leaderboard?${params}`);
}

export async function getStatus() {
  return apiFetch('/status');
}

export async function previewSubmission(url) {
  return apiFetch('/submissions/preview', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url }),
  });
}

export async function confirmSubmission(postIds) {
  return apiFetch('/submissions/confirm', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ post_ids: postIds }),
  });
}

export async function submitPreview(url) {
  return apiFetch('/submit/preview', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url }),
  });
}

export async function submitThread(url) {
  return apiFetch('/submit', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url }),
  });
}

export async function updateWallet(walletAddress) {
  return apiFetch('/me/wallet', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ wallet_address: walletAddress }),
  });
}

export async function recheckWallet() {
  return apiFetch('/me/wallet/recheck', { method: 'POST' });
}

export async function getManageContests() {
  return apiFetch('/manage/contests');
}

export async function createContest(data) {
  return apiFetch('/manage/contests', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
}

export async function updateContest(contestId, data) {
  return apiFetch(`/manage/contests/${contestId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
}

export async function deleteContest(contestId) {
  return apiFetch(`/manage/contests/${contestId}`, { method: 'DELETE' });
}

export async function getManageUsers(q) {
  const query = q ? `?q=${encodeURIComponent(q)}` : '';
  return apiFetch(`/manage/users${query}`);
}

export async function patchUser(xId, data) {
  return apiFetch(`/manage/user/${encodeURIComponent(xId)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
}

export async function deleteUser(xId) {
  return apiFetch(`/manage/user/${encodeURIComponent(xId)}`, { method: 'DELETE' });
}

export async function getUserThreads(xId) {
  return apiFetch(`/manage/user/${encodeURIComponent(xId)}/threads`);
}

export async function deletePost(postId) {
  return apiFetch(`/manage/post/${encodeURIComponent(postId)}`, { method: 'DELETE' });
}
