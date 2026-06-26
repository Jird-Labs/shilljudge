# thread-helper backend

FastAPI service that signs in with **X OAuth 2.0 (PKCE)** using the official [`xdk`](https://pypi.org/project/xdk/) client, then reads posts with user-context auth (needed for metrics fields such as `organic_metrics` / `non_public_metrics` on the [Posts lookup by IDs](https://developer.x.com/en/docs/twitter-api/tweets/lookup/api-reference/get-tweets) API).

## Setup

1. Create `backend/.env` from `.env.example` and set **`X_CLIENT_ID`** and **`X_CLIENT_SECRET`** from the X Developer Portal under **your app → User authentication settings (OAuth 2.0)**. These are the OAuth 2.0 client credentials, not OAuth 1.0a “Access token & secret”.
2. In the portal, add a **Callback / Redirect URI** that matches **`X_REDIRECT_URI` exactly** (scheme, host, port, path). For local development with **`npm run dev`**, prefer `http://localhost:5173/oauth/callback` and **`FRONTEND_URL=http://localhost:5173`** so X redirects to the Vite dev server (which proxies `/oauth` to this API); then you are not left on port **8080** after authorize, and the PKCE session cookie matches the callback host. If you open the app at **`127.0.0.1:5173`**, use that host in both URLs instead of `localhost` (browsers treat them as different sites). You can still use **`http://127.0.0.1:8080/oauth/callback`** if you always start OAuth by visiting **`/oauth/login` on 8080`** (not only through the SPA).
3. Install and run (from `backend/`):

```bash
uv sync
uv run fastapi dev app.py --port 8080
```

4. With the Vite + proxy setup, open the app at **`http://localhost:5173`** and use **Authenticate with X** (or open `http://localhost:5173/oauth/login`). With OAuth only on the API, open `http://127.0.0.1:8080/oauth/login` and ensure **`X_REDIRECT_URI`** uses that same host and port. Tokens are written to `x_oauth_tokens.json` (gitignored).

## API

- `GET /oauth/login` — start OAuth2 PKCE (redirects to X).
- `GET /oauth/callback` — X redirects here after login; do not open manually without a `code`.
- `GET /post/{post_id}` — single post with default tweet fields.
- `POST /posts/by-ids` — JSON body `{"ids": ["…"]}`; batches up to 100 IDs per X API request and merges `data` / `errors`.

If you see `401` with `x_oauth_required`, complete `/oauth/login` again (session cookie + token file must be present).

## Troubleshooting OAuth

- **X shows “Something went wrong” on the authorize URL** — Often the **`client_id` is wrong**. If it looks like `1992065765504401409-xxxxx`, that is an **OAuth 1.0a user access token**, not the OAuth 2.0 Client ID. Fix `X_CLIENT_ID` in `.env` from the portal’s OAuth 2.0 section.
- **Port conflicts** — If another process already uses **8000**, run this app on **8080** (or any free port) and set **`X_REDIRECT_URI`** and the portal callback to the same port. You must visit **`/oauth/login` on that same host and port** so the session cookie is set for the callback.
- **Callback on 8080 “breaks” after using the SPA on 5173** — The PKCE verifier lives in a **session cookie** on the host where you opened **`/oauth/login`**. If the login link went to **8080** but you use the UI on **5173**, or **`X_REDIRECT_URI`** does not match where that cookie was set, the callback fails. Fix: use **`X_REDIRECT_URI=http://localhost:5173/oauth/callback`**, **`FRONTEND_URL=http://localhost:5173`**, register that URI in the X portal, keep the Vite **`/oauth` proxy**, and use the **Authenticate with X** link (same-origin **`/oauth/login`**).
- **Generic X errors** — Try another browser profile or temporarily disable strict privacy extensions; X sometimes surfaces a generic page for invalid OAuth parameters ([x.com authorize](https://x.com/i/oauth2/authorize) failures).

## Security

Never commit `.env` or `x_oauth_tokens.json`. If credentials were ever committed or pasted into chat, rotate the client secret in the X portal and revoke old tokens.
