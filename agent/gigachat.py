"""Клиент GigaChat: токен доступа (живёт 30 мин, обновляется сам) и запрос к чату.
Ключ берётся из .env и никуда не выводится."""
import json
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

from .common import ROOT

OAUTH_URL = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
API_URL = "https://gigachat.devices.sberbank.ru/api/v1"

_ctx = ssl.create_default_context(cafile=str(ROOT / "russian_trusted_root_ca.pem"))
_token = {"value": None, "expires": 0}


def _env():
    env = {}
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


def _request(url, data=None, headers=None, timeout=60):
    req = urllib.request.Request(url, data=data, headers=headers or {}, method="POST" if data is not None else "GET")
    with urllib.request.urlopen(req, context=_ctx, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def token():
    if _token["value"] and time.time() < _token["expires"] - 60:
        return _token["value"]
    env = _env()
    res = _request(
        OAUTH_URL,
        urllib.parse.urlencode({"scope": env.get("GIGACHAT_SCOPE", "GIGACHAT_API_PERS")}).encode(),
        {
            "Authorization": f"Basic {env['GIGACHAT_AUTH_KEY']}",
            "RqUID": str(uuid.uuid4()),
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
    )
    _token["value"] = res["access_token"]
    _token["expires"] = res.get("expires_at", 0) / 1000 or time.time() + 1700
    return _token["value"]


def _auth():
    return {"Authorization": f"Bearer {token()}", "Accept": "application/json"}


def get(path):
    return _request(f"{API_URL}/{path}", headers=_auth())


def chat(messages, model="GigaChat", temperature=0.1, max_tokens=800):
    """Возвращает (текст ответа, использовано токенов). Повторяет запрос при 429/5xx."""
    body = json.dumps({"model": model, "messages": messages, "temperature": temperature,
                       "max_tokens": max_tokens}).encode("utf-8")
    for attempt in range(3):
        try:
            res = _request(f"{API_URL}/chat/completions", body, {**_auth(), "Content-Type": "application/json"}, timeout=120)
            return res["choices"][0]["message"]["content"], (res.get("usage") or {}).get("total_tokens", 0)
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and attempt < 2:
                time.sleep(10 * (attempt + 1))
                continue
            raise
        except (urllib.error.URLError, TimeoutError):
            if attempt < 2:
                time.sleep(10)
                continue
            raise
