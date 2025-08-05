import logging
from aiogram import Router, types
from aiogram.filters import Command
from openai import OpenAI
from bot.csv_db import (
    get_user, get_notion_connection, get_user_tracks,
    add_user
)
import os
from dotenv import load_dotenv


logger = logging.getLogger(__name__)
router = Router()

# Initialize OpenAI client for quotes
load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

async def get_quote_of_the_day() -> str:
    """Get a fresh motivational quote from ChatGPT."""
    try:
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a motivational quote generator. Provide a short, inspiring quote (max 2 sentences) that would help someone be more productive and mindful."},
                {"role": "user", "content": "Generate a fresh motivational quote for today."}
            ]
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"Error getting quote of the day: {e}")
        return "Today is a new opportunity to be your best self."

def format_dashboard(user_info: dict, notion_status: dict, track_counts: dict, quote: str) -> str:
    """Format the dashboard message with all user information."""
    # User greeting
    dashboard = f"👋 Hello, {user_info['login']}!\n\n"
    
    # Notion connection status
    dashboard += "🔗 Notion Integration:\n"
    dashboard += f"• Token: {'✅ Connected' if notion_status['token'] else '❌ Not connected'}\n"
    dashboard += f"• Main Table: {'✅ Connected' if notion_status['main_table'] else '❌ Not connected'}\n"
    dashboard += f"• Category Tables: {'✅ Connected' if notion_status['category_tables'] else '❌ Not connected'}\n\n"
    
    # Track counts
    dashboard += "🎵 Your Tracks:\n"
    dashboard += f"• Pomodoro: {track_counts['pomodoro']} tracks\n"
    dashboard += f"• Sleep: {track_counts['sleep']} tracks\n\n"
    
    # Quote of the day
    dashboard += "💭 Quote of the Day:\n"
    dashboard += f"\"{quote}\"\n\n"
    
    # Available commands
    dashboard += "📋 Available Commands:\n"
    dashboard += "• /start - Refresh this dashboard\n"
    dashboard += "• /pomodoro [work_time] [relax_time] - Start pomodoro timer\n"
    dashboard += "• /add_music [youtube_link] - Add music for sleep/pomodoro\n"
    dashboard += "• /sleep - Get sleep tracks\n"
    dashboard += "• /connect_notion [token] - Connect Notion account\n"
    dashboard += "• /connect_notion_table [page_id] - Connect main task table\n"
    dashboard += "• /connect_notion_category_table [1-8] [page_id] - Connect category table\n\n"
    
    # Rules
    dashboard += "📌 Rules:\n"
    dashboard += "• Send text/voice messages to create tasks (if Notion is connected)\n"
    dashboard += "• All actions require confirmation (Yes/No)\n"
    dashboard += "• Category tables must have a Description field\n"
    dashboard += "• Main table must have: Name, Sphere, Start Date, End Date, type, Project, ChatGPT_comment\n"
    
    return dashboard

@router.message(Command("start"))
async def cmd_start(message: types.Message):
    """Handle /start command and show user dashboard."""
    logger.info(f"Received /start command from user {message.from_user.id}")
    try:
        # Get or create user
        user_id = message.from_user.id
        username = message.from_user.username or message.from_user.first_name
        add_user(user_id, username)
        user_info = get_user(user_id)
        
        # Check Notion connections
        notion_status = {
            'token': bool(get_notion_connection(user_id, "NOTION_TOKEN")),
            'main_table': bool(get_notion_connection(user_id, "NOTION_DATABASE_ID")),
            'category_tables': bool(get_notion_connection(user_id, "NOTION_DATABASE_ID_2"))
        }
        
        # Get track counts
        tracks = get_user_tracks(user_id)
        track_counts = {
            'pomodoro': len([t for t in tracks if t['track_type'] == 'pomodoro']),
            'sleep': len([t for t in tracks if t['track_type'] == 'sleep'])
        }
        
        # Get fresh quote
        quote = await get_quote_of_the_day()
        
        # Format and send dashboard
        dashboard = format_dashboard(user_info, notion_status, track_counts, quote)
        await message.answer(dashboard)
        
        logger.info(f"Successfully sent dashboard to user {user_id}")
    except Exception as e:
        logger.error(f"Error sending dashboard to user {message.from_user.id}: {e}")
        await message.answer("Sorry, something went wrong while loading your dashboard. Please try again later.") 