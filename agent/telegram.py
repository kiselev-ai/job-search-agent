"""Клиент Telegram Bot API: отправка подборки и сбор нажатий кнопок.
Токен и номер чата берутся из .env и никуда не выводятся."""
import html
import json
import urllib.error
import urllib.request

from .common import DATA
from .gigachat import _env

API = "https://api.telegram.org/bot{token}/{method}"


def call(method, **params):
    env = _env()
    req = urllib.request.Request(API.format(token=env["TELEGRAM_BOT_TOKEN"], method=method),
                                 data=json.dumps(params).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            res = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:  # Telegram объясняет ошибку в теле ответа; токен в текст не попадает
        res = json.loads(e.read().decode("utf-8") or "{}")
    if not res.get("ok"):
        raise RuntimeError(f"Telegram {method}: {res.get('description', 'ошибка')}")
    return res["result"]


def send(text, buttons=None):
    """buttons — список рядов: [[("текст", "callback_data"), ...], ...]."""
    params = {"chat_id": _env()["TELEGRAM_CHAT_ID"], "text": text, "parse_mode": "HTML",
              "disable_web_page_preview": True}
    if buttons:
        params["reply_markup"] = {"inline_keyboard": [[{"text": t, "callback_data": d} for t, d in row]
                                                      for row in buttons]}
    return call("sendMessage", **params)


def esc(s):
    return html.escape(str(s or ""), quote=False)


def _offset_path():
    return DATA / "telegram_offset.json"


def collect_presses():
    """Забирает нажатия кнопок, накопленные с прошлого раза (Telegram хранит их до суток).
    Отвечает на каждое и убирает кнопки у сообщения, вписав выбор. Возвращает [(id, решение)]."""
    p = _offset_path()
    offset = json.loads(p.read_text())["offset"] if p.exists() else 0
    updates = call("getUpdates", offset=offset, timeout=0, allowed_updates=["callback_query"])
    chat_id = str(_env()["TELEGRAM_CHAT_ID"])
    presses = []
    for u in updates:
        offset = u["update_id"] + 1
        q = u.get("callback_query")
        if not q or str(q["message"]["chat"]["id"]) != chat_id:
            continue
        action, _, vid = (q.get("data") or "").partition(":")
        if action not in ("like", "skip") or not vid:
            continue
        presses.append((vid, action))
        label = "✅ Интересно — готовлю письмо" if action == "like" else "✖️ Не надо"
        try:
            call("answerCallbackQuery", callback_query_id=q["id"], text=label)
        except RuntimeError:
            pass  # ответ на нажатие старше нескольких минут Telegram уже не принимает — не страшно
        msg = q["message"]
        call("editMessageText", chat_id=msg["chat"]["id"], message_id=msg["message_id"],
             text=f"{msg.get('text', '')}\n\n{label}", entities=msg.get("entities", []),
             disable_web_page_preview=True)
    DATA.mkdir(exist_ok=True)
    p.write_text(json.dumps({"offset": offset}))
    return presses
