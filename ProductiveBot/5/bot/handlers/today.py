import os
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional
from aiogram import Router, types, F
from aiogram.filters import Command
from notion_client import Client
from bot.csv_db import get_notion_connection, get_user
from bot.prompts import TODAY_DASHBOARD_PROMPT
from bot.utils import client as openai_client
from bot.utils import _to_iso_local
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)
router = Router()

def format_time_msk(iso_str: str) -> str:
    MSK = ZoneInfo("Europe/Moscow")
    """
    iso_str – любая ISO-8601 строка, которую отдаёт Notion (`YYYY-MM-DDTHH:MM:SS[.fff][±HH:MM|Z]`).

    Возвращает время в формате «HH:MM» уже в московской тайм-зоне.
    """
    # 1.  Конвертируем ISO-строку в datetime
    dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))

    # 2.  Если в строке не было TZ-offset'а → считаем её UTC
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    # 3.  Переводим в МСК и красиво выводим
    return dt.astimezone(MSK).strftime("%H:%M")

def format_time(iso_time: str) -> str:
    """Format ISO time to HH:MM."""
    try:
        dt = datetime.fromisoformat(iso_time.replace('Z', '+00:00'))
        return dt.strftime('%H:%M')
    except:
        return iso_time

def get_week_start() -> str:
    """Get ISO date of the start of current week (Monday)."""
    today = datetime.now()
    monday = today - timedelta(days=today.weekday())
    return monday.strftime('%Y-%m-%d')

async def get_today_activities(notion: Client, database_id: str) -> Dict[str, List[Dict]]:
    """Get today's activities from Notion database."""
    try:
        # Get today's date in ISO format
        today_dt = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
        start_iso = today_dt.isoformat()
        start_iso = datetime.now().astimezone().strftime("%Y-%m-%d")
        end_iso   = (today_dt + timedelta(days=1, microseconds=-1)).isoformat()

        # Query database for today's activities
        response = notion.databases.query(
            database_id=database_id,
            filter={
                "and": [
                    {
                        "property": "Start Date",
                        "date": {
                            # "on_or_after": start_iso,
                            # "before": end_iso
                            "equals": start_iso
                        }
                    },
                    {
                        "or": [
                            {
                                "property": "type",
                                "status": {
                                    "equals": "таск"
                                }
                            },
                            {
                                "property": "type",
                                "status": {
                                    "equals": "мероприятие"
                                }
                            },
                            {
                                "property": "type",
                                "status": {
                                    "equals": "ChatGPTтаск"
                                }
                            },
                            {
                                "property": "type",
                                "status": {
                                    "equals": "ChatGPTмероприятие"
                                }
                            }
                        ]
                    }
                ]
            }
        )
        
        # Process activities
        activities = {}
        for page in response["results"]:
            props = page["properties"]
            
            # Get basic info
            name = props["Name"]["title"][0]["plain_text"]
            start_date = props["Start Date"]["date"]["start"]
            end_date = props["End Date"]["date"]["start"] if props["End Date"]["date"] else None
            
            # Get sphere if exists
            sphere = None
            sp = props.get("Sphere_plain_text")

            if sp:
                # 1) rich-text
                if sp.get("rich_text"):
                    sphere = sp["rich_text"][0]["plain_text"]

                # 2) title
                elif sp.get("title"):
                    sphere = sp["title"][0]["plain_text"]

                # 3) formula → string
                elif sp.get("formula") and sp["formula"].get("string"):
                    sphere = sp["formula"]["string"]

            
            # Group by sphere
            sphere = sphere or "Без категории"
            if sphere not in activities:
                activities[sphere] = []
            
            activities[sphere].append({
                "name": name,
                "start_time": format_time_msk(start_date),
                "end_time": format_time_msk(end_date) if end_date else None
            })
        
        return activities
        
    except Exception as e:
        logger.error(f"Error getting today's activities: {e}")
        return {}

