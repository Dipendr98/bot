"""
Professional Shopify Single Card Checker
Handles /sh and /slf commands for checking cards on user's saved site.
Uses the complete autoshopify checkout flow for real results.
Includes professional BIN billing information in responses.
"""

import re
import json
import os
from time import time
from datetime import datetime

from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.enums import ParseMode, ChatType

from BOT.helper.start import load_users
from BOT.helper.antispam import can_run_command
from BOT.gc.credit import has_credits, deduct_credit
from BOT.Charge.Shopify.slf.api import autoshopify
from BOT.Charge.Shopify.tls_session import TLSAsyncSession

# Try to import BIN lookup
try:
    from TOOLS.getbin import get_bin_details
except ImportError:
    def get_bin_details(bin_number):
        return None

SITES_PATH = "DATA/sites.json"
TXT_SITES_PATH = "DATA/txtsite.json"

# Private commands that should only work in DM
PRIVATE_ONLY_COMMANDS = ["sh", "slf", "addurl", "slfurl", "mysite", "delsite", "txturl", "txtls", "rurl"]


def extract_card(text: str):
    """Extract card details from text in format cc|mm|yy|cvv."""
    match = re.search(r'(\d{12,19})\|(\d{1,2})\|(\d{2,4})\|(\d{3,4})', text)
    if match:
        return match.groups()
    return None


def get_user_site(user_id: str):
    """Get user's saved site from sites.json or txtsite.json."""
    try:
        # First check sites.json
        if os.path.exists(SITES_PATH):
            with open(SITES_PATH, "r", encoding="utf-8") as f:
                sites = json.load(f)
            site_info = sites.get(str(user_id))
            if site_info:
                return site_info
        
        # Fallback to txtsite.json
        if os.path.exists(TXT_SITES_PATH):
            with open(TXT_SITES_PATH, "r", encoding="utf-8") as f:
                txt_sites = json.load(f)
            user_txt_sites = txt_sites.get(str(user_id), [])
            if user_txt_sites and len(user_txt_sites) > 0:
                first_site = user_txt_sites[0]
                return {
                    "site": first_site.get("site"),
                    "gate": first_site.get("gate", "Shopify")
                }
        
        return None
    except Exception:
        return None


def determine_status(response: str) -> tuple:
    """
    Determine status category from response.
    Returns (status_text, emoji, header, is_live)
    """
    response_upper = str(response).upper()
    
    # Charged/Success
    if any(x in response_upper for x in ["ORDER_PLACED", "ORDER_CONFIRMED", "THANK_YOU", "SUCCESS", "CHARGED"]):
        return "CHARGED 💎", "💎", "CHARGED", True
    
    # CCN/Live (CVV/Address issues but card is valid)
    if any(x in response_upper for x in [
        "3DS", "AUTHENTICATION", "INCORRECT_CVC", "INVALID_CVC", 
        "MISMATCHED", "INCORRECT_ADDRESS", "INCORRECT_ZIP", "INCORRECT_PIN",
        "FRAUD", "INSUFFICIENT_FUNDS", "CVV"
    ]):
        return "CCN LIVE ✅", "✅", "CCN LIVE", True
    
    # Declined
    if any(x in response_upper for x in [
        "DECLINED", "CARD_DECLINED", "GENERIC_ERROR", "INCORRECT_NUMBER",
        "INVALID_NUMBER", "EXPIRED", "NOT_SUPPORTED", "LOST", "STOLEN"
    ]):
        return "DECLINED ❌", "❌", "DECLINED", False
    
    # Errors
    if any(x in response_upper for x in ["ERROR", "TIMEOUT", "CAPTCHA", "EMPTY", "DEAD", "TAX"]):
        return "ERROR ⚠️", "⚠️", "ERROR", False
    
    return "UNKNOWN ❓", "❓", "RESULT", False


