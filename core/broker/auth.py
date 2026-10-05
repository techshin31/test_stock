"""Bounded KIS authentication with private, account/venue-scoped JSON tokens."""
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
import time
from contextlib import contextmanager

import requests
from core.utils.process_lock import ProcessInstanceLock


@contextmanager
def token_lock(path):
    lock = ProcessInstanceLock(path.with_suffix(".lock"), "AUTH", label="KIS token refresh").acquire()
    try:
        yield
    finally:
        lock.release()


def authenticated_client(base, **settings):
    class Client(base):
        def _token_path(self):
            directory = Path(os.getenv("KIS_TOKEN_CACHE_DIR") or
                             Path(__file__).resolve().parents[2] / "logs/credentials")
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            if os.name != "nt":
                directory.chmod(0o700)
            identity = hashlib.sha256(json.dumps([self.base_url, self.api_key, self.api_secret,
                                                  self.acc_no]).encode()).hexdigest()
            return directory / (identity + ".json")

        def _cached(self):
            try:
                data = json.loads(self._token_path().read_text())
                expiry = float(data["expires_at"])
                if (isinstance(data["access_token"], str) and data["access_token"]
                        and math.isfinite(expiry) and expiry > time.time() + 60):
                    return data
            except (OSError, ValueError, KeyError, TypeError):
                pass
            return None

        def check_access_token(self):
            return self._cached() is not None

        def load_access_token(self):
            data = self._cached()
            if data is None:
                return self.issue_access_token()
            self.access_token = "Bearer " + data["access_token"]

        def issue_access_token(self):
            path = self._token_path()
            with token_lock(path):
                data = self._cached()
                if data is None:
                    try:
                        response = requests.post(self.base_url + "/oauth2/tokenP", json={
                            "grant_type": "client_credentials", "appkey": self.api_key,
                            "appsecret": self.api_secret}, timeout=10)
                        response.raise_for_status()
                        payload = response.json()
                        token, lifetime = payload["access_token"], float(payload["expires_in"])
                        if not isinstance(token, str) or not token or not math.isfinite(lifetime) or lifetime <= 60:
                            raise ValueError("invalid token response")
                        data = {"access_token": token, "expires_at": time.time() + lifetime}
                    except Exception as exc:
                        raise RuntimeError(f"KIS_AUTHENTICATION_FAILED:{type(exc).__name__}") from None
                    temporary = None
                    try:
                        with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as handle:
                            temporary = Path(handle.name)
                            os.chmod(temporary, 0o600)
                            json.dump(data, handle)
                        os.replace(temporary, path)
                    finally:
                        if temporary:
                            temporary.unlink(missing_ok=True)
                self.access_token = "Bearer " + data["access_token"]

    return Client(**settings)
