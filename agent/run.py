"""Запуск звеньев. Пример: python3 -m agent.run collect   (или: novelty, filter, details, flags, evaluate,
select, deliver, inbox, letters, all)

Каждое звено читает выход предыдущего из data/runs/<сегодня>/ и пишет свой.
"""
import json
import sys
from datetime import date

from . import assess, digest, letter, links, telegram
from .common import DATA, load_config, load_step, save_step


def step_collect(cfg):
    print("Звено 1 — сбор:")
    res = links.collect(cfg)
    print(f"  итого: {len(res['cards'])} уникальных вакансий, ошибок страниц: {len(res['errors'])}")
    save_step("01_collect", res)


def step_novelty(cfg):
    res = links.novelty(load_step("01_collect")["cards"])
    print(f"Звено 2 — новизна: новых {len(res['new'])}, уже виденных {res['already_seen']}")
    save_step("02_novelty", res)


def step_filter(cfg):
    res = links.hard_filter(load_step("02_novelty")["new"], cfg)
    reasons = {}
    for r in res["rejected"]:
        key = r["reason"].split(":")[0]
        reasons[key] = reasons.get(key, 0) + 1
    print(f"Звено 3 — фильтр: прошло {len(res['passed'])}, отсеяно {len(res['rejected'])} {reasons}")
    save_step("03_filter", res)


def step_details(cfg):
    print("Звено 4 — подробности:")
    cards = load_step("03_filter")["passed"]
    try:  # повторный запуск докачивает только то, чего ещё нет
        done = {v["id"]: v for v in load_step("04_details")["vacancies"]}
    except FileNotFoundError:
        done = {}
    res = links.details([c for c in cards if c["id"] not in done], cfg)
    ids = {c["id"] for c in cards}
    res["vacancies"] = [v for v in done.values() if v["id"] in ids] + res["vacancies"]
    print(f"  всего с подробностями {len(res['vacancies'])} из {len(cards)}, ошибок {len(res['errors'])}")
    save_step("04_details", res)


def step_flags(cfg):
    vs = load_step("04_details")["vacancies"]
    for v in vs:
        v["rule_flags"] = assess.red_flags(v)
    print(f"Звено 5 — подвохи: с флагами {sum(bool(v['rule_flags']) for v in vs)} из {len(vs)}")
    save_step("05_flags", {"vacancies": vs})


def step_evaluate(cfg):
    vs = load_step("05_flags")["vacancies"]
    try:  # повторный запуск оценивает только неоценённое
        done = {v["id"]: v for v in load_step("06_evaluate")["vacancies"] if v.get("eval", {}).get("score")}
    except FileNotFoundError:
        done = {}
    model = cfg.get("gigachat_model", "GigaChat")
    print(f"Звено 6 — оценка ({model}):")
    out, tokens = [], 0
    for i, v in enumerate(vs, 1):
        if v["id"] in done:
            out.append(done[v["id"]])
            continue
        try:
            v["eval"] = assess.evaluate(v, model)
        except Exception as e:
            v["eval"] = {"score": None, "why": f"ошибка GigaChat: {e}", "direction": "other", "red_flags": [], "salary_ok": True, "tokens": 0}
        tokens += v["eval"].get("tokens", 0)
        out.append(v)
        if i % 10 == 0:
            save_step("06_evaluate", {"vacancies": out})  # промежуточное сохранение
            print(f"  {i}/{len(vs)}, токенов {tokens}")
    save_step("06_evaluate", {"vacancies": out})
    scores = [v["eval"]["score"] for v in out if v["eval"].get("score")]
    print(f"  оценено {len(scores)} из {len(out)}, токенов за запуск {tokens}; "
          f"≥6 баллов: {sum(s >= 6 for s in scores)}")


def step_select(cfg):
    save_step("07_select", digest.select(load_step("06_evaluate")["vacancies"], cfg))


def step_deliver(cfg):
    try:  # повторный запуск не шлёт то, что уже ушло
        sent = load_step("08_deliver")["sent"]
    except FileNotFoundError:
        sent = []
    try:
        digest.deliver(load_step("07_select"), sent)
    finally:
        save_step("08_deliver", {"sent": sent})
    links.mark_seen(c["id"] for c in load_step("01_collect")["cards"])  # завтра эти вакансии не придут снова


def step_inbox(cfg):
    """Нажатия кнопок с прошлой подборки → data/decisions.json (для писем и учёта)."""
    presses = telegram.collect_presses()
    p = DATA / "decisions.json"
    decisions = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    for vid, action in presses:  # если нажали обе кнопки — действует последняя
        decisions[vid] = {"decision": action, "date": date.today().isoformat()}
    p.write_text(json.dumps(decisions, ensure_ascii=False, indent=1), encoding="utf-8")
    likes = sum(a == "like" for _, a in presses)
    print(f"Входящие: нажатий {len(presses)} (интересно {likes}, не надо {len(presses) - likes})")


def step_letters(cfg):
    """Звено 9. Письма для вакансий с «Интересно», у которых письма ещё нет → в Telegram и data/letters/."""
    p = DATA / "decisions.json"
    decisions = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    todo = [vid for vid, d in decisions.items() if d["decision"] == "like" and not d.get("letter")]
    model = cfg.get("gigachat_model", "GigaChat")
    (DATA / "letters").mkdir(exist_ok=True)
    tokens = 0
    for vid in todo:
        v = letter.find_vacancy(vid)
        if not v:
            print(f"  {vid}: вакансия не найдена в выходах оценки — пропуск")
            continue
        text, issues, used = letter.write(v, model, cfg)
        tokens += used
        (DATA / "letters" / f"{vid}.txt").write_text(text, encoding="utf-8")
        head = f"✉️ <b>Письмо для отклика</b>\n{telegram.esc(v['title'])} — {telegram.esc(v['company'])}\n{v['url']}"
        if issues:
            head += "\n\n⚠️ <b>Проверьте, в профиле этого нет:</b>\n" + "\n".join(f"• {telegram.esc(i)}" for i in issues)
        telegram.send(head)
        telegram.send(telegram.esc(text))
        decisions[vid]["letter"] = date.today().isoformat()
        p.write_text(json.dumps(decisions, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Звено 9 — письма: готово {sum(1 for v in todo if decisions[v].get('letter'))} из {len(todo)}, токенов {tokens}")


STEPS = {"inbox": step_inbox, "letters": step_letters, "collect": step_collect, "novelty": step_novelty, "filter": step_filter,
         "details": step_details, "flags": step_flags, "evaluate": step_evaluate, "select": step_select,
         "deliver": step_deliver}


def main():
    cfg = load_config()
    names = sys.argv[1:] or ["all"]
    if names == ["all"]:
        names = list(STEPS)
    for n in names:
        STEPS[n](cfg)


if __name__ == "__main__":
    main()