def format_bill_response(fullcc: str, result: dict, user_info: dict, time_taken: float) -> str:
    """
    Format the checkout response professionally with BIN billing information.
    Shows a professional 'bill' style output.
    """
    parts = fullcc.split("|")
    cc = parts[0] if len(parts) > 0 else "Unknown"
    mm = parts[1] if len(parts) > 1 else "00"
    yy = parts[2] if len(parts) > 2 else "00"
    cvv = parts[3] if len(parts) > 3 else "000"
    
    response = result.get("Response", "UNKNOWN")
    gateway = result.get("Gateway", "Unknown")
    price = result.get("Price", "0.00")
    
    status_text, emoji, header, is_live = determine_status(response)
    
    # BIN lookup for professional billing info
    bin_data = get_bin_details(cc[:6]) if get_bin_details else None
    
    if bin_data:
        bin_number = bin_data.get('bin', cc[:6])
        vendor = bin_data.get('vendor', 'Unknown')
        card_type = bin_data.get('type', 'Unknown')
        level = bin_data.get('level', 'Unknown')
        bank = bin_data.get('bank', 'Unknown')
        country = bin_data.get('country', 'Unknown')
        country_flag = bin_data.get('flag', '🏳️')
    else:
        bin_number = cc[:6]
        vendor = "Unknown"
        card_type = "Unknown"
        level = "Unknown"
        bank = "Unknown"
        country = "Unknown"
        country_flag = "🏳️"
    
    # Get current time
    current_time = datetime.now().strftime("%I:%M:%S %p")
    current_date = datetime.now().strftime("%d/%m/%Y")
    
    # Format card display (mask middle digits for security appearance)
    card_display = f"{cc[:6]}****{cc[-4:]}" if len(cc) > 10 else cc
    
    # Build professional bill response
    bill = f"""<b>╔══════════════════════════╗
║     𝐒𝐇𝐎𝐏𝐈𝐅𝐘 𝐂𝐇𝐄𝐂𝐊𝐄𝐑 {emoji}     
╚══════════════════════════╝</b>

<b>┌─────── CARD DETAILS ───────┐</b>
│ <b>Card:</b> <code>{fullcc}</code>
│ <b>Status:</b> <code>{status_text}</code>
│ <b>Response:</b> <code>{response}</code>
<b>└────────────────────────────┘</b>

<b>┌─────── GATEWAY INFO ───────┐</b>
│ <b>Gateway:</b> <code>Shopify {gateway}</code>
│ <b>Amount:</b> <code>${price} USD</code>
│ <b>Merchant:</b> <code>Self Site</code>
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
│ <b>Checked By:</b> {user_info['profile']}
│ <b>Plan:</b> <code>{user_info['plan']} {user_info['badge']}</code>
│ <b>Time:</b> <code>{time_taken}s</code>
│ <b>Proxy:</b> <code>Live ⚡️</code>
<b>└────────────────────────────┘</b>

<b>┌────────── RECEIPT ─────────┐</b>
│ <b>Date:</b> <code>{current_date}</code>
│ <b>Time:</b> <code>{current_time}</code>
│ <b>Dev:</b> <a href="https://t.me/Chr1shtopher">Chr1shtopher</a>
<b>└────────────────────────────┘</b>"""
    
    return bill


async def check_group_command(message: Message) -> bool:
    """
    Check if command is used in group and guide user to use in private.
    Returns True if command should continue, False if it was blocked.
    """
    if message.chat.type in [ChatType.GROUP, ChatType.SUPERGROUP]:
        # Extract command name
        command = message.text.split()[0].replace("/", "").replace(".", "").replace("$", "").lower()
        
        if command in PRIVATE_ONLY_COMMANDS:
            await message.reply(
                f"""<pre>🔒 Private Command</pre>
━━━━━━━━━━━━━━━
<b>This command only works in private chat.</b>

<b>How to use:</b>
1️⃣ Click the button below to open private chat
2️⃣ Use <code>/{command}</code> command there

<b>Why private?</b>
• 🔐 Protects your card data
• ⚡ Faster response times
• 📊 Personal site management
━━━━━━━━━━━━━━━
<i>Your data security is our priority!</i>""",
                reply_to_message_id=message.id,
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📱 Open Private Chat", url="https://t.me/YOUR_BOT_USERNAME")],
                    [InlineKeyboardButton("📖 Help", callback_data="show_help")]
                ])
            )
            return False
    return True


