import os
import json
import logging
import asyncio
import aiohttp
import re
import pandas as pd
from datetime import datetime, timezone, date, time
from tempfile import NamedTemporaryFile
from openai import OpenAI
from dotenv import load_dotenv
from bot.prompts import TASK_ANALYSIS_PROMPT, NOTION_MAPPING, THOUGHT_ANALYSIS_PROMPT
from zoneinfo import ZoneInfo
from aiogram import types
from typing import List, Dict, Optional


load_dotenv()
logger = logging.getLogger(__name__)
# Initialize OpenAI client
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def list_page_options(notion, database_id: str) -> list[dict]:
    """Return list of dictionaries: [{"name": "work", "id": "...", "descr": "…"}, …]"""
    try:
        pages = notion.databases.query(
            database_id=database_id,
            filter={
                "property": "Select",
                "select": {"equals": "2 уровень"}
            },
            page_size=100
        )["results"]

        options = []
        for page in pages:
            props = page["properties"]
            name = props["Name"]["title"][0]["plain_text"]
            descr = props.get("Description", {}).get("rich_text", [])
            descr = descr[0]["plain_text"] if descr else ""
            options.append({"name": name, "id": page["id"], "descr": descr})
        return options
    except Exception as e:
        logger.error(f"Error getting page options: {e}")
        return []

def build_prompt(task_names: List[str], timestamp: str, page_opts: list[dict]) -> str:
    
    """Собираем промпт: в GPT идёт ТОЛЬКО список названий."""
    task_text = "\n".join(f"- {name}" for name in task_names)
    sphere_block = ""

    if page_opts != []:
        sphere_block = "\n".join(
        f"- {o['name']} (id: {o['id']}) – {o['descr']}" for o in page_opts
    )
    return TASK_ANALYSIS_PROMPT.format(
        task_text=task_text,
        timestamp=timestamp,
        sphere_block=sphere_block
    )


# Регулярки
_RE_DATE_ISO   = re.compile(r"^\s*(\d{4}-\d{2}-\d{2})\s*$")
_RE_DATE_DMY   = re.compile(r"^\s*(\d{1,2}[./]\d{1,2}[./]\d{2,4})\s*$")
_RE_LINE       = re.compile(
    r"""
    ^\s*
    (?P<start>\d{1,2}:\d{2})        # 9:31
    \s*[-—]\s*                      # любой дефис/тире
    (?:(?P<end>\d{1,2}:\d{2})\s*)?  # 9:57  (необяз.)
                                    # если end нет — сразу идёт body
    (?P<body>.+?)                   # читаю "как быть стоиком" 7
    \s*$                            # конец строки
    """,
    re.VERBOSE,
)
TZ_MOSCOW = ZoneInfo("Europe/Moscow")

    
def _parse_date(line: str) -> Optional[date]:
    """Пытаемся взять дату из первой строки."""
    if m := _RE_DATE_ISO.match(line):
        return datetime.fromisoformat(m.group(1)).date()
    if m := _RE_DATE_DMY.match(line):
        return datetime.strptime(m.group(1), "%d.%m.%Y").date()
    return None

