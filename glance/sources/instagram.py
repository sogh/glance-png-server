"""Instagram follower and post counts, via the official Graph API.

Scraping the public profile does not work: unauthenticated requests get a
login wall or a 401 telling you to wait, intermittently rather than
consistently. An app built that way does not fail loudly -- it falls back to a
stale or zero value and presents it as fact, which is how a panel ends up
confidently wrong.

So this uses the Graph API, and when it cannot get a fresh number it says so
instead of guessing. A count that is openly four hours old is more useful than
one that might be wrong and looks current.

Two modes:
  own       /me?fields=followers_count,media_count  -- the account the token
            belongs to. Exact, and the simplest thing that works.
  discovery business_discovery against another public Business/Creator
            account. Needs your own IG Business account as the caller.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

GRAPH = "https://graph.facebook.com/v21.0"


@dataclass
class Profile:
    username: str
    followers: int
    posts: int
    follows: int | None = None
    name: str = ""
    fetched_at: float = 0.0

    def age_seconds(self, now: float | None = None) -> float:
        return (now or time.time()) - self.fetched_at

    def age_text(self, now: float | None = None) -> str:
        """Human-sized staleness, for saying so on the panel."""
        seconds = self.age_seconds(now)
        if seconds < 90 * 60:
            return f"{int(seconds // 60)}M"
        if seconds < 48 * 3600:
            return f"{int(seconds // 3600)}H"
        return f"{int(seconds // 86400)}D"


class InstagramSource:
    def __init__(self, token: str, account: str = "", user_id: str = "",
                 cache_dir: Path | None = None, refresh: int = 3600,
                 timeout: float = 10.0) -> None:
        self.token = token or ""
        # Blank account (or "me") means the token's own account.
        self.account = (account or "").lstrip("@")
        self.user_id = user_id or "me"
        self.refresh = refresh
        self.timeout = timeout
        self.cache_dir = Path(cache_dir or ".")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_file = self.cache_dir / f"instagram-{self.account or 'me'}.json"
        self.last_error: str | None = None
        self._lock = threading.Lock()

    @property
    def configured(self) -> bool:
        return bool(self.token)

    # --- fetching ----------------------------------------------------------

    def _request(self) -> dict:
        if self.account and self.account.lower() != "me":
            # Asking about somebody else's public Business/Creator account.
            fields = (f"business_discovery.username({self.account})"
                      "{username,name,followers_count,media_count}")
        else:
            fields = "username,name,followers_count,media_count,follows_count"

        resp = httpx.get(f"{GRAPH}/{self.user_id}", timeout=self.timeout,
                         params={"fields": fields, "access_token": self.token})
        data = resp.json()
        if "error" in data:
            err = data["error"]
            raise RuntimeError(f"{err.get('type', 'error')}: {err.get('message', '')}")
        resp.raise_for_status()
        return data

    @staticmethod
    def _parse(data: dict, account: str) -> Profile:
        node = data.get("business_discovery", data)
        return Profile(
            username=node.get("username") or account,
            followers=int(node.get("followers_count", 0)),
            posts=int(node.get("media_count", 0)),
            follows=(int(node["follows_count"]) if "follows_count" in node else None),
            name=node.get("name") or "",
            fetched_at=time.time(),
        )

    def _cached(self) -> Profile | None:
        if not self.cache_file.exists():
            return None
        try:
            raw = json.loads(self.cache_file.read_text())
            return Profile(**raw)
        except (json.JSONDecodeError, OSError, TypeError):
            return None

    def profile(self) -> Profile | None:
        """Latest counts, or the last known ones with their age attached."""
        if not self.configured:
            self.last_error = "no access token configured"
            return None

        with self._lock:
            cached = self._cached()
            if cached and cached.age_seconds() < self.refresh:
                return cached
            try:
                profile = self._parse(self._request(), self.account)
                self.cache_file.write_text(json.dumps(profile.__dict__))
                self.last_error = None
                return profile
            except Exception as exc:  # noqa: BLE001
                self.last_error = f"{type(exc).__name__}: {exc}"
                # Stale and labelled beats absent, and beats wrong.
                return cached
