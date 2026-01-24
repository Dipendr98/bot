"""
Professional Stripe Auth Response Formatter
Formats Stripe authentication responses with BIN billing information.
"""

from datetime import datetime

# Try to import BIN lookup
try:
    from TOOLS.getbin import get_bin_details
except ImportError:
    def get_bin_details(bin_number):
        return None


def format_stripe_response(card, mes, ano, cvv, result, timetaken, gateway="Stripe Auth"):
    """
    Format Stripe Auth response for Telegram with professional billing info.

    Args:
        card: Card number
        mes: Expiry month
        ano: Expiry year
        cvv: CVV code
        result: Result dict from stripe auth
        timetaken: Time taken in seconds
        gateway: Gateway name

    Returns:
        Formatted string for Telegram
    """
    fullcc = f"{card}|{mes}|{ano}|{cvv}"
    bin_number = card[:6]

    status = result.get("status", "error")
    response = result.get("response", "Unknown error")

    # Status emojis and text
    if status == "approved":
        if "AUTH_SUCCESS" in response or "CARD_ADDED" in response:
            status_emoji = "✅"
            status_text = "APPROVED"
        else:
            status_emoji = "✅"
            status_text = "CCN LIVE"
    elif status == "declined":
        status_emoji = "❌"
        status_text = "DECLINED"
    else:
        status_emoji = "⚠️"
        status_text = "ERROR"

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
    formatted = f"""<b>╔══════════════════════════╗
║     𝐒𝐓𝐑𝐈𝐏𝐄 𝐀𝐔𝐓𝐇 {status_emoji}     
╚══════════════════════════╝</b>

<b>┌─────── CARD DETAILS ───────┐</b>
│ <b>Card:</b> <code>{fullcc}</code>
│ <b>Status:</b> <code>{status_text} {status_emoji}</code>
│ <b>Response:</b> <code>{response}</code>
<b>└────────────────────────────┘</b>

<b>┌─────── GATEWAY INFO ───────┐</b>
│ <b>Gateway:</b> <code>{gateway}</code>
│ <b>Amount:</b> <code>$0.00 (Auth)</code>
│ <b>Type:</b> <code>Card Verification</code>
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
│ <b>Time:</b> <code>{timetaken}s</code>
│ <b>Proxy:</b> <code>Live ⚡️</code>
<b>└────────────────────────────┘</b>

<b>┌────────── RECEIPT ─────────┐</b>
│ <b>Date:</b> <code>{current_date}</code>
│ <b>Time:</b> <code>{current_time}</code>
│ <b>Dev:</b> <a href="https://t.me/Chr1shtopher">Chr1shtopher</a>
<b>└────────────────────────────┘</b>"""

    return formatted
