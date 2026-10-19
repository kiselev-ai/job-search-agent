"""Общие функции: пути, настройки, загрузка страниц hh, сохранение выходов звеньев."""
import html
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"

_last_request = 0.0


def load_config():
    return json.loads((ROOT / "config.json").read_text(encoding="utf-8"))


def run_dir(day=None):
    d = DATA / "runs" / (day or date.today().isoformat())
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_step(name, payload, day=None):
    """Выход звена — в data/runs/<дата>/<name>.json (для проверки и разбора ошибок)."""
    path = run_dir(day) / f"{name}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def load_step(name, day=None):
    return json.loads((run_dir(day) / f"{name}.json").read_text(encoding="utf-8"))


def fetch(url, pause):
    """Загрузка страницы hh с паузой между запросами, чтобы не нагружать сайт."""
    global _last_request
    wait = pause - (time.time() - _last_request)
    if wait > 0:
        time.sleep(wait)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "ru-RU,ru;q=0.9"})
    for attempt in range(3):  # сбои сети (пропал интернет, таймаут) — повтор через 5 и 15 с
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read().decode("utf-8", "replace")
        except (urllib.error.URLError, TimeoutError) as e:
            if isinstance(e, urllib.error.HTTPError) or attempt == 2:
                raise
            time.sleep(5 if attempt == 0 else 15)
        finally:
            _last_request = time.time()


def page_state(html_text):
    """hh кладёт данные страницы в <template id="HH-Lux-InitialState"> в виде JSON."""
    m = re.search(r'<template[^>]*id="HH-Lux-InitialState"[^>]*>(.*?)</template>', html_text, re.S)
    if not m:
        raise ValueError("на странице нет блока данных HH-Lux-InitialState (капча или изменилась вёрстка)")
    return json.loads(html.unescape(m.group(1)))


def search_url(text, area, experience=None, remote=False, page=0, title_only=False):
    params = [("text", text), ("area", area), ("order_by", "publication_time"), ("page", page)]
    if title_only:
        params.append(("search_field", "name"))  # искать слово только в названии вакансии
    if experience:
        params.append(("experience", experience))
    if remote:
        params.append(("work_format", "REMOTE"))
    return "https://hh.ru/search/vacancy?" + urllib.parse.urlencode(params)


def strip_tags(s):
    s = re.sub(r"<br\s*/?>|</p>|</li>", "\n", s or "")
    s = re.sub(r"<li[^>]*>", "• ", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s)
    return re.sub(r"\n\s*\n+", "\n", s).strip()
