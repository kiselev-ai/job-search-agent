"""Звенья 5–6: подвохи (правила) и оценка вакансии GigaChat по профилю кандидата."""
import json
import re

from . import gigachat
from .common import ROOT

RED_FLAG_PATTERNS = [
    (r"в валюте", "обещают доход в валюте"),
    (r"без вложений", "«доход без вложений»"),
    (r"(платн\w+|оплат\w+)\s+(за\s+)?обучени", "платное обучение"),
    (r"обучени\w*\s+(платн|за\s+свой\s+сч)", "платное обучение"),
    (r"агентск\w+ договор", "агентский договор (часто — оплата только с продаж)"),
    (r"процент от (продаж|сделк)", "оплата процентом от продаж"),
]

SCORE_RULES = """Как ставить оценку (score, целое 1–10) — насколько вакансия подходит ИМЕННО этому кандидату:
9–10 — точное попадание: основная работа — автоматизация с ИИ, ИИ-агенты/ассистенты, чат-боты, промпты, no-code, или ИИ в энергетике; кандидат реально проходит по требованиям (без опыта или засчитывают свои проекты); формат подходит.
7–8 — то же направление, но с оговоркой: просят 1–3 года опыта, а его ИИ-проекты могут засчитать.
5–6 — ИИ-автоматизация лишь часть работы, остальное — общие поручения (ассистент, администратор); или аналитик/стажёр-аналитик без упора на ИИ.
3–4 — творческое и маркетинговое направление с нейросетями (AI-контент, SEO, реклама, SMM); техническая документация на стыке с энергетикой.
1–2 — не подходит: продажи, техподдержка, классический техписатель, экономист, HR, маркетинг без ИИ, нужен серьёзный опыт программиста или 1С, офис вне регионов кандидата, сомнительные условия.
Отрасль работодателя не важна: «техписатель в энергокомпании» — всё равно техписатель. Само слово «ИИ» или «нейросети» в описании не повышает оценку — смотри, чем человек будет заниматься большую часть времени.
Снижай оценку при оплате только процентом и платном «обучении»."""

FORMAT = """Ответь ТОЛЬКО JSON-объектом, без пояснений и без ```:
{"score": <1-10>, "why": "<одно предложение по-русски: почему такая оценка, конкретно про эту вакансию>", "direction": "<tech|energy|creative|other>", "red_flags": ["<короткие подвохи, если есть, иначе пустой список>"], "salary_ok": <true|false — подходит ли оплата под ожидания кандидата из профиля; если не указана — true>}"""


def red_flags(v):
    """Звено 5. Подвохи по правилам: флаги, а не отсев."""
    text = f"{v['title']}\n{v['description']}".lower()
    flags = [label for pat, label in RED_FLAG_PATTERNS if re.search(pat, text)]
    lo, hi = v.get("salary_from"), v.get("salary_to")
    if lo and hi and hi >= 10 * lo:
        flags.append(f"вилка зарплаты ×{hi // lo}")
    if v.get("salary_mode") and v["salary_mode"] not in ("MONTH",):
        flags.append({"SHIFT": "оплата за смену", "HOUR": "оплата за час", "PER_PROJECT": "оплата за проект",
                      "FLY_IN_FLY_OUT": "вахта"}.get(v["salary_mode"], f"оплата: {v['salary_mode']}"))
    return list(dict.fromkeys(flags))


def _salary(v):
    lo, hi, cur = v.get("salary_from"), v.get("salary_to"), v.get("salary_currency") or ""
    if not lo and not hi:
        return "не указана"
    s = f"{lo or ''}–{hi or ''} {cur}".strip()
    if v.get("salary_gross"):
        s += " до вычета налогов"
    if v.get("salary_mode") and v["salary_mode"] != "MONTH":
        s += f" (режим: {v['salary_mode']})"
    return s


def vacancy_text(v, limit=3500):
    desc = v["description"]
    if len(desc) > limit:
        desc = desc[:limit] + " …[обрезано]"
    return (f"Вакансия: {v['title']}\nКомпания: {v['company']}\nЗарплата: {_salary(v)}\n"
            f"Формат: {', '.join(v['work_formats'])}; город: {v['area_name']}\n"
            f"Требуемый опыт: {v['experience']}\nКлючевые навыки: {', '.join(v.get('key_skills') or []) or '—'}\n\n"
            f"Описание:\n{desc}")


def _parse_json(text):
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("в ответе нет JSON")
    return json.loads(m.group(0))


def _parse(text):
    d = _parse_json(text)
    score = int(d["score"])
    if not 1 <= score <= 10:
        raise ValueError("score вне 1–10")
    return {
        "score": score,
        "why": str(d.get("why", "")).strip(),
        "direction": d.get("direction") if d.get("direction") in ("tech", "energy", "creative", "other") else "other",
        "red_flags": [str(x) for x in d.get("red_flags") or []][:5],
        "salary_ok": bool(d.get("salary_ok", True)),
    }


def evaluate(v, model, profile=None):
    """Звено 6. Оценка GigaChat. Один повтор при неверном формате; второй сбой — «не оценено»."""
    profile = profile or (ROOT / "profile.md").read_text(encoding="utf-8")
    messages = [
        {"role": "system", "content": f"Ты — карьерный консультант. Оцениваешь, подходит ли вакансия кандидату.\n\n{profile}\n\n{SCORE_RULES}\n\n{FORMAT}"},
        {"role": "user", "content": vacancy_text(v)},
    ]
    used = 0
    for attempt in range(2):
        text, tokens = gigachat.chat(messages, model=model)
        used += tokens
        try:
            return {**_parse(text), "tokens": used, "model": model}
        except (ValueError, KeyError, TypeError, json.JSONDecodeError):
            messages += [{"role": "assistant", "content": text},
                         {"role": "user", "content": "Ответ не по формату. Верни только JSON-объект по схеме."}]
    return {"score": None, "why": "не оценено: GigaChat дважды ответил не по формату", "direction": "other",
            "red_flags": [], "salary_ok": True, "tokens": used, "model": model}
