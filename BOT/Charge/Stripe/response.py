"""
Professional Stripe Charge Response Formatter
Formats Stripe checkout responses with BIN billing information.
"""

from datetime import datetime
from time import time

# Try to import BIN lookup
try:
    from TOOLS.getbin import get_bin_details
except ImportError:
    def get_bin_details(bin_number):
        return None


def format_stripe_charge_response(card_data: str, result: dict, start_time: float, user_info: dict = None) -> str:
    """
    Format the Stripe $20 Charge response with professional billing info.

    Args:
        card_data: Full card details (cc|mm|yy|cvv)
        result: Result dictionary from check_stripe_charge
        start_time: Start time of the check
        user_info: User information dict

    Returns:
        Formatted HTML message string
    """
    end_time = time()
    time_taken = round(end_time - start_time, 2)

    # Parse card data
    card_parts = card_data.split('|')
    card_number = card_parts[0] if len(card_parts) > 0 else "Unknown"
    mm = card_parts[1] if len(card_parts) > 1 else "00"
    yy = card_parts[2] if len(card_parts) > 2 else "00"
    cvv = card_parts[3] if len(card_parts) > 3 else "000"
    
    bin_number = card_number[:6]
    last4 = card_number[-4:]

    # Determine status emoji and message
    status = result.get("status", "error")
    message = result.get("response", "UNKNOWN_ERROR")

    if status == "approved":
        if "PAYMENT_SUCCESSFUL" in message or "CHARGED" in message:
            status_emoji = "💎"
            status_text = "CHARGED"
            header = "CHARGED"
        else:
            status_emoji = "✅"
            status_text = "CCN LIVE"
            header = "CCN LIVE"
    elif status == "declined":
        status_emoji = "❌"
        status_text = "DECLINED"
        header = "DECLINED"
    else:
        status_emoji = "⚠️"
        status_text = "ERROR"
        header = "ERROR"

    # Get user info
    plan = user_info.get("plan", "Free") if user_info else "Free"
    badge = user_info.get("badge", "🎟️") if user_info else "🎟️"
    checked_by = user_info.get("checked_by", "Unknown") if user_info else "Unknown"

    # Current time
    current_time = datetime.now().strftime("%I:%M:%S %p")
    current_date = datetime.now().strftime("%d/%m/%Y")

    # BIN lookup for professional billing info
    bin_data = get_bin_details(bin_number) if get_bin_details else None
    
    if bin_data:
        vendor = bin_data.get('vendor', 'Unknown')
        card_type = bin_data.get('type', 'Unknown')
        level = bin_data.get('level', 'Unknown')
        bank = bin_data.get('bank', 'Unknown')
        country = bin_data.get('country', 'Unknown')
        country_flag = bin_data.get('flag', '🏳️')
    else:
        vendor = "Unknown"
        card_type = "Unknown"
        level = "Unknown"
        bank = "Unknown"
        country = "Unknown"
        country_flag = "🏳️"

    # Format professional bill response
    response = f"""<b>╔══════════════════════════╗
║     𝐒𝐓𝐑𝐈𝐏𝐄 𝐂𝐇𝐀𝐑𝐆𝐄 {status_emoji}     
╚══════════════════════════╝</b>

<b>┌─────── CARD DETAILS ───────┐</b>
│ <b>Card:</b> <code>{card_data}</code>
│ <b>Status:</b> <code>{status_text} {status_emoji}</code>
│ <b>Response:</b> <code>{message}</code>
<b>└────────────────────────────┘</b>

<b>┌─────── GATEWAY INFO ───────┐</b>
│ <b>Gateway:</b> <code>Stripe Balliante</code>
│ <b>Amount:</b> <code>$20.00 USD</code>
│ <b>Merchant:</b> <code>Balliante.com</code>
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
│ <b>Checked By:</b> {checked_by}
│ <b>Plan:</b> <code>{plan} {badge}</code>
│ <b>Time:</b> <code>{time_taken}s</code>
│ <b>Proxy:</b> <code>Live ⚡️</code>
<b>└────────────────────────────┘</b>

<b>┌────────── RECEIPT ─────────┐</b>
│ <b>Date:</b> <code>{current_date}</code>
│ <b>Time:</b> <code>{current_time}</code>
│ <b>Dev:</b> <a href="https://t.me/Chr1shtopher">Chr1shtopher</a>
<b>└────────────────────────────┘</b>"""

    return response
