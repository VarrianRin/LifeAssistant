import logging
from aiogram import Router, types, F
from aiogram.filters import Command
from notion_client import Client
from bot.csv_db import save_notion_connection, get_notion_connection

logger = logging.getLogger(__name__)
router = Router()

async def verify_notion_token(token: str) -> bool:
    """Verify if the Notion token is valid."""
    try:
        client = Client(auth=token)
        # Try to list users to verify token
        client.users.me()
        return True
    except Exception as e:
        logger.error(f"Error verifying Notion token: {e}")
        return False

async def verify_notion_database(token: str, database_id: str) -> bool:
    """Verify if the database exists and has required properties."""
    try:
        client = Client(auth=token)
        database = client.databases.retrieve(database_id=database_id)
        
        # Check required properties for main database
        required_props = {"Name", "Sphere", "Start Date", "End Date", "type", "Project", "ChatGPT_comment"}
        db_props = set(database["properties"].keys())
        
        return required_props.issubset(db_props)
    except Exception as e:
        logger.error(f"Error verifying Notion database: {e}")
        return False

async def verify_category_database(token: str, database_id: str) -> bool:
    """Verify if the category database exists and has Description field."""
    try:
        client = Client(auth=token)
        database = client.databases.retrieve(database_id=database_id)
        
        # Check if Description field exists
        return "Description" in database["properties"]
    except Exception as e:
        logger.error(f"Error verifying category database: {e}")
        return False

@router.message(Command("connect_notion"))
async def cmd_connect_notion(message: types.Message):
    """Handle /connect_notion command to save Notion token."""
    try:
        # Get token from command
        args = message.text.split()
        if len(args) != 2:
            await message.answer(
                "❌ Invalid format. Please use:\n"
                "/connect_notion [your_notion_token]"
            )
            return
        
        token = args[1]
        user_id = message.from_user.id
        
        # Verify token
        if not await verify_notion_token(token):
            await message.answer("❌ Invalid Notion token. Please check and try again.")
            return
        
        # Save token
        if save_notion_connection(user_id, "NOTION_TOKEN", token):
            await message.answer("✅ Notion token successfully connected!")
        else:
            await message.answer("❌ Failed to save Notion token. Please try again.")
            
    except Exception as e:
        logger.error(f"Error connecting Notion token: {e}")
        await message.answer("❌ Something went wrong. Please try again later.")

@router.message(Command("connect_notion_table"))
async def cmd_connect_notion_table(message: types.Message):
    """Handle /connect_notion_table command to save main database ID."""
    try:
        # Get database ID from command
        args = message.text.split()
        if len(args) != 2:
            await message.answer(
                "❌ Invalid format. Please use:\n"
                "/connect_notion_table [database_id]"
            )
            return
        
        database_id = args[1]
        user_id = message.from_user.id
        
        # Get user's token
        token = get_notion_connection(user_id, "NOTION_TOKEN")
        if not token:
            await message.answer("❌ Please connect your Notion token first using /connect_notion")
            return
        
        # Verify database
        if not await verify_notion_database(token, database_id):
            await message.answer(
                "❌ Invalid database or missing required properties.\n"
                "Required properties: Name, Sphere, Start Date, End Date, type, Project, ChatGPT_comment"
            )
            return
        
        # Save database ID
        if save_notion_connection(user_id, "NOTION_MAIN_DATABASE_ID", database_id):
            await message.answer("✅ Main Notion database successfully connected!")
        else:
            await message.answer("❌ Failed to save database ID. Please try again.")
            
    except Exception as e:
        logger.error(f"Error connecting Notion database: {e}")
        await message.answer("❌ Something went wrong. Please try again later.")

@router.message(Command("connect_notion_category_table"))
async def cmd_connect_notion_category_table(message: types.Message):
    """Handle /connect_notion_category_table command to save category database ID."""
    try:
        # Get arguments from command
        args = message.text.split()
        if len(args) != 3:
            await message.answer(
                "❌ Invalid format. Please use:\n"
                "/connect_notion_category_table [1] [database_id]"
            )
            return
        
        category_num = args[1]
        if category_num != "1":  # Only supporting category 1 for now
            await message.answer("❌ Only category 1 is supported at the moment.")
            return
        
        database_id = args[2]
        user_id = message.from_user.id
        
        # Get user's token
        token = get_notion_connection(user_id, "NOTION_TOKEN")
        if not token:
            await message.answer("❌ Please connect your Notion token first using /connect_notion")
            return
        
        # Verify database
        if not await verify_category_database(token, database_id):
            await message.answer("❌ Invalid database or missing Description field.")
            return
        
        # Save database ID
        if save_notion_connection(user_id, "NOTION_DATABASE_ID_1", database_id):
            await message.answer("✅ Category database successfully connected!")
        else:
            await message.answer("❌ Failed to save database ID. Please try again.")
            
    except Exception as e:
        logger.error(f"Error connecting category database: {e}")
        await message.answer("❌ Something went wrong. Please try again later.") 