import os
import logging
from datetime import datetime
from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.enums import ContentType  
from notion_client import Client
from bot.utils import (
    analyze_task_with_gpt, create_notion_task,
    process_voice_message, list_page_options,
    analyze_thoughts_with_gpt, create_notion_thought
)
from bot.csv_db import save_tasks, add_user, get_notion_connection
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)
router = Router()

def _display_local(dt_iso: str | None) -> str:
    if not dt_iso:
        return "Not set"
    msk = ZoneInfo("Europe/Moscow")
    # заменить Z на +00:00, чтобы fromisoformat понял
    dt = datetime.fromisoformat(dt_iso.replace("Z", "+00:00"))
    return dt.astimezone(msk).strftime("%d.%m.%Y %H:%M")


def format_task_response(task: dict) -> str:
    """Format a single task for response message."""
    return (
        f"📝 {task['name']}\n"
        f"📅 Start: {_display_local(task.get('start_datetime', 'Not set'))}\n"
        f"⏰ End: {_display_local(task.get('end_datetime', 'Not set'))}\n"
        f"📊 Type: {task.get('type', 'Not specified')}\n"
        f"🎯 Project: {task.get('project', 'Not specified')}\n"
        f"🌐 Sphere: {task.get('sphere_text', 'Not specified')}\n"
        f"💡 {task.get('chatGPT_comment', '')}\n"
    )

async def send_long_message(message: types.Message, text: str, max_length: int = 4000):
    """Split and send long messages in chunks."""
    if len(text) <= max_length:
        await message.answer(text)
        return
    
    # Split the text into chunks
    chunks = []
    current_chunk = ""
    
    for line in text.split('\n'):
        if len(current_chunk) + len(line) + 1 <= max_length:
            current_chunk += line + '\n'
        else:
            if current_chunk:
                chunks.append(current_chunk.strip())
            current_chunk = line + '\n'
    
    if current_chunk:
        chunks.append(current_chunk.strip())
    
    # Send each chunk
    for i, chunk in enumerate(chunks):
        if i == 0:
            await message.answer(chunk)
        else:
            await message.answer(f"(continued...)\n{chunk}")

async def process_thoughts(message: types.Message, text: str) -> bool:
    """
    Обработка блока «мысли».
    Алгоритм похож на process_tasks, но:
    • нет расчёта времени — берём `now`
    • статус всегда "помыслитьChatGPT"
    • используется analyze_thoughts_with_gpt + create_notion_thought
    """
    try:
        user_id = message.from_user.id
        username = message.from_user.username or message.from_user.first_name
        add_user(user_id, username)

        notion_token = get_notion_connection(user_id, "NOTION_TOKEN")
        notion_db_id = get_notion_connection(user_id, "NOTION_THOUGHTS_DATABASE_ID")
        notion_category_db_id = get_notion_connection(user_id, "NOTION_DATABASE_ID_1")

        TZ_MOSCOW = ZoneInfo("Europe/Moscow")
        timestamp = datetime.now(tz=TZ_MOSCOW).strftime("%Y-%m-%d %H:%M:%S")

        page_opts = []
        if notion_token and notion_category_db_id:
            notion_cli = Client(auth=notion_token)
            page_opts = list_page_options(notion_cli, notion_category_db_id)

        thoughts_data = analyze_thoughts_with_gpt(text, timestamp, page_opts)
        print(thoughts_data)
        if not thoughts_data:
            await message.answer("Не удалось разобрать мысли 🤔 Попробуйте ещё раз.")
            return False

        # запись в Notion, если подключен
        if notion_token and notion_db_id:
            notion_cli = Client(auth=notion_token)
            ok = create_notion_thought(thoughts_data, text, notion_cli, notion_db_id)
            if not ok:
                await message.answer("Мысли сохранены локально, но не попали в Notion.")
                return False
            status_msg = "💡 Мысли сохранены в Notion!"
        else:
            status_msg = (
                "💡 Мысли сохранены локально. Подключите Notion командами:\n"
                "• /connect_notion …\n"
                "• /connect_notion_thoughts_db …"
            )

        # обратная связь пользователю
        reply = [status_msg]
        for i, idea in enumerate(thoughts_data, 1):
            reply.append(f"\nМысль {i}: {idea['name']} — {idea.get('sphere_text', 'Без сферы')}")
        await send_long_message(message, "\n".join(reply))
        return True

    except Exception as exc:
        logger.exception("process_thoughts failed: %s", exc)
        await message.answer("Ошибка при обработке мыслей 😢")
        return False