def _parse_activity_lines(
    lines: List[str], day: date
) -> List[Dict[str, str | int | None]]:
    """
    Разбираем список строк с активностями.
    Возвращаем список словарей: start_datetime, end_datetime, name, csat.
    """
    raw_tasks: List[Dict[str, str | int | None]] = []

    for line in lines:
        if not line.strip():
            continue  # пропускаем пустые строки

        m = _RE_LINE.match(line)
        if not m:
            # строка не соответствует формату — просто игнорируем
            continue

        start_str, end_str, body = m.group("start", "end", "body")

        # Ищем CSAT — последняя «голая» цифра
        csat: Optional[int] = None
        body_clean = body.strip()
        if body_clean and body_clean.split()[-1].isdigit():
            csat = int(body_clean.split()[-1])
            body_clean = body_clean[: body_clean.rfind(str(csat))].rstrip()

        raw_tasks.append(
            {
                "start_time": start_str,
                "explicit_end": end_str,  # может быть None
                "name": body_clean,
                "csat": csat,
            }
        )

    # Второй проход — ставим время конца, если не указано
    for idx, task in enumerate(raw_tasks):
        if task["explicit_end"]:
            task["end_time"] = task["explicit_end"]
        else:
            # берём время начала следующей активности
            next_start = (
                raw_tasks[idx + 1]["start_time"] if idx + 1 < len(raw_tasks) else None
            )
            task["end_time"] = next_start

    # Финальное формирование datetime
    tasks: List[Dict[str, str | int | None]] = []
    for task in raw_tasks:
        start_dt = datetime.combine(
            day,
            datetime.strptime(task["start_time"], "%H:%M").time(),
            TZ_MOSCOW,
        )
        end_time_raw = task["end_time"]
        end_dt: Optional[datetime] = None
        if end_time_raw:
            end_candidate = datetime.combine(
                day,
                datetime.strptime(end_time_raw, "%H:%M").time(),
                TZ_MOSCOW,
            )
            # Если «сквозь полночь» — двигаем дату
            if end_candidate < start_dt:
                end_candidate = end_candidate.replace(day=day.day + 1)
            end_dt = end_candidate

        tasks.append(
            {
                "name": task["name"],
                "start_datetime": start_dt,
                "end_datetime": end_dt,
                "csat": task["csat"],
            }
        )

    return tasks

def analyze_thoughts_with_gpt(
    thoughts_text: str, timestamp: str, page_opts: list[dict]
) -> list[dict] | None:
    """Простой wrapper вокруг ChatGPT — без расчёта времени."""
    try:
        

        prompt = THOUGHT_ANALYSIS_PROMPT.format(
            thoughts=thoughts_text,
            timestamp=timestamp,
            sphere_block=page_opts,
        )
        print(prompt)
        response = client.chat.completions.create(
            model="o4-mini",
            messages=[
                {"role": "system", "content": "You are a thought analysis assistant."},
                {"role": "user", "content": prompt},
            ]
        )

        print(response)
        raw = response.choices[0].message.content.strip().removeprefix("```json").removesuffix("```")
        thoughts_data = json.loads(raw)
        return thoughts_data

    except Exception as exc:
        logger.error("[analyze_thoughts_with_gpt] %s", exc)
        return None


