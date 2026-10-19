"""Звенья 1–4: сбор, новизна, жёсткий фильтр, подробности.

Порядок отличается от spec v0.2: жёсткий фильтр стоит до «подробностей» — опыт, формат и регион
есть уже в выдаче поиска, поэтому страницы вакансий открываются только для прошедших отсев.
"""
import json
import re
from datetime import date, timedelta

from .common import DATA, fetch, load_config, page_state, search_url, strip_tags


def _card(v, query, source):
    comp = v.get("compensation") or {}
    area = v.get("area") or {}
    company = v.get("company") or {}
    return {
        "id": str(v["vacancyId"]),
        "url": f"https://hh.ru/vacancy/{v['vacancyId']}",
        "title": v.get("name", ""),
        "company": company.get("visibleName") or company.get("name", ""),
        "salary_from": comp.get("from"),
        "salary_to": comp.get("to"),
        "salary_currency": comp.get("currencyCode"),
        "salary_gross": comp.get("gross"),
        "salary_mode": comp.get("mode"),
        "area_id": str(area.get("@id") or area.get("id") or ""),
        "area_name": area.get("name", ""),
        "area_path": area.get("path", ""),
        "experience": v.get("workExperience"),
        "work_formats": [f for item in v.get("workFormats") or [] for f in item.get("workFormatsElement", [])],
        "employment": v.get("employmentForm"),
        "internship": v.get("internship"),
        "published": (v.get("publicationTime") or {}).get("$"),
        "queries": [query],
        "source": source,
    }


def collect(cfg=None, log=print):
    """Звено 1. Сбор: страницы поиска hh по запросам из config.json → список карточек без дублей."""
    cfg = cfg or load_config()
    pause = cfg["request_pause_sec"]
    jobs = []
    for q in cfg["remote_queries"]:
        for exp in cfg["experience"]:
            jobs.append((q, "113", exp, True, f"remote:{exp}"))
    for area_id, area_name in cfg["regions"].items():
        for q in cfg["regional_queries"]:
            for exp in cfg["experience"]:
                jobs.append((q, area_id, exp, False, f"{area_name}:{exp}"))

    title_only = set(cfg.get("title_only_queries", []))
    cards, errors = {}, []
    for i, (q, area, exp, remote, source) in enumerate(jobs, 1):
        for page in range(cfg["pages_per_query"]):
            url = search_url(q, area, exp, remote, page, title_only=q in title_only)
            try:
                res = page_state(fetch(url, pause))["vacancySearchResult"]
            except Exception as e:  # одна сбойная страница не должна ронять весь сбор
                errors.append({"url": url, "error": str(e)})
                break
            for v in res.get("vacancies", []):
                c = _card(v, q, source)
                if c["id"] in cards:
                    if q not in cards[c["id"]]["queries"]:
                        cards[c["id"]]["queries"].append(q)
                else:
                    cards[c["id"]] = c
            nxt = (res.get("paging") or {}).get("next") or {}
            if not nxt or nxt.get("disabled"):
                break
        log(f"  [{i}/{len(jobs)}] {source} «{q}»: всего уникальных {len(cards)}")
    return {"cards": list(cards.values()), "errors": errors, "requests": len(jobs)}


def novelty(cards):
    """Звено 2. Новизна: убирает вакансии, уже виденные в прошлые дни (data/seen.json)."""
    seen = load_seen()
    new = [c for c in cards if c["id"] not in seen]
    return {"new": new, "already_seen": len(cards) - len(new)}


def load_seen():
    p = DATA / "seen.json"
    return set(json.loads(p.read_text(encoding="utf-8"))) if p.exists() else set()


def mark_seen(ids):
    """Запоминает вакансии как просмотренные. Вызывается в конце успешного прогона."""
    seen = load_seen() | set(ids)
    DATA.mkdir(exist_ok=True)
    (DATA / "seen.json").write_text(json.dumps(sorted(seen)), encoding="utf-8")


def hard_filter(cards, cfg=None):
    """Звено 3. Жёсткий фильтр: стоп-слова в названии, опыт, регион, признак темы в названии
    (кроме вакансий, найденных по точным словам — trusted_fulltext_queries)."""
    cfg = cfg or load_config()
    stop = [w.lower() for w in cfg["stop_title_words"]]
    regions = set(cfg["regions"])
    whole = set(cfg["relevance_whole_word_stems"])
    trusted = set(cfg["trusted_fulltext_queries"])

    def relevant(c):
        if trusted & set(c["queries"]):
            return True
        t = c["title"].lower()
        for s in cfg["relevance_title_stems"]:
            if s in whole:
                if re.search(rf"(?<![a-zа-яё]){s}(?![a-zа-яё])", t):
                    return True
            elif s in t:
                return True
        return False

    oldest = (date.today() - timedelta(days=cfg.get("max_age_days", 3))).isoformat()
    passed, rejected = [], []
    for c in cards:
        title = c["title"].lower()
        hit = next((w for w in stop if w in title), None)
        remote = "REMOTE" in c["work_formats"]
        in_region = any(f".{r}." in c["area_path"] or c["area_id"] == r for r in regions)
        if hit:
            reason = f"stop_title:{hit}"
        elif c["experience"] not in cfg["allowed_experience"]:
            reason = f"experience:{c['experience']}"
        elif not remote and not in_region:
            reason = f"region:{c['area_name']}"
        elif not relevant(c):
            reason = "irrelevant_title"
        elif (c["published"] or "")[:10] < oldest:
            reason = "old"
        else:
            passed.append(c)
            continue
        rejected.append({**c, "reason": reason})
    return {"passed": passed, "rejected": rejected}


def details(cards, cfg=None, log=print):
    """Звено 4. Подробности: открывает страницу каждой вакансии → полный текст, навыки, адрес."""
    cfg = cfg or load_config()
    out, errors = [], []
    for i, c in enumerate(cards, 1):
        try:
            v = page_state(fetch(c["url"], cfg["request_pause_sec"]))["vacancyView"]["vacancyFull"]["vacancy"]
        except Exception as e:
            errors.append({"id": c["id"], "error": str(e)})
            continue
        addr = v.get("address") or {}
        out.append({
            **c,
            "description": strip_tags(v.get("description", "")),
            "key_skills": v.get("keySkills") or [],
            "work_formats": v.get("workFormats") or c["work_formats"],
            "address": addr.get("displayName") or addr.get("city") or "",
            "status": (v.get("status") or {}).get("archived") if isinstance(v.get("status"), dict) else v.get("status"),
        })
        if i % 10 == 0 or i == len(cards):
            log(f"  подробности: {i}/{len(cards)}")
    return {"vacancies": out, "errors": errors}


def is_open(vid, cfg=None):
    """Вакансия ещё принимает отклики? (могла уйти в архив между сбором и подборкой)"""
    cfg = cfg or load_config()
    v = page_state(fetch(f"https://hh.ru/vacancy/{vid}", cfg["request_pause_sec"]))["vacancyView"]["vacancyFull"]["vacancy"]
    status = v.get("status") or {}
    return not (status.get("archived") or status.get("disabled") or v.get("closedForApplicants"))
