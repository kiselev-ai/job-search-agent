"""Звено 9: сопроводительное письмо для вакансии, отмеченной «Интересно».

Абзацы о проектах — готовые выверенные тексты из letter_blocks.json (выдумать проект невозможно).
GigaChat только выписывает из вакансии главную задачу (вступление собирается по шаблону), выбирает
проекты и отвечает на вопросы работодателя, если они есть. Ответы проверяются на выдумки отдельным запросом."""
import json
import re

from . import gigachat
from .assess import _parse_json, vacancy_text
from .common import DATA, ROOT

RULES = """Помоги составить сопроводительное письмо к этой вакансии. Письмо собирается из готовых частей, от тебя нужны только данные для них.

Проекты кандидата (id — суть):
{projects}

Ответь ТОЛЬКО JSON без ```:
{{"task": "...", "tools": ["...", ...], "projects": ["id", ...], "answers": "...", "energy": true/false, "people": true/false}}

- task — главная (или первая названная) задача работы из текста вакансии, ближе всего похожая на проекты кандидата: именная группа в именительном падеже, 5–15 слов, со строчной буквы, без точки — она встанет во фразу «Главное в ней — <task>.». Пример: «ИИ-агент, который собирает актуальные темы из источников и готовит подборки для команды». Это не название должности, а то, что нужно сделать (обязанность, лучше с её целью). Пиши суть задачи, НЕ называя конкретных программ, сервисов и языков (не «в n8n и LangFlow», а «автоматизации бизнес-процессов с помощью LLM»). Сохраняй написание слов как в вакансии (AI, ИИ). Только содержание вакансии, ничего о кандидате;
- tools — конкретные программы, сервисы, платформы и языки, которые вакансия называет для этой задачи или в обязательных требованиях (n8n, LangFlow, Go, 1С, Bitrix24…), до 5 штук, написание как в вакансии; если не названы — [];
- projects — 1–2 id проектов, ближайших к задачам вакансии, самый близкий первым (проект vl добавят сами, его можно не указывать);
- answers — если в вакансии просят что-то указать или ответить в отклике (кроме ссылок на GitHub/портфолио — их добавят сами), кратко ответь только фактами из профиля; иначе пустая строка;
- energy — true, только если вакансия прямо или косвенно связана с электроэнергетикой (энергокомпания, электросети, ЖКХ, промышленное оборудование);
- people — true, если в работе нужно внедрять решения у сотрудников, общаться с ними, обучать.
Не придумывай ничего, чего нет в профиле."""

CHECK = """Ты проверяешь фрагмент сопроводительного письма на выдумки. Ниже профиль кандидата — единственный источник фактов.
Разбери фрагмент на утверждения о кандидате (что он делал, умеет, знает, сколько, где). Для каждого найди подтверждение в профиле. Утверждения о вакансии и работодателе не проверяй; пересказ своими словами — не ошибка.
Ответь ТОЛЬКО JSON без ```: {"issues": ["<утверждение> — <чего нет в профиле>", ...]}; если всё подтверждается — {"issues": []}.

ПРОФИЛЬ:
"""


def _restore_case(phrase, source):
    """GigaChat пишет «ai-агенты», «python»; возвращаем написание из вакансии (AI, Python, API).
    Берём только формы с заглавной не в начале слова или латиницу с заглавной — иначе «Разработка» в начале
    предложения испортила бы «разработку» внутри фразы."""
    forms = {}
    for w in re.findall(r"\w+", source):
        if any(c.isupper() for c in w[1:]) or (w[:1].isupper() and re.match(r"[A-Za-z]", w)):
            forms.setdefault(w.lower(), w)
    return re.sub(r"\w+", lambda m: forms.get(m.group(0).lower(), m.group(0)) if m.group(0).islower() else m.group(0), phrase)


def _new_tools(tools, blocks):
    """Инструменты вакансии, которых нет среди знакомых кандидату (known_tools в letter_blocks.json)."""
    known = {k.lower() for k in blocks.get("known_tools", [])}
    out = []
    for t in tools or []:
        t = str(t).strip()
        if t and t.lower() not in known and t.lower() not in {o.lower() for o in out}:
            out.append(t)
    return out[:4]


def _join(items):
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " и " + items[-1]


def _blocks():
    return json.loads((ROOT / "letter_blocks.json").read_text(encoding="utf-8"))


