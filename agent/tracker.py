"""Звено 10: учёт в data/tracker.csv (открывается в Excel: разделитель «;», UTF-8 с BOM).

Агент ведёт статусы «новая» → «интересно» / «не надо» → «письмо». Дальше статусы ставит
пользователь в Excel («отклик», «приглашение», «отказ» или любой свой) — агент их не трогает,
как и колонку «Заметки»."""
import csv
from datetime import date

from .common import DATA

PATH = DATA / "tracker.csv"
COLUMNS = ["Дата", "ID", "Ссылка", "Вакансия", "Компания", "Оценка", "Статус", "Обновлено", "Заметки"]
AGENT_RANK = {"новая": 0, "не надо": 1, "интересно": 1, "письмо": 2}  # прочие статусы — пользовательские


def load():
    """Читает таблицу; Excel мог пересохранить её в cp1251 или с запятыми — понимаем оба варианта."""
    if not PATH.exists():
        return []
    raw = PATH.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp1251")
    delimiter = ";" if text.split("\n", 1)[0].count(";") >= text.split("\n", 1)[0].count(",") else ","
    return [dict(r) for r in csv.DictReader(text.splitlines(), delimiter=delimiter)]


def save(rows):
    """Пишет через временный файл. Если таблица открыта и запись не удалась — бросает PermissionError."""
    tmp = PATH.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, delimiter=";", extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    tmp.replace(PATH)


def _set_status(row, status, today):
    cur = row.get("Статус", "")
    cur_rank = AGENT_RANK.get(cur, 9)  # 9 — статус пользователя, агент его не перебивает
    new_rank = AGENT_RANK[status]
    if new_rank > cur_rank or (new_rank == cur_rank == 1 and status != cur):  # передумал: «не надо» ↔ «интересно»
        row["Статус"], row["Обновлено"] = status, today
        return True
    return False


def update(sent_vacancies, decisions, find_vacancy):
    """sent_vacancies — вакансии, ушедшие в подборку; decisions — data/decisions.json."""
    today = date.today().isoformat()
    rows = load()
    by_id = {r["ID"]: r for r in rows}
    added = changed = 0

    def row_for(v):
        nonlocal added
        if v["id"] not in by_id:
            score = (v.get("eval") or {}).get("score")
            by_id[v["id"]] = {"Дата": today, "ID": v["id"], "Ссылка": v["url"], "Вакансия": v["title"],
                              "Компания": v["company"], "Оценка": score if score is not None else "",
                              "Статус": "новая", "Обновлено": today, "Заметки": ""}
            rows.append(by_id[v["id"]])
            added += 1
        return by_id[v["id"]]

    for v in sent_vacancies:
        row_for(v)
    for vid, d in decisions.items():
        row = by_id.get(vid)
        if row is None:
            v = find_vacancy(vid)
            if not v:
                continue
            row = row_for(v)
        status = "письмо" if d.get("letter") else ("интересно" if d["decision"] == "like" else "не надо")
        changed += _set_status(row, status, today)
    save(rows)
    return {"added": added, "changed": changed, "total": len(rows)}