@Client.on_message(filters.command(["sh", "slf"]) | filters.regex(r"^\.sh(\s|$)") | filters.regex(r"^\.slf(\s|$)"))
async def handle_sh_command(client: Client, message: Message):
    """
    Handle /sh and /slf commands for Shopify card checking.
    Uses the complete autoshopify checkout flow.
    """
    try:
        if not message.from_user:
            return
        
        user_id = str(message.from_user.id)
        users = load_users()
        
        # Check registration
        if user_id not in users:
            return await message.reply(
                """<pre>🚫 Access Denied</pre>
━━━━━━━━━━━━━━━
<b>You must register first!</b>

Use <code>/register</code> to create your account.
━━━━━━━━━━━━━━━""",
                reply_to_message_id=message.id,
                parse_mode=ParseMode.HTML
            )
        
        # Check if command is used in group
        if not await check_group_command(message):
            return
        
        # Check credits
        if not has_credits(user_id):
            return await message.reply(
                """<pre>💳 Insufficient Credits</pre>
━━━━━━━━━━━━━━━
<b>You have no credits remaining.</b>

Use <code>/buy</code> to purchase credits.
━━━━━━━━━━━━━━━""",
                reply_to_message_id=message.id,
                parse_mode=ParseMode.HTML
            )
        
        # Get user's site
        user_site_info = get_user_site(user_id)
        if not user_site_info:
            return await message.reply(
                """<pre>⚠️ No Site Found</pre>
━━━━━━━━━━━━━━━
<b>You haven't added a Shopify site yet!</b>

<b>Add a site first:</b>
<code>/addurl https://store.com</code>

<b>Or use multiple sites:</b>
<code>/txturl site1.com site2.com</code>
━━━━━━━━━━━━━━━""",
                reply_to_message_id=message.id,
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📖 How to Add Site", callback_data="help_addurl")]
                ])
            )
        
        # Extract card
        target_text = None
        if message.reply_to_message and message.reply_to_message.text:
            target_text = message.reply_to_message.text
        elif len(message.text.split(maxsplit=1)) > 1:
            target_text = message.text.split(maxsplit=1)[1]
        
        if not target_text:
            return await message.reply(
                """<pre>❌ Card Not Found</pre>
━━━━━━━━━━━━━━━
<b>No card detected in your input!</b>

<b>Usage:</b> <code>/sh cc|mm|yy|cvv</code>
<b>Example:</b> <code>/sh 4111111111111111|12|25|123</code>

<b>Or reply to a message containing a card.</b>
━━━━━━━━━━━━━━━""",
                reply_to_message_id=message.id,
                parse_mode=ParseMode.HTML
            )
        
        extracted = extract_card(target_text)
        if not extracted:
            return await message.reply(
                """<pre>❌ Invalid Format</pre>
━━━━━━━━━━━━━━━
<b>Card format is incorrect!</b>

<b>Correct Format:</b>
<code>cc|mm|yy|cvv</code> or <code>cc|mm|yyyy|cvv</code>

<b>Example:</b>
<code>/sh 4111111111111111|12|25|123</code>
━━━━━━━━━━━━━━━""",
                reply_to_message_id=message.id,
                parse_mode=ParseMode.HTML
            )
        
        # Antispam check
        allowed, wait_time = can_run_command(user_id, users)
        if not allowed:
            return await message.reply(
                f"""<pre>⏳ Antispam Active</pre>
━━━━━━━━━━━━━━━
<b>Please wait before checking again.</b>

<b>Try again in:</b> <code>{wait_time}s</code>

<i>Upgrade your plan to reduce wait time!</i>
━━━━━━━━━━━━━━━""",
                reply_to_message_id=message.id,
                parse_mode=ParseMode.HTML
            )
        
        # Prepare card and site
        card_num, mm, yy, cvv = extracted
        fullcc = f"{card_num}|{mm}|{yy}|{cvv}"
        site = user_site_info['site']
        gate = user_site_info.get('gate', 'Shopify')
        
        # Get user info
        user_data = users.get(user_id, {})
        plan = user_data.get("plan", {}).get("plan", "Free")
        badge = user_data.get("plan", {}).get("badge", "🎟️")
        profile = f"<a href='tg://user?id={user_id}'>{message.from_user.first_name}</a>"
        
        user_info = {"profile": profile, "plan": plan, "badge": badge}
        
        start_time = time()
        
        # Show processing message
        loading_msg = await message.reply(
            f"""<pre>🔄 Processing...</pre>
━━━━━━━━━━━━━━━
<b>Card:</b> <code>{fullcc}</code>
<b>Gate:</b> <code>{gate}</code>
<b>Status:</b> <i>Checking checkout...</i>
━━━━━━━━━━━━━━━""",
            reply_to_message_id=message.id,
            parse_mode=ParseMode.HTML
        )
        
        # Perform checkout using autoshopify
        try:
            async with TLSAsyncSession(timeout_seconds=120) as session:
                result = await autoshopify(site, fullcc, session)
        except Exception as e:
            result = {
                "Response": f"ERROR: {str(e)[:60]}",
                "Status": False,
                "Gateway": "Unknown",
                "Price": "0.00",
                "cc": fullcc
            }
        
        time_taken = round(time() - start_time, 2)
        
        # Format professional bill response
        final_message = format_bill_response(fullcc, result, user_info, time_taken)
        
        # Create buttons based on result
        response_upper = str(result.get("Response", "")).upper()
        
        if any(x in response_upper for x in ["ORDER_PLACED", "CHARGED", "SUCCESS"]):
            buttons = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("💎 Charged!", callback_data="charged_info"),
                    InlineKeyboardButton("📋 My Site", callback_data="show_my_site")
                ],
                [
                    InlineKeyboardButton("Support", url="https://t.me/Chr1shtopher")
                ]
            ])
        elif any(x in response_upper for x in ["INCORRECT_CVC", "3DS", "INSUFFICIENT", "CVV"]):
            buttons = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("✅ CCN Live", callback_data="ccn_info"),
                    InlineKeyboardButton("📋 My Site", callback_data="show_my_site")
                ],
                [
                    InlineKeyboardButton("Support", url="https://t.me/Chr1shtopher")
                ]
            ])
        else:
            buttons = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("🔄 Try Another", callback_data="try_another"),
                    InlineKeyboardButton("📋 My Site", callback_data="show_my_site")
                ],
                [
                    InlineKeyboardButton("Support", url="https://t.me/Chr1shtopher")
                ]
            ])
        
        await loading_msg.edit(
            final_message,
            reply_markup=buttons,
            disable_web_page_preview=True,
            parse_mode=ParseMode.HTML
        )
        
        # Deduct credit
        success, msg = deduct_credit(user_id)
        if not success:
            print(f"Credit deduction failed for user {user_id}")
        
    except Exception as e:
        print(f"Error in /sh command: {e}")
        import traceback
        traceback.print_exc()
        try:
            await message.reply(
                f"""<pre>⚠️ Error Occurred</pre>
━━━━━━━━━━━━━━━
<code>{str(e)[:100]}</code>

<i>Please try again or contact support.</i>""",
                reply_to_message_id=message.id,
                parse_mode=ParseMode.HTML
            )
        except:
            pass