def analyze_task_with_gpt(task_text: str, timestamp: str, page_opts: list[dict]) -> list[dict] | None:
    """
    Анализирует список активностей.
    Шаги:
    1. Парсинг времени/CSAT (локально, без GPT).
    2. В GPT уходит ТОЛЬКО текст названий — для классификации.
    3. Объединяем результаты и возвращаем готовый список задач.
    """
    try:
        # ───── 1. Определяем дату дня ─────
        print('\n--------------------------', task_text)
        first_line, *other_lines = task_text.splitlines()
        task_date = _parse_date(first_line)
        lines_for_parse = other_lines if task_date else task_text.splitlines()
        if not task_date:
            # берём дату из timestamp, если в тексте нет даты
            task_date = datetime.fromisoformat(timestamp).astimezone(TZ_MOSCOW).date()

        # ───── 2. Парсим время и CSAT ─────
        parsed_tasks = _parse_activity_lines(lines_for_parse, task_date)
        if not parsed_tasks:
            raise ValueError("Не удалось разобрать ни одной активности.")
        print('\n--------------------------', parsed_tasks)
        # ───── 3. Готовим запрос к GPT ─────
        task_names = [t["name"] for t in parsed_tasks]
        prompt = build_prompt(task_names, timestamp, page_opts)

        response = client.chat.completions.create(
            model="o4-mini",
            messages=[
                {"role": "system", "content": """Вы — опытный менеджер по личной эффективности и высокоуровневый ассистент ChatGPT.  
Ваша задача — разобрать описание, выявить один или несколько самостоятельных элементов
и вернуть структурированные данные."""},
                {"role": "user", "content": prompt}
            ]
        )

        gpt_raw = response.choices[0].message.content.strip()
        gpt_json_str = gpt_raw.removeprefix("```json").removesuffix("```")
        gpt_tasks = json.loads(gpt_json_str)

        # ───── 4. Сопоставляем результаты ─────
        if len(gpt_tasks) != len(parsed_tasks):
            raise ValueError(
                "Количество элементов от GPT не совпадает "
                "с количеством распарсенных активностей."
            )

        merged_tasks = []
        print('\n--------------------------', "HERE WE ARE")
        for local, remote in zip(parsed_tasks, gpt_tasks, strict=True):
            remote["start_datetime"] = _to_iso_local(local["start_datetime"])
            remote["end_datetime"] = _to_iso_local(local["end_datetime"])
            remote["csat"] = local["csat"]
            merged_tasks.append(remote)

        return merged_tasks

    # ───── 5. Обработка ошибок ─────
    except Exception as exc:
        # В прод-боте логируем через logging; здесь — print для наглядности
        print(f"[analyze_task_with_gpt] error: {exc}")
        return None
    
    # # ПУСТОЙ МАССИВ ДЕЛАЕМ

    # # ЗДЕСЬ СТАВИМ ВРЕМЯ (и дату из начала сообщения)

    # # ЗДЕСЬ CSAT

    # # ChatGPT ИНФУ БЕЗ ВРЕМЕНИ и CSAT (проекты, сферы жизни)

    # # ИЗ МАССИВА С ОТ CHATGPT  БЕРЕМ КАТЕГОРИИ
    # prompt = build_prompt(task_text, timestamp, page_opts)

    # try:
    #     response = client.chat.completions.create(
    #         model="o4-mini",
    #         messages=[
    #             {"role": "system", "content": "You are a task analysis assistant."},
    #             {"role": "user", "content": prompt}
    #         ]
    #     )

    #     corrected = response.choices[0].message.content.strip()

    #     raw = corrected.removeprefix("```json").removesuffix("```")
    #     print("--------------------------------")
    #     print(raw)
    #     tasks_data = json.loads(raw)
        
    #     # Process each task
    #     for task in tasks_data:
    #         task["start_datetime"] = _to_iso_local(task.get("start_datetime"))
    #         task["end_datetime"] = _to_iso_local(task.get("end_datetime"))
        
    #     print(tasks_data)
    #     return tasks_data
    
    # except Exception as e:
    #     print(f"Error analyzing task with GPT: {e}")
    #     return None

def save_task_to_csv(tasks_data: list[dict], csv_path: str) -> bool:
    """Save multiple tasks to CSV file."""
    try:
        # Create DataFrame with all tasks
        df = pd.DataFrame(tasks_data)
        
        # If file exists, append to it
        if os.path.exists(csv_path):
            existing_df = pd.read_csv(csv_path)
            df = pd.concat([existing_df, df], ignore_index=True)
        
        # Save to CSV
        df.to_csv(csv_path, index=False)
        return True
    except Exception as e:
        print(f"Error saving tasks to CSV: {e}")
        return False

def _to_iso_local(dt: datetime | None) -> str | None:
    """Преобразуем datetime → ISO-8601 в локальной зоне."""
    return dt.astimezone(TZ_MOSCOW).isoformat(timespec="seconds") if dt else None

