# Auth endpoint orchestration (`src/recipeserver/auth_endpoints.py`)

```mermaid
flowchart TD
    login("<img src='barnacle:log-in.svg' width='20' alt=''/><br/>GET /api/auth/login") --> decisions
    callback("<img src='barnacle:refresh-cw.svg' width='20' alt=''/><br/>GET /api/auth/callback") --> decisions
    logout("<img src='barnacle:log-out.svg' width='20' alt=''/><br/>POST /api/auth/logout") --> decisions
    decisions("<img src='barnacle:layers.svg' width='20' alt=''/><br/><u>auth_endpoints.py<br/>flow decisions + actions</u>") --> handler("<img src='barnacle:file-code.svg' width='20' alt=''/><br/><u>server.py<br/>cookies · redirects · status codes</u>")
    click handler href "server.py.md"
    class decisions goFile
    classDef goFile fill:#8fd8ef,stroke:#0277a8,color:#08303d
```

The OIDC login flow decisions, separated from the HTTP response code that
applies them. [server.py.md](server.py.md) owns the routes and writes the
cookies/redirects; this module decides _which_ cookies, redirect, or
non-leaking error the flow requires. It delegates the actual session and token
work to [authorization.py.md](authorization.py.md), [oidc.py.md](oidc.py.md),
and [session.py.md](session.py.md).

## Public interface

- `AuthAction` — a small action record: `redirect`, `cookie`, `clear_cookie`,
  `error`, `error_json`, `success`. A decision returning `None` means auth is
  disabled and the endpoint does not exist.
- `begin_login(auth, path)` — start the flow, queue the single-use flow cookie,
  or return a 503 error page.
- `finish_login(auth, path, headers)` — clear the flow cookie even on failure,
  complete the login, and queue the session cookie.
- `logout(auth, identity, headers)` — enforce CSRF and clear the session cookie.
- `queue_cookie_header(auth, cookie)` — render `Set-Cookie` with the live
  `secure_cookies` setting.

## Related pages

- [server.py.md](server.py.md) — the three endpoints and their route registration
- [authorization.py.md](authorization.py.md) — permissions and the auth gate
- [README.md](README.md) — the package hub
