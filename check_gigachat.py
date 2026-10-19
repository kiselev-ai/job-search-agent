"""Проверка подключения к GigaChat: берёт ключ из .env, получает токен и задаёт тестовый вопрос.
Ключ и токен на экран не выводятся."""
import json
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

OAUTH_URL = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
CHAT_URL = "https://gigachat.devices.sberbank.ru/api/v1/chat/completions"
ROOT = Path(__file__).parent


def load_env(path):
    env = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def ssl_context():
    # Серверы Сбера подписаны российским корневым сертификатом (НУЦ Минцифры).
    # Если он лежит в папке проекта — используем его, иначе системные сертификаты.
    cert = ROOT / "russian_trusted_root_ca.pem"
    return ssl.create_default_context(cafile=str(cert)) if cert.exists() else ssl.create_default_context()


def post(url, data, headers, ctx):
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main():
    env = load_env(ROOT / ".env")
    key = env.get("GIGACHAT_AUTH_KEY", "")
    scope = env.get("GIGACHAT_SCOPE", "GIGACHAT_API_PERS")
    if not key:
        sys.exit("Ключ не найден: в .env пустая строка GIGACHAT_AUTH_KEY=")
    ctx = ssl_context()

    try:
        token = post(
            OAUTH_URL,
            urllib.parse.urlencode({"scope": scope}).encode(),
            {
                "Authorization": f"Basic {key}",
                "RqUID": str(uuid.uuid4()),
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
            ctx,
        )["access_token"]
        print("1. Ключ принят, токен доступа получен.")

        answer = post(
            CHAT_URL,
            json.dumps({
                "model": "GigaChat",
                "messages": [{"role": "user", "content": "Ответь одним предложением: что такое воздушная линия электропередачи?"}],
            }).encode("utf-8"),
            {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            ctx,
        )
        print("2. GigaChat ответил:", answer["choices"][0]["message"]["content"])
        usage = answer.get("usage", {})
        if usage:
            print(f"   Потрачено токенов: {usage.get('total_tokens')}")
    except ssl.SSLError as e:
        sys.exit(f"Ошибка сертификата (нужен российский корневой сертификат): {e}")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:300]
        sys.exit(f"Сервер ответил ошибкой {e.code}: {body}")
    except urllib.error.URLError as e:
        sys.exit(f"Не удалось подключиться: {e.reason}")


if __name__ == "__main__":
    main()