def create_notion_thought(
    thoughts: list[dict],
    raw_text: str,
    notion,
    db_id: str,
) -> bool:
    """
    Создаёт страницы мыслей; сырой текст кладём в первый параграф.
    """
    print(raw_text, thoughts)
    now_iso = datetime.now(tz=TZ_MOSCOW).isoformat(timespec="seconds")
    ok = True

    # общий paragraph-block с исходным текстом
    raw_paragraph = {
        "object": "block",
        "type": "paragraph",
        "paragraph": {
            "rich_text": [{"type": "text", "text": {"content": raw_text}}],
        },
    }

    for idea in thoughts:
        props = {
            "Name":    {"title": [{"text": {"content": idea["name"]}}]},
            "Date":    {"date": {"start": now_iso}},
            "Status":  {"status": {"name": "помыслитьChatGPT"}},
        }

        # связь со сферой
        if sid := idea.get("sphere_page_id"):
            props["Sphere"] = {"relation": [{"id": sid}]}
        elif sname := idea.get("sphere_text"):
            props["Sphere"] = {"rich_text": [{"text": {"content": sname}}]}

        try:
            notion.pages.create(
                parent={"database_id": db_id},
                properties=props,
                children=[raw_paragraph],   # ⬅️ сырой текст внутри страницы
            )
        except Exception as exc:
            logger.error("Notion create_thought failed: %s", exc)
            ok = False
    return ok



def create_notion_task(tasks_data: list[dict], notion_client, database_id: str) -> bool:
    """Create multiple tasks in Notion."""
    try:
        for task_data in tasks_data:
            props = {}

            # Title
            props["Name"] = {
                "title": [{"text": {"content": task_data["name"]}}]
            }

            # Sphere text
            if task_data.get("sphere_text"):
                props["Sphere_text"] = {
                    "rich_text": [{"text": {"content": task_data["sphere_text"]}}]
                }

            # Dates
            if task_data.get("start_datetime"):
                props["Start Date"] = {
                    "date": {"start": task_data["start_datetime"]}
                }
            if task_data.get("end_datetime"):
                props["End Date"] = {
                    "date": {"start": task_data["end_datetime"]}
                }

            # Status/Type
            if task_data.get("type"):
                props["type"] = {"status": {"name": task_data["type"]}}

            # Project
            if task_data.get("project"):
                props["Project"] = {
                    "rich_text": [{"text": {"content": task_data["project"]}}]
                }

            # ChatGPT comment
            if task_data.get("chatGPT_comment"):
                props["ChatGPT_comment"] = {
                    "rich_text": [{"text": {"content": task_data["chatGPT_comment"]}}]
                }
            
            # CSAT
            
            if task_data.get("csat"):
                print(int(task_data["csat"]))
                props["csat"] = {
                    "number": int(task_data["csat"])
                }
        
            # Sphere relation
            sphere_page_id = task_data.get("sphere_page_id")
            if sphere_page_id:
                props["Sphere"] = {"relation": [{"id": task_data["sphere_page_id"]}]}

            notion_client.pages.create(
                parent={"database_id": database_id},
                properties=props,
            )
        return True

    except Exception as e:
        print(f"Error creating Notion tasks: {e}")
        return False

async def process_voice_message(message: types.Message, bot) -> str | None:
    """Process voice message and return transcribed text."""
    try:
        voice = message.voice
        file = await bot.get_file(voice.file_id)
        file_path = file.file_path

        # Download voice file
        url = f"https://api.telegram.org/file/bot{bot.token}/{file_path}"
        async with aiohttp.ClientSession() as sess, sess.get(url) as resp:
            opus_data = await resp.read()

        # Save to temporary file
        with NamedTemporaryFile(delete=False, suffix=".oga") as tmp:
            tmp.write(opus_data)
            opus_file = tmp.name

        # Convert to WAV
        wav_file = opus_file.replace(".oga", ".wav")
        cmd = f"ffmpeg -y -i {opus_file} -ar 16000 -ac 1 {wav_file}"
        proc = await asyncio.create_subprocess_shell(
            cmd, stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL)
        await proc.communicate()
        print(wav_file)
        # Transcribe with Whisper
        with open(wav_file, "rb") as f:
            response = client.audio.transcriptions.create(
                file=f,
                model="whisper-1",
                language="ru"
            )
        text = response.text.strip()
        print(text)
        return text

    except Exception as e:
        print(f"Error processing voice message: {e}")
        return None

    finally:
        # Clean up temporary files
        for f in (opus_file, wav_file):
            try:
                os.remove(f)
            except:
                pass
