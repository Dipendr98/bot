"""
Shopify Response Formatter
Professional response formatting for Shopify card checking results.
"""

import json
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
    Format Shopify checkout response for display.
    
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
        status_flag = "Charged 💎"
        header = "CHARGED"
    elif any(x in response for x in [
        "3DS", "AUTHENTICATION", "INCORRECT_CVC", "INVALID_CVC", "INCORRECT_CVV",
        "MISMATCHED", "INCORRECT_ADDRESS", "INCORRECT_ZIP", "INCORRECT_PIN",
        "FRAUD", "INSUFFICIENT_FUNDS", "CARD_DECLINED"
    ]):
        status_flag = "Approved ✅"
        header = "CCN LIVE"
    elif any(x in response for x in [
        "CAPTCHA", "HCAPTCHA", "RECAPTCHA", "EMPTY", "DEAD", "ERROR",
        "TIMEOUT", "FAILED", "TAX"
    ]):
        status_flag = "Error ⚠️"
        header = "ERROR"
    else:
        status_flag = "Declined ❌"
        header = "DECLINED"
    
    # BIN lookup
    bin_data = get_bin_details(cc[:6]) if get_bin_details else None
    if bin_data:
        bin_info = {
            "bin": bin_data.get("bin", cc[:6]),
            "country": bin_data.get("country", "Unknown"),
            "flag": bin_data.get("flag", "🏳️"),
            "vendor": bin_data.get("vendor", "Unknown"),
            "type": bin_data.get("type", "Unknown"),
            "level": bin_data.get("level", "Unknown"),
            "bank": bin_data.get("bank", "Unknown")
        }
    else:
        bin_info = {
            "bin": cc[:6],
            "country": "Unknown",
            "flag": "🏳️",
            "vendor": "Unknown",
            "type": "Unknown",
            "level": "Unknown",
            "bank": "Unknown"
        }
    
    # Get user plan
    try:
        users = load_users()
        user_data = users.get(user_id, {})
        plan = user_data.get("plan", {}).get("plan", "Free")
        badge = user_data.get("plan", {}).get("badge", "🎟️")
    except Exception:
        plan = "Free"
        badge = "🎟️"
    
    # Format response message
    result = f"""<b>[#Shopify] | {header}</b> ✦
━━━━━━━━━━━━━━━
<b>[•] Card:</b> <code>{fullcc}</code>
<b>[•] Gateway:</b> <code>{gateway}</code>
<b>[•] Status:</b> <code>{status_flag}</code>
<b>[•] Response:</b> <code>{response}</code>
━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━
<b>[+] BIN:</b> <code>{bin_info['bin']}</code>
<b>[+] Info:</b> <code>{bin_info['vendor']} - {bin_info['type']} - {bin_info['level']}</code>
<b>[+] Bank:</b> <code>{bin_info['bank']}</code> 🏦
<b>[+] Country:</b> <code>{bin_info['country']}</code> {bin_info['flag']}
━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━
<b>[ﾒ] Checked By:</b> {profile} [<code>{plan} {badge}</code>]
<b>[ϟ] Dev:</b> <a href="https://t.me/Chr1shtopher">Chr1shtopher</a>
━━━━━━━━━━━━━━━
<b>[ﾒ] Time:</b> <code>{timet}s</code> | <b>Proxy:</b> <code>Live ⚡️</code>"""
    
    return status_flag, result
