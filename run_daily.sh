#!/bin/bash
# Ежедневный запуск агента (вызывается планировщиком macOS в 8:00, см. com.kiselev.job-agent.plist).
# Аргументы передаются в agent.run; без аргументов — весь день целиком.
cd "$(dirname "$0")" || exit 1
mkdir -p data/logs
LOG="data/logs/$(date +%Y-%m-%d).log"
# После пробуждения Mac сеть появляется не сразу — ждём до 2 минут
for i in $(seq 1 24); do
  /usr/bin/curl -s -o /dev/null --max-time 5 https://hh.ru && break
  sleep 5
done
/usr/bin/python3 -u -m agent.run "${@:-all}" >> "$LOG" 2>&1
