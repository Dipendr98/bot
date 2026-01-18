import json
import os
from typing import Optional, List

# File to store user custom URLs
URLS_FILE = "FILES/user_autosh_urls.json"

def load_user_urls() -> dict:
    """Load user custom URLs from file"""
    try:
        if os.path.exists(URLS_FILE):
            with open(URLS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {}
    except Exception as e:
        print(f"Error loading user URLs: {e}")
        return {}

def save_user_urls(urls_data: dict):
    """Save user URLs to file"""
    try:
        os.makedirs(os.path.dirname(URLS_FILE), exist_ok=True)
        with open(URLS_FILE, 'w', encoding='utf-8') as f:
            json.dump(urls_data, f, indent=2)
    except Exception as e:
        print(f"Error saving user URLs: {e}")

def set_user_url(user_id: str, url: str) -> tuple[bool, str]:
    """
    Set custom URL for a user

    Args:
        user_id: User ID
        url: URL to set

    Returns:
        (success, message)
    """
    try:
        # Basic URL validation
        url = url.strip()
        if not url.startswith('http://') and not url.startswith('https://'):
            return False, "URL must start with http:// or https://"

        if len(url) < 10:
            return False, "URL is too short"

        # Load existing URLs
        urls_data = load_user_urls()

        # Set user URL
        urls_data[user_id] = url

        # Save
        save_user_urls(urls_data)

        return True, f"Custom URL set successfully: {url}"
    except Exception as e:
        return False, f"Error setting URL: {str(e)}"

def get_user_url(user_id: str) -> Optional[str]:
    """
    Get custom URL for a user

    Args:
        user_id: User ID

    Returns:
        URL or None if not set
    """
    urls_data = load_user_urls()
    return urls_data.get(user_id)

def remove_user_url(user_id: str) -> tuple[bool, str]:
    """
    Remove custom URL for a user

    Args:
        user_id: User ID

    Returns:
        (success, message)
    """
    try:
        urls_data = load_user_urls()

        if user_id in urls_data:
            del urls_data[user_id]
            save_user_urls(urls_data)
            return True, "Custom URL removed successfully"
        else:
            return False, "No custom URL found for your account"
    except Exception as e:
        return False, f"Error removing URL: {str(e)}"

def list_all_custom_urls() -> dict:
    """Get all custom URLs (for admin use)"""
    return load_user_urls()
