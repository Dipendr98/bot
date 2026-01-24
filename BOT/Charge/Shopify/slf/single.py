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
from pyrogram.enums import ParseMode, ChatType, ChatAction

from BOT.helper.start import load_users
from BOT.helper.antispam import can_run_command
from BOT.gc.credit import has_credits, deduct_credit
from BOT.Charge.Shopify.slf.api import autoshopify, autoshopify_with_captcha_retry
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
# Concurrent threads per card (10 parallel checks at a time; first valid wins)
SH_CONCURRENT_THREADS = 10


def _is_valid_shopify_response(rotator: SiteRotator, resp: str) -> bool:
    """True if proper card response (charged/CCN/declined). False for captcha/site/HTTP/JSON errors."""
    if not resp:
        return False
    if rotator.is_real_response(resp):
        return True
    if rotator.should_retry(resp):
        return False
    u = resp.upper()
    invalid = (
        "CAPTCHA" in u or "HCAPTCHA" in u or "SITE_" in u or "CART_" in u or "SESSION_" in u
        or "ERROR" in u or "TIMEOUT" in u or "CONNECTION" in u or "JSON" in u or "HTTP" in u
    )
    return not invalid


async def check_card_all_sites_parallel(
    user_id: str,
    fullcc: str,
    proxy,
) -> tuple:
    """
    Run Shopify check across all user sites in parallel.
    First valid response wins; cancel remaining site-tasks, return result, then next CC.
    Valid = proper decline/approved/charged/CCN. Invalid = captcha, HTTP, site, JSON errors.
    """
    sites = get_user_sites(user_id)
    sites = [s for s in sites if s.get("active", True)]
    if not sites:
        return (
            {"Response": "NO_SITES_CONFIGURED", "Status": False, "Gateway": "Unknown", "Price": "0.00", "cc": fullcc},
            0,
        )

    rotator = SiteRotator(user_id, max_retries=MAX_SITE_RETRIES)

    async def check_one(site_info: dict):
        url = site_info.get("url", "")
        gate = site_info.get("gateway", "Shopify")
        try:
            async with TLSAsyncSession(timeout_seconds=120, proxy=proxy) as session:
                res = await autoshopify_with_captcha_retry(
                    url, fullcc, session, max_captcha_retries=7, proxy=proxy
                )
            return (url, gate, res)
        except Exception as e:
            return (url, gate, {"Response": f"ERROR: {str(e)[:50]}", "Status": False, "Gateway": gate, "Price": "0.00", "cc": fullcc})

    # 10 threads per batch: cycle through sites so we always run SH_CONCURRENT_THREADS concurrent checks
    task_sites = [sites[i % len(sites)] for i in range(SH_CONCURRENT_THREADS)]

    async def _run_parallel() -> tuple:
        """Run 10 concurrent site checks; first valid wins. Return (result_dict, gate_str, all_retryable)."""
        ts = [asyncio.create_task(check_one(s)) for s in task_sites]
        last_res = None
        last_gate = "Unknown"
        all_retryable = True
        try:
            while ts:
                done, pending = await asyncio.wait(ts, return_when=asyncio.FIRST_COMPLETED)
                for t in done:
                    try:
                        url, gate, res = t.result()
                    except asyncio.CancelledError:
                        continue
                    except Exception as e:
                        gate = "Unknown"
                        res = {"Response": f"ERROR: {str(e)[:50]}", "Status": False, "Gateway": gate, "Price": "0.00", "cc": fullcc}
                    resp = str((res or {}).get("Response", ""))
                    last_res, last_gate = res, gate
                    if _is_valid_shopify_response(rotator, resp):
                        for p in pending:
                            p.cancel()
                        res["Gateway"] = gate
                        return (res, gate, False)
                    if not rotator.should_retry(resp):
                        all_retryable = False
                ts = list(pending)
        except asyncio.CancelledError:
            pass
        for t in ts:
            try:
                t.cancel()
            except Exception:
                pass
        return (last_res, last_gate, all_retryable)

    res, gate_str, all_retryable = await _run_parallel()
    if isinstance(res, dict) and _is_valid_shopify_response(rotator, str((res or {}).get("Response", ""))):
        res["Gateway"] = res.get("Gateway") or gate_str
        return (res, 0)

    last_res = res
    last_gate = gate_str if isinstance(gate_str, str) else "Unknown"
    retry_count = 0

    # Retry with another 10-thread batch until real response or max batches (captcha/site errors only)
    max_batches = 3
    for _ in range(max_batches - 1):
        if not all_retryable or last_res is None:
            break
        await asyncio.sleep(4)
        res2, gate2, all_retryable = await _run_parallel()
        if isinstance(res2, dict) and _is_valid_shopify_response(rotator, str((res2 or {}).get("Response", ""))):
            res2["Gateway"] = res2.get("Gateway") or (gate2 if isinstance(gate2, str) else "Unknown")
            return (res2, retry_count + 1)
        if res2 is not None:
            last_res, last_gate = res2, (gate2 if isinstance(gate2, str) else "Unknown")
        retry_count += 1

    if last_res is not None:
        last_res["Gateway"] = last_gate
        return (last_res, retry_count)
    return (
        {"Response": "UNKNOWN", "Status": False, "Gateway": "Unknown", "Price": "0.00", "cc": fullcc},
        0,
    )


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
        "REVOKED", "SERVICE_NOT_ALLOWED", "RISKY"
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

    # Gateway display: site gateway may already be "Shopify Normal $0.50"; avoid "Shopify ... $0.50 $0.54" (double price)
    if "$" in str(gateway):
        gateway_display = gateway
    else:
        gateway_display = f"Shopify {gateway} ${price}"
    
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
    
    retry_line = f"\n<b>[•] Retries:</b> <code>{retry_count}</code>"
    
    proxy_status = "Live ⚡️" if has_proxy else "None"
    
    # Build message in original format
    return f"""<b>[#Shopify] | {header}</b> ✦
━━━━━━━━━━━━━━━
<b>[•] Card:</b> <code>{fullcc}</code>
<b>[•] Gateway:</b> <code>{gateway_display}</code>
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
        
        # Show loading message with round spinner
        site_count = rotator.get_site_count()
        loading_msg = await message.reply(
            f"""<pre>◐ Checking...</pre>
