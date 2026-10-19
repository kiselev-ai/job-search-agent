#!/bin/bash
# Ежедневный запуск агента (вызывается планировщиком macOS, время — в com.kiselev.job-agent.plist).
# Аргументы передаются в agent.run; без аргументов — весь день целиком.
cd "$(dirname "$0")" || exit 1
mkdir -p data/logs
LOG="data/logs/$(date +%Y-%m-%d).log"
# Без аргументов — один полный запуск в день: если подборка сегодня уже ушла, второй раз не запускаемся
if [ $# -eq 0 ] && [ -f "data/runs/$(date +%Y-%m-%d)/08_deliver.json" ]; then
  echo "$(date '+%d.%m.%Y %H:%M') — подборка за сегодня уже отправлена, запуск пропущен" >> "$LOG"
  exit 0
fi
# После пробуждения Mac сеть появляется не сразу — ждём до 2 минут
for i in $(seq 1 24); do
  /usr/bin/curl -s -o /dev/null --max-time 5 https://hh.ru && break
  sleep 5
done
/usr/bin/python3 -u -m agent.run "${@:-all}" >> "$LOG" 2>&1