async def get_habits_progress(notion: Client, habit_db_id: str, main_db_id: str) -> List[Dict]:
    """Get habits progress from Notion databases."""
    try:
        # Get active habits
        habits_response = notion.databases.query(
            database_id=habit_db_id,
            filter={
                "property": "Status",
                "status": {
                    "equals": "Занимаюсь"
                }
            }
        )
        
        habits = []
        week_start = get_week_start()
        today = datetime.now()
        end_of_week = (today + timedelta(days=6-today.weekday())).strftime('%Y-%m-%d')
        today_str = today.strftime('%Y-%m-%d')
        
        for page in habits_response["results"]:
            props = page["properties"]
            habit_name = props["Name"]["title"][0]["plain_text"]
            week_frequency = props["Week_frequency"]["number"] or 0
            
            # Count habit completions this week
            completions = notion.databases.query(
                database_id=main_db_id,
                filter={
                    "and": [
                        {
                            "property": "type",
                            "select": {
                                "equals": "привычка"
                            }
                        },
                        {
                            "property": "Name",
                            "title": {
                                "equals": habit_name
                            }
                        },
                        {
                            "property": "Start Date",
                            "date": {
                                "on_or_after": week_start,
                                "on_or_before": end_of_week
                            }
                        }
                    ]
                }
            )
            
            habits.append({
                "name": habit_name,
                "week_frequency": week_frequency,
                "count_week_now": len(completions["results"])
            })
        
        return habits
        
    except Exception as e:
        logger.error(f"Error getting habits progress: {e}")
        return []

async def get_gpt_insights(message: str) -> str:
    """Get GPT insights for the dashboard message."""
    try:
        # Get GPT response
        response = openai_client.chat.completions.create(
            model="o4-mini",
            messages=[
                {"role": "system", "content": "You are a helpful assistant that provides personalized insights."},
                {"role": "user", "content": TODAY_DASHBOARD_PROMPT.format(message=message)}
            ]
        )
        
        return response.choices[0].message.content
        
    except Exception as e:
        logger.error(f"Error getting GPT insights: {e}")
        return message

@router.message(Command("today"))
async def cmd_today(message: types.Message):
    """Handle /today command to show today's dashboard."""
    try:
        user_id = message.from_user.id
        
        # Get user info
        user_info = get_user(user_id)
        if not user_info:
            await message.answer("❌ User information not found. Please use /start first.")
            return
        
        # Get Notion connections
        notion_token = get_notion_connection(user_id, "NOTION_TOKEN")
        main_db_id = get_notion_connection(user_id, "NOTION_MAIN_DATABASE_ID")
        habit_db_id = get_notion_connection(user_id, "NOTION_DATABASE_HABIT")
        
        if not notion_token or not main_db_id:
            await message.answer(
                "❌ Notion is not connected. Please use:\n"
                "• /connect_notion [token] to connect your Notion account\n"
                "• /connect_notion_table [database_id] to connect your main task database"
            )
            return
        
        # Initialize Notion client
        notion = Client(auth=notion_token)
        
        # Get today's activities
        activities = await get_today_activities(notion, main_db_id)
        if not activities:
            await message.answer("📅 No activities planned for today.")
            return
        
        # Get habits progress if habit database is connected
        habits = []
        if habit_db_id:
            habits = await get_habits_progress(notion, habit_db_id, main_db_id)
        
        # Format today's date
        today = datetime.now().strftime("%d.%m.%Y")
        
        # Build initial dashboard message
        dashboard = [
            f"🌅 Доброе утро, {user_info['login']}! Сегодня отличный день {today}!\n",
            f"Если вкратце, то сегодня [GPT_summary]",
            f"[GPT_custom_motto] 🚀\n",
            f"------------------\n",
            "🦄 Сегодняшние таски и события:\n"
        ]
        
        # Add activities
        for sphere, acts in activities.items():
            dashboard.append(f"- {sphere}")
            for i, act in enumerate(acts, 1):
                time_str = f"{act['start_time']} - {act['end_time']}" if act['end_time'] else act['start_time']
                dashboard.append(f"{i}. {act['name']} {time_str}")
            dashboard.append("")
        
        # Add habits if any
        if habits:
            dashboard.append("------------------\n💦 Привычки")
            for i, habit in enumerate(habits[:10], 1):  # Show only first 10 habits
                dashboard.append(
                    f"• {habit['name']}: {habit['count_week_now']} / {habit['week_frequency']} – "
                    f"рекомендую [GPT_habit_time_{i}]"
                )
            dashboard.append("")
        
        # Add relaxation suggestions
        dashboard.extend([
            "------------------",
            "🧘 Можно отдохнуть",
            "• [GPT_relax_activity_1] в [GPT_relax_time_1]",
            "• [GPT_relax_activity_2] в [GPT_relax_time_2]\n",
            "Сделай сегодня незабываемым✨",
            "Но не вини себя если что-то не успел 💜"
        ])
        
        # Get GPT insights for the complete message
        final_message = await get_gpt_insights("\n".join(dashboard))
        
        # Send dashboard
        await message.answer(final_message)
        
    except Exception as e:
        logger.error(f"Error in today command: {e}")
        await message.answer("❌ Something went wrong while generating your dashboard. Please try again.") 