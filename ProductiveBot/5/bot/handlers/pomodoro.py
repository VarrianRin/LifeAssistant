import os
import logging
import asyncio
from datetime import datetime, timedelta
from typing import Optional, Dict
from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from bot.csv_db import get_user_tracks

logger = logging.getLogger(__name__)
router = Router()

# Store active timers
active_timers: Dict[int, asyncio.Task] = {}

class PomodoroState(StatesGroup):
    """States for pomodoro timer."""
    waiting_for_rest = State()

async def format_time_left(seconds: int) -> str:
    """Format remaining time in a user-friendly way."""
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    if hours > 0:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"

async def send_track_info(message: types.Message, track_type: str = "pomodoro"):
    """Send available tracks to user."""
    tracks = get_user_tracks(message.from_user.id, track_type)
    if not tracks:
        await message.answer(
            "🎵 No tracks available for this session.\n"
            "Use /add_music [youtube_link] to add some tracks!"
        )
        return
    
    # Group tracks by availability (downloaded vs youtube only)
    downloaded = []
    youtube_only = []
    
    for track in tracks:
        local_path = str(track.get('local_path', '')).strip()
        if local_path and os.path.exists(local_path):
            downloaded.append(f"• {os.path.basename(local_path)}")
        else:
            youtube_url = track.get('youtube_url', '')
            if youtube_url:
                youtube_only.append(f"• {youtube_url}")
    
    response = ["🎵 Available tracks for this session:"]
    
    if downloaded:
        response.append("\n📥 Downloaded tracks:")
        response.extend(downloaded)
    
    if youtube_only:
        response.append("\n🔗 YouTube links:")
        response.extend(youtube_only)
    
    await message.answer("\n".join(response))

async def notify_time_left(message: types.Message, seconds_left: int, phase: str):
    """Send notification about remaining time."""
    time_str = await format_time_left(seconds_left)
    await message.answer(f"⏰ {phase.capitalize()} time left: {time_str}")

async def run_timer(
    message: types.Message,
    duration: int,
    phase: str,
    state: Optional[FSMContext] = None
) -> bool:
    """Run pomodoro timer with notifications."""
    try:
        # Send initial notification
        await message.answer(f"⏳ Starting {phase} timer for {await format_time_left(duration)}")
        
        # Send available tracks
        await send_track_info(message)
        
        # Calculate notification intervals
        total_seconds = duration
        last_notification = total_seconds
        
        while total_seconds > 0:
            # Sleep for 1 second
            await asyncio.sleep(1)
            total_seconds -= 1
            
            # Send notification every 10 minutes
            if last_notification - total_seconds >= 600:  # 10 minutes
                await notify_time_left(message, total_seconds, phase)
                last_notification = total_seconds
        
        # Timer finished
        if phase == "work":
            await message.answer(
                "⏰ Work time is over! Time to rest.\n"
                "Would you like to start rest timer? (Yes/No)"
            )
            if state:
                await state.set_state(PomodoroState.waiting_for_rest)
        else:
            await message.answer(
                "✅ Pomodoro session completed!\n"
                "To start a new session, use /pomodoro [work_time] [rest_time]"
            )
            if state:
                await state.clear()
        
        return True
        
    except asyncio.CancelledError:
        await message.answer("⏹ Timer stopped.")
        if state:
            await state.clear()
        return False
    except Exception as e:
        logger.error(f"Error in pomodoro timer: {e}")
        await message.answer("❌ Something went wrong with the timer. Please try again.")
        if state:
            await state.clear()
        return False

@router.message(Command("pomodoro"))
async def cmd_pomodoro(message: types.Message, state: FSMContext):
    """Handle /pomodoro command to start a pomodoro session."""
    try:
        # Get arguments
        args = message.text.split()
        if len(args) != 3:
            await message.answer(
                "❌ Invalid format. Please use:\n"
                "/pomodoro [work_time] [rest_time]\n"
                "Times should be in minutes (e.g., 25 5)"
            )
            return
        
        # Parse times
        try:
            work_time = int(args[1])
            rest_time = int(args[2])
            
            if work_time <= 0 or rest_time <= 0:
                raise ValueError("Times must be positive")
            
            # Convert to seconds
            work_seconds = work_time * 60
            rest_seconds = rest_time * 60
            
        except ValueError as e:
            await message.answer(f"❌ Invalid time format: {e}")
            return
        
        # Check if user already has an active timer
        user_id = message.from_user.id
        if user_id in active_timers and not active_timers[user_id].done():
            await message.answer("❌ You already have an active timer. Please wait for it to finish.")
            return
        
        # Start work timer
        timer_task = asyncio.create_task(
            run_timer(message, work_seconds, "work", state)
        )
        active_timers[user_id] = timer_task
        
    except Exception as e:
        logger.error(f"Error starting pomodoro: {e}")
        await message.answer("❌ Something went wrong. Please try again.")

@router.message(PomodoroState.waiting_for_rest, F.text.lower().in_({"yes", "no"}))
async def handle_rest_confirmation(message: types.Message, state: FSMContext):
    """Handle user's response about starting rest timer."""
    try:
        user_id = message.from_user.id
        
        if message.text.lower() == "yes":
            # Get rest time from command arguments
            args = message.text.split()
            rest_time = int(args[2]) * 60  # Convert to seconds
            
            # Start rest timer
            timer_task = asyncio.create_task(
                run_timer(message, rest_time, "rest", state)
            )
            active_timers[user_id] = timer_task
        else:
            await message.answer(
                "✅ Pomodoro session completed!\n"
                "To start a new session, use /pomodoro [work_time] [rest_time]"
            )
            await state.clear()
            
    except Exception as e:
        logger.error(f"Error handling rest confirmation: {e}")
        await message.answer("❌ Something went wrong. Please try again.")
        await state.clear()

@router.message(Command("stop"))
async def cmd_stop(message: types.Message, state: FSMContext):
    """Handle /stop command to stop active timer."""
    try:
        user_id = message.from_user.id
        if user_id in active_timers and not active_timers[user_id].done():
            active_timers[user_id].cancel()
            await message.answer("⏹ Timer stopped.")
            await state.clear()
        else:
            await message.answer("❌ No active timer to stop.")
            
    except Exception as e:
        logger.error(f"Error stopping timer: {e}")
        await message.answer("❌ Something went wrong while stopping the timer.") 