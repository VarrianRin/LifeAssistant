import os
import pandas as pd
from typing import Optional, List, Dict, Any
from datetime import datetime

# CSV file paths
DATA_DIR = os.getenv("DATA_DIR", "data")
TASKS_CSV = os.path.join(DATA_DIR, "tasks.csv")
NOTION_CONNECTIONS_CSV = os.path.join(DATA_DIR, "notion_connections.csv")
USERS_CSV = os.path.join(DATA_DIR, "users.csv")
TRACKS_CSV = os.path.join(DATA_DIR, "tracks.csv")

# Ensure data directory exists
os.makedirs(DATA_DIR, exist_ok=True)

def init_csv_files():
    """Initialize all CSV files with proper headers if they don't exist."""
    # Initialize tasks.csv with user_id column
    if not os.path.exists(TASKS_CSV):
        pd.DataFrame(columns=[
            'name', 'sphere_text', 'sphere_page_id', 'start_datetime', 
            'end_datetime', 'type', 'project', 'chatGPT_comment', 'user_id'
        ]).to_csv(TASKS_CSV, index=False)
    else:
        # Add user_id column if it doesn't exist
        df = pd.read_csv(TASKS_CSV)
        if 'user_id' not in df.columns:
            df['user_id'] = None
            df.to_csv(TASKS_CSV, index=False)

    # Initialize notion_connections.csv
    if not os.path.exists(NOTION_CONNECTIONS_CSV):
        pd.DataFrame(columns=[
            'user_id', 'connection_type', 'value'
        ]).to_csv(NOTION_CONNECTIONS_CSV, index=False)

    # Initialize users.csv
    if not os.path.exists(USERS_CSV):
        pd.DataFrame(columns=[
            'user_id', 'login'
        ]).to_csv(USERS_CSV, index=False)

    # Initialize tracks.csv
    if not os.path.exists(TRACKS_CSV):
        pd.DataFrame(columns=[
            'user_id', 'track_type', 'youtube_url', 'local_path'
        ]).to_csv(TRACKS_CSV, index=False)

# User management functions
def add_user(user_id: int, login: str) -> bool:
    """Add or update a user in users.csv."""
    try:
        df = pd.read_csv(USERS_CSV)
        if user_id in df['user_id'].values:
            df.loc[df['user_id'] == user_id, 'login'] = login
        else:
            df = pd.concat([df, pd.DataFrame({'user_id': [user_id], 'login': [login]})], ignore_index=True)
        df.to_csv(USERS_CSV, index=False)
        return True
    except Exception as e:
        print(f"Error adding user: {e}")
        return False

def get_user(user_id: int) -> Optional[Dict[str, Any]]:
    """Get user information from users.csv."""
    try:
        df = pd.read_csv(USERS_CSV)
        user = df[df['user_id'] == user_id]
        return user.to_dict('records')[0] if not user.empty else None
    except Exception as e:
        print(f"Error getting user: {e}")
        return None

# Notion connections management
def save_notion_connection(user_id: int, connection_type: str, value: str) -> bool:
    """Save or update a Notion connection for a user."""
    try:
        df = pd.read_csv(NOTION_CONNECTIONS_CSV)
        mask = (df['user_id'] == user_id) & (df['connection_type'] == connection_type)
        
        if mask.any():
            df.loc[mask, 'value'] = value
        else:
            df = pd.concat([df, pd.DataFrame({
                'user_id': [user_id],
                'connection_type': [connection_type],
                'value': [value]
            })], ignore_index=True)
        
        df.to_csv(NOTION_CONNECTIONS_CSV, index=False)
        return True
    except Exception as e:
        print(f"Error saving Notion connection: {e}")
        return False

def get_notion_connection(user_id: int, connection_type: str) -> Optional[str]:
    """Get a specific Notion connection value for a user."""
    try:
        df = pd.read_csv(NOTION_CONNECTIONS_CSV)
        connection = df[(df['user_id'] == user_id) & (df['connection_type'] == connection_type)]
        return connection['value'].iloc[0] if not connection.empty else None
    except Exception as e:
        print(f"Error getting Notion connection: {e}")
        return None

# Tasks management
def save_task(task_data: Dict[str, Any], user_id: int) -> bool:
    """Save a single task with user_id to tasks.csv."""
    try:
        task_data['user_id'] = user_id
        df = pd.DataFrame([task_data])
        
        if os.path.exists(TASKS_CSV):
            existing_df = pd.read_csv(TASKS_CSV)
            df = pd.concat([existing_df, df], ignore_index=True)
        
        df.to_csv(TASKS_CSV, index=False)
        return True
    except Exception as e:
        print(f"Error saving task: {e}")
        return False

def save_tasks(tasks_data: List[Dict[str, Any]], user_id: int) -> bool:
    """Save multiple tasks with user_id to tasks.csv."""
    try:
        for task in tasks_data:
            task['user_id'] = user_id
        
        df = pd.DataFrame(tasks_data)
        
        if os.path.exists(TASKS_CSV):
            existing_df = pd.read_csv(TASKS_CSV)
            df = pd.concat([existing_df, df], ignore_index=True)
        
        df.to_csv(TASKS_CSV, index=False)
        return True
    except Exception as e:
        print(f"Error saving tasks: {e}")
        return False

def get_user_tasks(user_id: int) -> List[Dict[str, Any]]:
    """Get all tasks for a specific user."""
    try:
        df = pd.read_csv(TASKS_CSV)
        user_tasks = df[df['user_id'] == user_id]
        return user_tasks.to_dict('records')
    except Exception as e:
        print(f"Error getting user tasks: {e}")
        return []

# Tracks management
def save_track(user_id: int, track_type: str, youtube_url: str, local_path: str) -> bool:
    """Save a track entry to tracks.csv."""
    try:
        # Ensure local_path is a string
        local_path = str(local_path) if local_path else ""
        
        df = pd.read_csv(TRACKS_CSV)
        new_track = pd.DataFrame({
            'user_id': [user_id],
            'track_type': [track_type],
            'youtube_url': [youtube_url],
            'local_path': [local_path]
        })
        df = pd.concat([df, new_track], ignore_index=True)
        df.to_csv(TRACKS_CSV, index=False)
        return True
    except Exception as e:
        print(f"Error saving track: {e}")
        return False

def get_user_tracks(user_id: int, track_type: Optional[str] = None) -> List[Dict[str, Any]]:
    """Get tracks for a user, optionally filtered by type."""
    try:
        df = pd.read_csv(TRACKS_CSV)
        # Ensure local_path is string type
        df['local_path'] = df['local_path'].astype(str)
        # Replace 'nan' with empty string
        df['local_path'] = df['local_path'].replace('nan', '')
        
        mask = df['user_id'] == user_id
        if track_type:
            mask &= df['track_type'] == track_type
        tracks = df[mask]
        return tracks.to_dict('records')
    except Exception as e:
        print(f"Error getting user tracks: {e}")
        return []

# Initialize all CSV files when module is imported
init_csv_files() 