#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# run_bot.sh – запуск Telegram-бота (aiogram v3)   macOS / Ubuntu
# Работает, где бы скрипт ни лежал: в project-root или в самом bot/
# ---------------------------------------------------------------------------
set -euo pipefail

# ─── 0. Определяем каталоги ────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Если bot.py рядом со скриптом → мы уже в каталоге bot
if [[ -f "$SCRIPT_DIR/bot.py" ]]; then
  BOT_DIR="$SCRIPT_DIR"
# иначе ищем подкаталог bot/
elif [[ -f "$SCRIPT_DIR/bot/bot.py" ]]; then
  BOT_DIR="$SCRIPT_DIR/bot"
else
  echo "❌ Не найден bot.py (ни рядом, ни в $SCRIPT_DIR/bot)" >&2
  exit 1
fi

VENV_DIR="$BOT_DIR/.venv"
REQ_FILE="$BOT_DIR/requirements.txt"
ENV_FILE="$BOT_DIR/.env"

PY_MIN="3.10"

# ─── 1. Проверяем Python ───────────────────────────────────────────────────
if ! command -v python3 &>/dev/null; then
  echo "❌ python3 not found. Install Python ${PY_MIN}+." >&2
  exit 1
fi
PYTHON_BIN="$(command -v python3)"
PY_VER="$($PYTHON_BIN - <<'PY'
import sys; print(".".join(map(str, sys.version_info[:3])))
PY
)"

ver_lt() { [[ "$(printf '%s\n' "$1" "$2" | sort -V | head -n1)" == "$1" && "$1" != "$2" ]]; }
if ver_lt "$PY_VER" "$PY_MIN"; then
  echo "❌ Python >= ${PY_MIN} required, but found ${PY_VER}" >&2
  exit 1
fi

# ─── 2. virtualenv ─────────────────────────────────────────────────────────
if [[ ! -d "$VENV_DIR" ]]; then
  echo "➕ Создаём virtualenv в $VENV_DIR"
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi
# shellcheck source=/dev/null
source "$VENV_DIR/bin/activate"

pip --quiet install --upgrade pip wheel
if [[ -f "$REQ_FILE" ]]; then
  pip --quiet install -r "$REQ_FILE"
else
  echo "⚠️  requirements.txt не найден — пропускаем установку зависимостей"
fi

# ─── 3. .env ───────────────────────────────────────────────────────────────
if [[ -f "$ENV_FILE" ]]; then
  echo "🔑 Загружаем переменные из .env"
  # macOS BSD-xargs не понимает -d, поэтому используем POSIX-способ
  while IFS='=' read -r key value; do
    [[ $key == "" || $key == \#* ]] && continue
    export "$key=$value"
  done < <(grep -v '^[[:space:]]*#' "$ENV_FILE" | sed '/^[[:space:]]*$/d')
fi

if [[ -z "${BOT_TOKEN:-}" ]]; then
  echo "❌ BOT_TOKEN не задан (добавьте в .env или экспортируйте вручную)." >&2
  exit 1
fi

# ─── 4. Запуск бота ────────────────────────────────────────────────────────
echo "🚀 Запускаем пакет bot.bot  (polling)"
exec python -m bot.bot   