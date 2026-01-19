def format_stripe_response(card, mes, ano, cvv, result, timetaken, gateway="Stripe Auth"):
    """
    Format Stripe Auth response for Telegram

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

    status = result.get("status", "error")
    response = result.get("response", "Unknown error")

    # Status emojis
    if status == "approved":
        status_emoji = "✅"
        status_text = "Approved"
    elif status == "declined":
        status_emoji = "❌"
        status_text = "Declined"
    else:
        status_emoji = "⚠️"
        status_text = "Error"

    # Card info (mask most of the card)
    masked_card = f"{card[:6]}{'X' * (len(card) - 10)}{card[-4:]}"

    formatted = f"""<pre>━━━━━ {gateway} ━━━━━</pre>
<b>Card:</b> <code>{fullcc}</code>
<b>Status:</b> <code>{status_text} {status_emoji}</code>
<b>Response:</b> <code>{response}</code>
━━━━━━━━━━━━━━━
<b>⏱️ Time:</b> <code>{timetaken}s</code>
<b>Gateway:</b> <code>{gateway}</code>"""

    return formatted