# Callback handlers for buttons
@Client.on_callback_query(filters.regex("^help_addurl$"))
async def help_addurl_callback(client, callback_query):
    """Show help for adding URL."""
    await callback_query.answer()
    await callback_query.message.reply(
        """<pre>📖 How to Add Shopify Site</pre>
━━━━━━━━━━━━━━━
<b>Step 1:</b> Find a Shopify store URL
<b>Step 2:</b> Use the command:

<code>/addurl https://store.myshopify.com</code>

<b>The bot will:</b>
• ✅ Validate the site
• ✅ Find cheapest product
• ✅ Detect payment gateway
• ✅ Save it for your checks

<b>After adding, use:</b>
<code>/sh cc|mm|yy|cvv</code>
━━━━━━━━━━━━━━━""",
        parse_mode=ParseMode.HTML
    )


@Client.on_callback_query(filters.regex("^show_help$"))
async def show_help_callback(client, callback_query):
    """Show general help."""
    await callback_query.answer("Opening help menu...")
    await callback_query.message.reply(
        """<pre>📖 Bot Commands Help</pre>
━━━━━━━━━━━━━━━
<b>Shopify Commands:</b>
• <code>/addurl</code> - Add Shopify site
• <code>/mysite</code> - View your site
• <code>/sh</code> - Check card on your site
• <code>/msh</code> - Mass check cards

<b>Stripe Commands:</b>
• <code>/st</code> - Stripe $20 charge
• <code>/au</code> - Stripe auth check

<b>Other Commands:</b>
• <code>/bin</code> - BIN lookup
• <code>/fake</code> - Generate fake info
• <code>/gen</code> - Generate cards
━━━━━━━━━━━━━━━""",
        parse_mode=ParseMode.HTML
    )


@Client.on_callback_query(filters.regex("^charged_info$"))
async def charged_info_callback(client, callback_query):
    """Show info about charged card."""
    await callback_query.answer(
        "💎 Card was successfully charged! The payment went through.",
        show_alert=True
    )


@Client.on_callback_query(filters.regex("^ccn_info$"))
async def ccn_info_callback(client, callback_query):
    """Show info about CCN live card."""
    await callback_query.answer(
        "✅ Card is LIVE! CVV/Address issue but card number is valid.",
        show_alert=True
    )


@Client.on_callback_query(filters.regex("^try_another$"))
async def try_another_callback(client, callback_query):
    """Show how to try another card."""
    await callback_query.answer(
        "Use /sh cc|mm|yy|cvv with a different card",
        show_alert=True
    )
