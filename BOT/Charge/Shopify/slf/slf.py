"""
Shopify SLF Module
Uses the complete autoshopify checkout flow for real card checking.
"""

import json
import os
from typing import Optional, Dict, Any

from BOT.Charge.Shopify.slf.api import autoshopify
from BOT.Charge.Shopify.tls_session import TLSAsyncSession
from BOT.tools.proxy import get_proxy

SITES_PATH = "DATA/sites.json"


def get_site(user_id: str) -> Optional[str]:
    """Get user's saved site from sites.json."""
    try:
        if not os.path.exists(SITES_PATH):
            return None
        with open(SITES_PATH, "r", encoding="utf-8") as f:
            sites = json.load(f)
        return sites.get(str(user_id), {}).get("site")
    except Exception:
        return None


def get_site_info(user_id: str) -> Optional[Dict[str, str]]:
    """Get user's full site info (site + gateway)."""
    try:
        if not os.path.exists(SITES_PATH):
            return None
        with open(SITES_PATH, "r", encoding="utf-8") as f:
            sites = json.load(f)
        return sites.get(str(user_id))
    except Exception:
        return None


async def check_card(user_id: str, cc: str, site: Optional[str] = None) -> str:
    """
    Check a card on user's saved Shopify site.
    Uses the full autoshopify checkout flow for real results.
    
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
        return "SITE_NOT_FOUND"
    
    try:
        async with TLSAsyncSession(timeout_seconds=120) as session:
            result = await autoshopify(site, cc, session)
        
        # Return the response string from the full checkout
        response = result.get("Response", "UNKNOWN_ERROR")
        return response
        
    except Exception as e:
        error_msg = str(e)[:80]
        if "timeout" in error_msg.lower():
            return "TIMEOUT"
        elif "connection" in error_msg.lower():
            return "CONNECTION_ERROR"
        return f"ERROR: {error_msg}"


async def check_card_full(user_id: str, cc: str, site: Optional[str] = None) -> Dict[str, Any]:
    """
    Check a card and return full result dictionary.
    Uses the full autoshopify checkout flow.
    
    Args:
        user_id: User ID to look up site
        cc: Card in format cc|mm|yy|cvv
        site: Optional site URL
    
    Returns:
        Full result dictionary with Response, Status, Gateway, Price, cc
    """
    # Get site if not provided
    if not site:
        site = get_site(user_id)
    
    if not site:
        return {
            "Response": "SITE_NOT_FOUND",
            "Status": False,
            "Gateway": "Unknown",
            "Price": "0.00",
            "cc": cc
        }
    
    try:
        async with TLSAsyncSession(timeout_seconds=120) as session:
            result = await autoshopify(site, cc, session)
        
        # Ensure all required fields are present
        return {
            "Response": result.get("Response", "UNKNOWN_ERROR"),
            "Status": result.get("Status", False),
            "Gateway": result.get("Gateway", "Unknown"),
            "Price": result.get("Price", "0.00"),
            "cc": result.get("cc", cc)
        }
        
    except Exception as e:
        return {
            "Response": str(e)[:80],
            "Status": False,
            "Gateway": "Unknown",
            "Price": "0.00",
            "cc": cc
        }