async def process_tasks(message: types.Message, text: str) -> bool:
    """Process tasks from text and save them."""
    try:
        # Get user info and save/update in users.csv
        user_id = message.from_user.id
        username = message.from_user.username or message.from_user.first_name
        add_user(user_id, username)
        
        # Get user's Notion connections
        notion_token = get_notion_connection(user_id, "NOTION_TOKEN")
        notion_db_id = get_notion_connection(user_id, "NOTION_MAIN_DATABASE_ID")
        notion_category_db_id = get_notion_connection(user_id, "NOTION_DATABASE_ID_1")
        
        # Get current timestamp
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if not notion_token or not notion_db_id:

            # FOR THOSE WHO HASN'T CONNECTED NOTION
            page_opts = []
            tasks_data = analyze_task_with_gpt(text, timestamp, page_opts)
            if not tasks_data:
                await message.answer("Sorry, I couldn't analyze your tasks. Please try again.")
                return False
        
            # Save to CSV with user_id
            if save_tasks(tasks_data, user_id):
                logger.info(f"Saved {len(tasks_data)} tasks to CSV for user {user_id}")
            else:
                logger.error("Failed to save tasks to CSV")
                await message.answer("Sorry, I couldn't get your tasks.")
                return False
            
            # Send confirmation to user
            response = [f"✅ Created {len(tasks_data)} task(s) successfully! ❌ But not in Notion!\n Please use:\n"
                "• /connect_notion [token] to connect your Notion account\n"
                "• /connect_notion_table [database_id] to connect your main task database\n"
                "• And then send this message again\n"]
            for i, task in enumerate(tasks_data, 1):
                response.append(f"\nTask {i}:")
                response.append(format_task_response(task))
            
            await send_long_message(message, "\n".join(response))
            
            return False
        
        # Initialize Notion client with user's token
        notion = Client(auth=notion_token)
        
        
        
        # Get page options using user's category database
        page_opts = []
        if notion_category_db_id:
            page_opts = list_page_options(notion, notion_category_db_id)
        
        # Analyze tasks with GPT
        tasks_data = analyze_task_with_gpt(text, timestamp, page_opts)
        if not tasks_data:
            await message.answer("Sorry, I couldn't analyze your tasks. Please try again.")
            return False
        
        # Save to CSV with user_id
        if save_tasks(tasks_data, user_id):
            logger.info(f"Saved {len(tasks_data)} tasks to CSV for user {user_id}")
        else:
            logger.error("Failed to save tasks to CSV")
            await message.answer("Sorry, I couldn't save your tasks locally.")
            return False
        
        # Create in Notion
        if create_notion_task(tasks_data, notion, notion_db_id):
            logger.info(f"Created {len(tasks_data)} tasks in Notion for user {user_id}")
        else:
            logger.error("Failed to create tasks in Notion")
            await message.answer("Tasks saved locally but couldn't be added to Notion.")
            return False
        
        # Send confirmation to user
        response = [f"✅ Created {len(tasks_data)} task(s) successfully!\n"]
        for i, task in enumerate(tasks_data, 1):
            response.append(f"\nTask {i}:")
            response.append(format_task_response(task))
        
        await send_long_message(message, "\n".join(response))
        return True
        
    except Exception as e:
        logger.error(f"Error processing tasks: {e}")
        await message.answer("Sorry, something went wrong while processing your tasks. Please try again.")
        return False

@router.message((F.content_type == ContentType.TEXT) & ~F.text.startswith("/"))
async def handle_text(message: types.Message):
    """
    Роутинг входящих сообщений:
    • если первая непустая строка == «мысли» (без учёта регистра) →
      process_thoughts(...)
    • иначе → process_tasks(...)
    """
    logger.info("Received message from %s: %r", message.from_user.id, message.text)

    first_line, *rest = (message.text or "").splitlines()
    first_line = first_line.strip().lower()

    if first_line == "мысли":
        # всё после первой строки — собственно текст мыслей
        await process_thoughts(message, "\n".join(rest).strip())
    else:
        await process_tasks(message, message.text)

@router.message(F.content_type == ContentType.VOICE)
async def handle_voice(message: types.Message, bot):
    """Handle voice messages and create tasks from speech."""
    try:
        logger.info(f"Received voice message from user {message.from_user.id}")
        
        # Process voice message
        text = await process_voice_message(message, bot)
        if not text:
            await message.answer("Sorry, I couldn't transcribe your voice message. Please try again or send a text message.")
            return
        
        # Send transcription to user
        await message.answer(f"🎤 Transcribed: {text}")
        
        # Process the transcribed text as tasks
        await process_tasks(message, text)
        
    except Exception as e:
        logger.error(f"Error handling voice message: {e}")
        await message.answer("Sorry, something went wrong while processing your voice message. Please try again.") 