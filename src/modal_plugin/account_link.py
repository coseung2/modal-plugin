from __future__ import annotations

import html
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import RLock

from .models import SAFE_NAME_PATTERN


@dataclass(frozen=True)
class LinkSession:
    token: str
    account_id: str
    expires_at: datetime


class AccountLinkSessions:
    def __init__(self, ttl_seconds: int = 600) -> None:
        self.ttl_seconds = ttl_seconds
        self._items: dict[str, LinkSession] = {}
        self._lock = RLock()

    def create(self, account_id: str) -> LinkSession:
        if re.fullmatch(SAFE_NAME_PATTERN, account_id) is None:
            raise ValueError(
                "account_id must contain only letters, numbers, dots, underscores, or dashes"
            )
        now = datetime.now(timezone.utc)
        session = LinkSession(
            token=secrets.token_urlsafe(32),
            account_id=account_id,
            expires_at=now + timedelta(seconds=self.ttl_seconds),
        )
        with self._lock:
            self._prune(now)
            self._items[session.token] = session
        return session

    def get(self, token: str) -> LinkSession | None:
        now = datetime.now(timezone.utc)
        with self._lock:
            self._prune(now)
            return self._items.get(token)

    def consume(self, token: str) -> LinkSession | None:
        now = datetime.now(timezone.utc)
        with self._lock:
            self._prune(now)
            return self._items.pop(token, None)

    def _prune(self, now: datetime) -> None:
        expired = [token for token, item in self._items.items() if item.expires_at <= now]
        for token in expired:
            self._items.pop(token, None)


def render_link_form(session: LinkSession) -> str:
    account_id = html.escape(session.account_id)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Connect Modal</title>
<style>
body {{ font: 16px system-ui; max-width: 680px; margin: 40px auto; padding: 0 20px; }}
label {{ display: block; margin: 14px 0 4px; }}
input, select, button {{ font: inherit; padding: 9px; width: 100%; box-sizing: border-box; }}
button {{ margin-top: 18px; }}
code {{ background: #eee; padding: 2px 5px; }}
</style>
</head>
<body>
<h1>Connect Modal account</h1>
<p>Account ID: <code>{account_id}</code></p>
<p>Credentials are posted directly to this server and are not sent through ChatGPT or Codex.</p>
<label>Authentication type</label>
<select id="kind">
  <option value="token">Modal API token</option>
  <option value="oauth">Modal OAuth refresh token</option>
</select>
<div id="tokenFields">
  <label>Token ID</label><input id="tokenId" autocomplete="off">
  <label>Token secret</label><input id="tokenSecret" type="password" autocomplete="off">
</div>
<div id="oauthFields" hidden>
  <label>OAuth refresh token</label>
  <input id="refreshToken" type="password" autocomplete="off">
</div>
<button id="connect">Connect</button>
<pre id="status"></pre>
<script>
const kind = document.getElementById('kind');
const tokenFields = document.getElementById('tokenFields');
const oauthFields = document.getElementById('oauthFields');
kind.onchange = () => {{
  tokenFields.hidden = kind.value !== 'token';
  oauthFields.hidden = kind.value !== 'oauth';
}};
document.getElementById('connect').onclick = async () => {{
  const body = kind.value === 'token'
    ? {{
        auth_type: 'token',
        token_id: document.getElementById('tokenId').value,
        token_secret: document.getElementById('tokenSecret').value
      }}
    : {{ auth_type: 'oauth', refresh_token: document.getElementById('refreshToken').value }};
  const response = await fetch(location.href, {{
    method: 'POST',
    headers: {{ 'Content-Type': 'application/json' }},
    body: JSON.stringify(body)
  }});
  const result = await response.json();
  document.getElementById('status').textContent = result.message || JSON.stringify(result, null, 2);
  if (response.ok) document.getElementById('connect').disabled = true;
}};
</script>
</body>
</html>"""
