"""
Shopify SLF Module
Provides card checking functionality using local checkout.
"""

import json
from typing import Optional, Dict, Any

from BOT.Charge.Shopify.slf.checkout import shopify_checkout
from BOT.Charge.Shopify.tls_session import TLSAsyncSession


def get_site(user_id: str) -> Optional[str]:
    """Get user's saved site from sites.json."""
    try:
        with open("DATA/sites.json", "r", encoding="utf-8") as f:
            sites = json.load(f)
        return sites.get(str(user_id), {}).get("site")
    except Exception:
        return None


async def check_card(user_id: str, cc: str, site: Optional[str] = None) -> str:
    """
    Check a card on user's saved Shopify site.
    
    Args:
        user_id: User ID to look up site
        cc: Card in format cc|mm|yy|cvv
        site: Optional site URL (uses user's saved site if not provided)
    
    Returns:
        Response string (e.g., "ORDER_PLACED", "CARD_DECLINED", "3DS_REQUIRED")
    """
    # Get site if not provided
    if not site:
        site = get_site(user_id)
    
    if not site:
        return "Site Not Found"
    
    try:
        async with TLSAsyncSession(timeout_seconds=90) as session:
            result = await shopify_checkout(site, cc, session)
        
        # Return the response string
        return result.get("response", "UNKNOWN_ERROR")
        
    except Exception as e:
        return f"Error: {str(e)[:50]}"


async def check_card_full(user_id: str, cc: str, site: Optional[str] = None) -> Dict[str, Any]:
    """
    Check a card and return full result dictionary.
    
    Args:
        user_id: User ID to look up site
        cc: Card in format cc|mm|yy|cvv
        site: Optional site URL
    
    Returns:
        Full result dictionary with status, response, gateway, price, etc.
    """
    # Get site if not provided
    if not site:
        site = get_site(user_id)
    
    if not site:
        return {
            "status": "ERROR",
            "response": "Site Not Found",
            "gateway": "Unknown",
            "price": "0.00",
            "time_taken": 0,
            "emoji": "⚠️",
            "is_ccn": False
        }
    
    try:
        async with TLSAsyncSession(timeout_seconds=90) as session:
            return await shopify_checkout(site, cc, session)
    except Exception as e:
        return {
            "status": "ERROR",
            "response": str(e)[:80],
            "gateway": "Unknown",
            "price": "0.00",
            "time_taken": 0,
            "emoji": "⚠️",
            "is_ccn": False
        }
