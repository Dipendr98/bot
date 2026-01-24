"""
Professional Shopify Response Formatter
Formats Shopify checkout responses with BIN billing information.
"""

import json
from datetime import datetime
from typing import Tuple

# Try to import BIN lookup
try:
    from TOOLS.getbin import get_bin_details
except ImportError:
    def get_bin_details(bin_number):
        return None

try:
    from BOT.helper.start import load_users
except ImportError:
    def load_users():
        return {}


def format_shopify_response(
    cc: str, 
    mes: str, 
    ano: str, 
    cvv: str, 
    raw_response: str, 
    timet: float, 
    profile: str
) -> Tuple[str, str]:
    """
    Format Shopify checkout response for display with professional billing info.
    
    Args:
        cc: Card number
        mes: Month
        ano: Year
        cvv: CVV
        raw_response: Raw response from checkout
        timet: Time taken in seconds
        profile: User profile HTML string
        
    Returns:
        Tuple of (status_flag, formatted_message)
    """
    fullcc = f"{cc}|{mes}|{ano}|{cvv}"
    bin_number = cc[:6]
    
    # Extract user_id from profile
    try:
        user_id = profile.split("id=")[-1].split("'")[0]
    except Exception:
        user_id = None
    
    # Load gateway from sites.json
    try:
        with open("DATA/sites.json", "r", encoding="utf-8") as f:
            sites = json.load(f)
        gateway = sites.get(user_id, {}).get("gate", "Shopify Self Site")
    except Exception:
        gateway = "Shopify Self Site"
    
    # Clean response
    response = str(raw_response).upper() if raw_response else "UNKNOWN"
    
    # Determine status based on response
    if any(x in response for x in ["ORDER_PLACED", "ORDER_CONFIRMED", "CHARGED", "THANK_YOU"]):
        status_flag = "CHARGED 💎"
        header = "CHARGED"
        status_emoji = "💎"
    elif any(x in response for x in [
        "3DS", "AUTHENTICATION", "INCORRECT_CVC", "INVALID_CVC", "INCORRECT_CVV",
        "MISMATCHED", "INCORRECT_ADDRESS", "INCORRECT_ZIP", "INCORRECT_PIN",
        "FRAUD", "INSUFFICIENT_FUNDS", "CARD_DECLINED"
    ]):
        status_flag = "CCN LIVE ✅"
        header = "CCN LIVE"
        status_emoji = "✅"
    elif any(x in response for x in [
        "CAPTCHA", "HCAPTCHA", "RECAPTCHA", "EMPTY", "DEAD", "ERROR",
        "TIMEOUT", "FAILED", "TAX"
    ]):
        status_flag = "ERROR ⚠️"
        header = "ERROR"
        status_emoji = "⚠️"
    else:
        status_flag = "DECLINED ❌"
        header = "DECLINED"
        status_emoji = "❌"
    
    # BIN lookup for professional billing info
    bin_data = get_bin_details(bin_number) if get_bin_details else None
    
    if bin_data:
        vendor = bin_data.get("vendor", "Unknown")
        card_type = bin_data.get("type", "Unknown")
        level = bin_data.get("level", "Unknown")
        bank = bin_data.get("bank", "Unknown")
        country = bin_data.get("country", "Unknown")
        country_flag = bin_data.get("flag", "🏳️")
    else:
        vendor = "Unknown"
        card_type = "Unknown"
        level = "Unknown"
        bank = "Unknown"
        country = "Unknown"
        country_flag = "🏳️"
    
    # Get user plan
    try:
        users = load_users()
        user_data = users.get(user_id, {})
        plan = user_data.get("plan", {}).get("plan", "Free")
        badge = user_data.get("plan", {}).get("badge", "🎟️")
    except Exception:
        plan = "Free"
        badge = "🎟️"
    
    # Current time
    current_time = datetime.now().strftime("%I:%M:%S %p")
    current_date = datetime.now().strftime("%d/%m/%Y")
    
    # Format professional bill response
    result = f"""<b>╔══════════════════════════╗
║     𝐒𝐇𝐎𝐏𝐈𝐅𝐘 𝐂𝐇𝐄𝐂𝐊𝐄𝐑 {status_emoji}     
╚══════════════════════════╝</b>

<b>┌─────── CARD DETAILS ───────┐</b>
│ <b>Card:</b> <code>{fullcc}</code>
│ <b>Status:</b> <code>{status_flag}</code>
│ <b>Response:</b> <code>{response}</code>
<b>└────────────────────────────┘</b>

<b>┌─────── GATEWAY INFO ───────┐</b>
│ <b>Gateway:</b> <code>{gateway}</code>
│ <b>Type:</b> <code>Shopify Checkout</code>
<b>└────────────────────────────┘</b>

<b>┌──────── BIN BILLING ───────┐</b>
│ <b>BIN:</b> <code>{bin_number}</code>
│ <b>Brand:</b> <code>{vendor}</code>
│ <b>Type:</b> <code>{card_type}</code>
│ <b>Level:</b> <code>{level}</code>
│ <b>Bank:</b> <code>{bank}</code>
│ <b>Country:</b> <code>{country}</code> {country_flag}
<b>└────────────────────────────┘</b>

<b>┌──────── CHECK INFO ────────┐</b>
│ <b>Checked By:</b> {profile}
│ <b>Plan:</b> <code>{plan} {badge}</code>
│ <b>Time:</b> <code>{timet}s</code>
│ <b>Proxy:</b> <code>Live ⚡️</code>
<b>└────────────────────────────┘</b>

<b>┌────────── RECEIPT ─────────┐</b>
│ <b>Date:</b> <code>{current_date}</code>
│ <b>Time:</b> <code>{current_time}</code>
│ <b>Dev:</b> <a href="https://t.me/Chr1shtopher">Chr1shtopher</a>
<b>└────────────────────────────┘</b>"""
    
    return status_flag, result