━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━
<b>• Card:</b> <code>{fullcc}</code>
<b>• Gate:</b> <code>Shopify</code>
<b>• Sites:</b> <code>{site_count}</code>
<b>• Status:</b> <i>◐ Processing...</i>""",
            reply_to_message_id=message.id,
            parse_mode=ParseMode.HTML
        )

        spinners = ("◐", "◓", "◑", "◒")

        async def spinner_loop():
            i = 0
            while True:
                try:
                    await loading_msg.edit(
                        f"""<pre>{spinners[i % 4]} Checking...</pre>
━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━
<b>• Card:</b> <code>{fullcc}</code>
<b>• Gate:</b> <code>Shopify</code>
<b>• Sites:</b> <code>{site_count}</code>
<b>• Status:</b> <i>{spinners[i % 4]} Processing...</i>""",
                        parse_mode=ParseMode.HTML,
                    )
                except Exception:
                    pass
                i += 1
                await asyncio.sleep(1.2)

        async def typing_loop():
            while True:
                try:
                    await client.send_chat_action(message.chat.id, ChatAction.TYPING)
                except Exception:
                    pass
                await asyncio.sleep(4)

        spinner_task = asyncio.create_task(spinner_loop())
        typing_task = asyncio.create_task(typing_loop())

        SH_RETRY_ATTEMPTS = 3
        result = None
        retry_count = 0
        try:
            for attempt in range(SH_RETRY_ATTEMPTS):
                res, r = await check_card_all_sites_parallel(user_id, fullcc, user_proxy)
                retry_count += r
                resp = str((res or {}).get("Response", ""))
                if _is_valid_shopify_response(rotator, resp):
                    result = res
                    break
                if rotator.should_retry(resp) and attempt < SH_RETRY_ATTEMPTS - 1:
                    await asyncio.sleep(1.5)
                    continue
                result = res
                break
        finally:
            spinner_task.cancel()
            typing_task.cancel()
            try:
                await spinner_task
            except asyncio.CancelledError:
                pass
            try:
                await typing_task
            except asyncio.CancelledError:
                pass

        if result is None:
            result = {"Response": "UNKNOWN", "Status": False, "Gateway": "Unknown", "Price": "0.00"}

        time_taken = round(time() - start_time, 2)
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
