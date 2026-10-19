"""Звенья 7–8: отбор подборки дня и отправка её в Telegram."""
from datetime import date

from . import links, telegram
from .telegram import esc

DIRECTION_ORDER = {"tech": 0, "energy": 1, "creative": 2, "other": 3}
FORMATS = {"REMOTE": "удалённо", "HYBRID": "гибрид", "ON_SITE": "офис", "FIELD_WORK": "разъездная"}
EXPERIENCE = {"noExperience": "без опыта", "between1And3": "опыт 1–3 года", "between3And6": "опыт 3–6 лет",
              "moreThan6": "опыт 6+ лет"}
SALARY_MODES = {"SHIFT": "за смену", "HOUR": "в час", "PER_PROJECT": "за проект", "FLY_IN_FLY_OUT": "вахта"}


def select(vacancies, cfg, log=print):
    """Звено 7. Оценка ≥ порога, лучшие сверху; перед включением проверяет, не ушла ли вакансия в архив.
    Неоценённые (GigaChat не ответил по формату) идут в конец, если остались места."""
    size, threshold = cfg.get("digest_size", 5), cfg.get("digest_min_score", 6)
    scored = [v for v in vacancies if (v["eval"].get("score") or 0) >= threshold]
    scored.sort(key=lambda v: v.get("published") or "", reverse=True)  # при равенстве — свежие выше
    scored.sort(key=lambda v: (-v["eval"]["score"], DIRECTION_ORDER.get(v["eval"].get("direction"), 3)))
    unscored = [v for v in vacancies if v["eval"].get("score") is None]
    selected, closed = [], []
    for v in scored + unscored:
        if len(selected) == size:
            break
        try:
            open_ = links.is_open(v["id"], cfg)
        except Exception as e:  # страница не открылась — не прячем вакансию из-за сбоя сети
            log(f"  не удалось проверить {v['id']}: {e}")
            open_ = True
        if open_:
            selected.append(v)
        else:
            closed.append(v["id"])
    log(f"Звено 7 — отбор: подходящих (≥{threshold}) {len(scored)}, без оценки {len(unscored)}, "
        f"в подборке {len(selected)}, ушли в архив {len(closed)}")
    return {"selected": selected, "eligible": len(scored), "unscored": len(unscored),
            "total": len(vacancies), "closed": closed}


def _salary(v):
    lo, hi = v.get("salary_from"), v.get("salary_to")
    if not lo and not hi:
        return "з/п не указана"
    fmt = lambda n: f"{n:,}".replace(",", " ")
    s = " ".join(p for p in (lo and f"от {fmt(lo)}", hi and f"до {fmt(hi)}") if p)
    cur = {"RUR": "₽", "RUB": "₽", "USD": "$", "EUR": "€"}.get(v.get("salary_currency"), v.get("salary_currency") or "")
    s += f" {cur}"
    if v.get("salary_mode") in SALARY_MODES:
        s += f" {SALARY_MODES[v['salary_mode']]}"
    s += " до вычета" if v.get("salary_gross") else " на руки"
    return s


def card_text(v):
    e = v["eval"]
    score = f"⭐ {e['score']}/10" if e.get("score") else "❔ не оценено"
    formats = ", ".join(FORMATS.get(f, f) for f in v.get("work_formats") or []) or "формат не указан"
    place = formats if formats == "удалённо" else f"{formats}, {v.get('area_name', '')}"
    flags = list(dict.fromkeys((v.get("rule_flags") or []) + (e.get("red_flags") or [])))
    lines = [f"{score} · <b>{esc(v['title'])}</b>",
             f"{esc(v['company'])} · {esc(_salary(v))}",
             f"{esc(place)} · {EXPERIENCE.get(v.get('experience'), esc(v.get('experience')))}",
             "",
             f"<i>{esc(e.get('why'))}</i>"]
    if flags:
        lines.append("⚠️ " + esc("; ".join(flags)))
    lines.append(v["url"])
    return "\n".join(lines)


def deliver(sel, sent, log=print):
    """Звено 8. Заголовок + по сообщению на вакансию с кнопками.
    sent — список id, уже отправленных сегодня (дополняется по ходу, чтобы при сбое не слать повторно)."""
    today = date.today().strftime("%d.%m")
    if not sent:
        if sel["selected"]:
            head = (f"🔎 <b>Подборка на {today}</b>: {len(sel['selected'])} лучших из {sel['eligible']} подходящих "
                    f"(новых вакансий оценено: {sel['total']}).\n"
                    "Нажмите «Интересно» — подготовлю сопроводительное письмо.")
        else:
            head = f"🔎 <b>{today}</b>: подходящих вакансий сегодня нет (новых оценено: {sel['total']})."
        telegram.send(head)
    for v in sel["selected"]:
        if v["id"] in sent:
            continue
        telegram.send(card_text(v), [[("👍 Интересно", f"like:{v['id']}"), ("👎 Не надо", f"skip:{v['id']}")]])
        sent.append(v["id"])
    log(f"Звено 8 — доставка: отправлено вакансий {len(sent)}")
    return {"sent": sent}