def _check(fragment, profile, model):
    messages = [{"role": "system", "content": CHECK + profile},
                {"role": "user", "content": f"ФРАГМЕНТ:\n{fragment}"}]
    text, tokens = gigachat.chat(messages, model=model, temperature=0.0, max_tokens=600)
    try:
        issues = [str(x) for x in _parse_json(text).get("issues") or []]
    except (ValueError, json.JSONDecodeError):
        issues = ["проверка фактов не сработала — сверьте вступление сами"]
    return issues, tokens


def _plan(messages, model, blocks):
    """Ответ GigaChat → части письма; при неверном формате один повтор."""
    used = 0
    for attempt in range(2):
        text, tokens = gigachat.chat(messages, model=model, temperature=0.4, max_tokens=800)
        used += tokens
        try:
            d = _parse_json(text)
            projects = [p for p in d.get("projects") or [] if p in blocks["projects"]][:2]
            if (d.get("task") or "").strip() and projects:
                return d, projects, text, used
        except (ValueError, json.JSONDecodeError):
            pass
        messages = messages + [{"role": "assistant", "content": text},
                               {"role": "user", "content": "Ответ не по формату. Верни только JSON по схеме."}]
    raise ValueError("GigaChat дважды ответил не по формату")


def write(v, model, cfg, profile=None):
    """Возвращает (письмо, замечания проверки фактов в ответах на вопросы, токены)."""
    profile = profile or (ROOT / "profile.md").read_text(encoding="utf-8")
    blocks = _blocks()
    projects_list = "\n".join(f"- {pid} — {p['about']}" for pid, p in blocks["projects"].items())
    messages = [
        {"role": "system", "content": f"Ты помогаешь кандидату откликаться на вакансии.\n\n{profile}\n\n"
                                      + RULES.format(projects=projects_list)},
        {"role": "user", "content": vacancy_text(v, limit=6000)},  # указания «как откликнуться» часто в конце
    ]
    used = 0
    for attempt in range(2):
        d, projects, raw, tokens = _plan(messages, model, blocks)
        used += tokens
        named = [t for t in d.get("tools") or [] if str(t).strip() and str(t).lower() in d["task"].lower()]
        if named and attempt == 0:  # программы должны быть в tools, а не во вступлении — один повтор
            messages = messages + [{"role": "assistant", "content": raw},
                                   {"role": "user", "content": f"В task названы программы ({', '.join(named)}). "
                                    "Перепиши task по сути задачи, без названий программ; остальное оставь. Верни JSON."}]
            continue
        answers = (d.get("answers") or "").strip()
        if not answers:
            issues = []
            break
        issues, tokens = _check(answers, profile, model)
        used += tokens
        if not issues:
            break
        messages = messages + [{"role": "assistant", "content": raw},
                               {"role": "user", "content": "В ответах есть утверждения, которых нет в профиле:\n- "
                                + "\n- ".join(issues) + "\nИсправь, верни JSON по той же схеме."}]

    lead = blocks.get("lead_project")  # главный проект — всегда первым, остальные — по выбору GigaChat
    if lead in blocks["projects"]:
        projects = [lead] + [p for p in projects if p != lead]
    projects = projects[:blocks.get("max_projects", 3)]
    about = blocks["method"]
    if d.get("energy"):
        about += " " + blocks["energy"]
    elif d.get("people"):
        about += " " + blocks["people"]
    task = _restore_case(d["task"].strip().rstrip("."), f"{v['title']}\n{v['description']}")
    if task[1:2].islower():  # «Создание…» → «создание…», но «AI-агент» не трогаем
        task = task[:1].lower() + task[1:]
    opening = blocks["intro"].format(title=v["title"].strip(), task=task)
    new = _new_tools(d.get("tools"), blocks)
    if new:  # честно назвать инструменты вакансии, с которыми кандидат не работал
        opening += " " + blocks["new_tools"].format(tools=_join(new))
    opening += " " + blocks["intro_end"]
    numbered = "\n\n".join(f"{i}. {blocks['projects'][p]['text']}" for i, p in enumerate(projects, 1))
    parts = ["Здравствуйте!", opening, numbered, about]
    if answers:
        parts.append(answers)
    if cfg.get("portfolio_url"):
        parts.append(blocks["closing"].format(portfolio=cfg["portfolio_url"]))
    parts.append(cfg.get("letter_signature", ""))
    return "\n\n".join(p for p in parts if p), issues, used


def find_vacancy(vid):
    """Ищет вакансию в выходах оценки за все дни, начиная с последнего."""
    for d in sorted((DATA / "runs").iterdir(), reverse=True):
        p = d / "06_evaluate.json"
        if p.exists():
            for v in json.loads(p.read_text(encoding="utf-8"))["vacancies"]:
                if v["id"] == vid:
                    return v
    return None
