"""
Professional Mass Shopify Checker with Global Priority Queue
Handles /msh command with Producer-Consumer Pattern for scalability.

Architecture:
- Producer: User sends /msh -> Cards added to Global Priority Queue
- Consumer: Global Worker Pool (500 workers) processes cards
- Priority: Premium users processed first (Priority 1-5), Free users last (Priority 10)
"""

import re
import time
import asyncio
from datetime import datetime
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.enums import ChatType, ParseMode
from BOT.Charge.Shopify.slf.site_manager import get_user_sites
from BOT.helper.start import load_users
from BOT.tools.proxy import get_rotating_proxy
from BOT.helper.permissions import check_private_access
from BOT.gc.credit import deduct_credit_bulk

# Try to import BIN lookup
try:
    from TOOLS.getbin import get_bin_details
except ImportError:
    def get_bin_details(bin_number):
        return None

# User locks to prevent concurrent requests from same user
user_locks = {}
msh_stop_requested: dict[str, bool] = {}

SPINNERS = ("◐", "◓", "◑", "◒")


def extract_cards(text):
    """Extract card numbers from text."""
    return re.findall(r'(\d{12,19}\|\d{1,2}\|\d{2,4}\|\d{3,4})', text)


def get_status_flag(raw_response):
    """
    Determine status flag from response.

    Categories:
    - Charged 💎: Payment completed successfully
    - Approved ✅: Card is live, CVV/Address issue (CCN)
    - Declined ❌: Card is dead/blocked/expired
    - Error ⚠️: System/Site errors
    """
    response_upper = str(raw_response).upper() if raw_response else ""

    # Check for system errors first
    if any(error_keyword in response_upper for error_keyword in [
        "CAPTCHA", "HCAPTCHA", "RECAPTCHA", "CHALLENGE", "VERIFY",
        "SITE_EMPTY", "SITE_HTML", "SITE_CAPTCHA", "SITE_HTTP", "SITE_CONNECTION",
        "SITE_NO_PRODUCTS", "SITE_PRODUCTS_EMPTY", "SITE_INVALID_JSON", "SITE_EMPTY_JSON",
        "CART_ERROR", "CART_HTML", "CART_INVALID", "CART_CREATION",
        "SESSION_ERROR", "SESSION_ID", "SESSION_INVALID",
        "CONNECTION FAILED", "IP RATE LIMIT", "PRODUCT ID", "SITE NOT FOUND",
        "REQUEST TIMEOUT", "REQUEST FAILED", "SITE | CARD ERROR",
        "ERROR", "BLOCKED", "PROXY", "TIMEOUT", "DEAD", "EMPTY",
        "NO_AVAILABLE_PRODUCTS", "BUILD", "TAX", "DELIVERY"
    ]):
        return "Error ⚠️"

    # Charged - Payment completed
    elif any(keyword in response_upper for keyword in [
        "ORDER_PLACED", "THANK YOU", "SUCCESS", "CHARGED", "COMPLETE"
    ]):
        return "Charged 💎"

    # Approved/CCN - Card is valid, CVV/Address issue
    elif any(keyword in response_upper for keyword in [
        "3D CC", "3DS", "3D_SECURE", "AUTHENTICATION_REQUIRED",
        "MISMATCHED_BILLING", "MISMATCHED_PIN", "MISMATCHED_ZIP", "MISMATCHED_BILL",
        "INCORRECT_CVC", "INVALID_CVC", "CVV_MISMATCH",
        "INCORRECT_ZIP", "INCORRECT_ADDRESS", "INCORRECT_PIN",
        "INSUFFICIENT_FUNDS"
    ]):
        return "Approved ✅"

    # Declined - Card is dead/blocked/expired
    else:
        return "Declined ❌"


@Client.on_message(filters.command("msh") | filters.regex(r"^\.mslf(\s|$)"))
async def mslf_handler(client, message):
    """
    Mass Shopify Checker using Global Priority Queue.

    Producer-Consumer Pattern:
    1. User sends /msh with cards (Producer)
    2. Cards are added to Global Priority Queue
    3. Worker Pool processes cards (Consumer)
    4. Real-time updates sent back to user
    """
    user_id = str(message.from_user.id)

    if not message.from_user:
        return await message.reply("❌ Cannot process this message. Comes From Channel")

    if user_id in user_locks:
        return await message.reply(
            "<pre>⚠️ Wait!</pre>\n"
            "<b>Your previous</b> <code>/msh</code> <b>request is still processing.</b>\n"
            "<b>Please wait until it finishes.</b>", reply_to_message_id=message.id
        )

    user_locks[user_id] = True

    try:
        users = load_users()

        if user_id not in users:
            return await message.reply(
                "<pre>Access Denied 🚫</pre>\n"
                "<b>You have to register first using</b> <code>/register</code> <b>command.</b>",
                reply_to_message_id=message.id
            )

        if not await check_private_access(message):
            return

        proxy = get_rotating_proxy(str(user_id))
        if not proxy:
            return await message.reply(
                "<pre>Proxy Error ❗️</pre>\n"
                "<b>~ Message :</b> <code>You Have To Add Proxy For Mass checking</code>\n"
                "<b>~ Command  →</b> <b>/setpx</b>\n",
                reply_to_message_id=message.id
            )

        # Check if user has sites
        user_sites = get_user_sites(user_id)
        if not user_sites:
            return await message.reply(
                "<pre>Site Not Found ⚠️</pre>\n"
                "Error : <code>Please Set Site First</code>\n"
                "~ <code>Using /addurl or /txturl</code>",
                reply_to_message_id=message.id
            )

        user_data = users[user_id]
        plan_info = user_data.get("plan", {})
        plan = plan_info.get("plan", "Free")
        badge = plan_info.get("badge", "🎟️")

        gateway = user_sites[0].get("gateway", "Shopify")
        site_count = len(user_sites)

        target_text = None
        if message.reply_to_message and message.reply_to_message.text:
            target_text = message.reply_to_message.text
        elif len(message.text.split(maxsplit=1)) > 1:
            target_text = message.text.split(maxsplit=1)[1]

        if not target_text:
            return await message.reply(
                "❌ Send cards!\n1 per line:\n4633438786747757|10|2025|298",
                reply_to_message_id=message.id
            )

        all_cards = extract_cards(target_text)
        if not all_cards:
            return await message.reply("❌ No valid cards found!", reply_to_message_id=message.id)

        # Check credits
        available_credits = user_data.get("plan", {}).get("credits", 0)
        card_count = len(all_cards)

        if available_credits != "∞":
            try:
                available_credits = int(available_credits)
                if card_count > available_credits:
                    return await message.reply(
                        "<pre>Notification ❗️</pre>\n"
                        "<b>Message :</b> <code>You Have Insufficient Credits</code>\n"
                        "<b>Get Credits To Use</b>\n"
                        "━━━━━━━━━━━━━\n"
                        "<b>Type <code>/buy</code> to get Credits.</b>",
                        reply_to_message_id=message.id
                    )
            except Exception:
                return await message.reply(
                    "⚠️ Error reading your credit balance.",
                    reply_to_message_id=message.id
                )

        checked_by = f"<a href='tg://user?id={message.from_user.id}'>{message.from_user.first_name}</a>"

        # Initialize stop flag
        msh_stop_requested[user_id] = False

        stop_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⏹ Stop Checking", callback_data=f"msh_stop_{user_id}")],
        ])

        # Get queue and show initial message
        from BOT.queue.manager import get_global_queue, Priority, get_priority_for_plan

        queue = await get_global_queue()
        queue_stats = await queue.get_queue_stats()
        priority = get_priority_for_plan(plan)
        priority_name = Priority(priority).name

        loader_msg = await message.reply(
            f"""<pre>◐ [#MSH] | Mass Shopify Check</pre>
━━━━━━━━━━━━━━━
<b>[⚬] Gateway:</b> <code>{gateway}</code>
<b>[⚬] Cards:</b> <code>{card_count}</code>
<b>[⚬] Sites:</b> <code>{site_count}</code>
<b>[⚬] Mode:</b> <code>Priority Queue ⚡</code>
<b>[⚬] Priority:</b> <code>{priority_name} (P{priority})</code>
<b>[⚬] Queue Size:</b> <code>{queue_stats['queue_size']}</code>
<b>[⚬] Workers:</b> <code>{queue_stats['max_workers']} global</code>
<b>[⚬] Status:</b> <code>◐ Adding to queue...</code>
━━━━━━━━━━━━━
<b>[⚬] Checked By:</b> {checked_by} [<code>{plan} {badge}</code>]""",
            reply_to_message_id=message.id,
            parse_mode=ParseMode.HTML,
            reply_markup=stop_kb,
        )

        # Track progress state
        start_time = time.time()
        progress_state = {
            "processed": 0,
            "charged": 0,
            "approved": 0,
            "declined": 0,
            "errors": 0,
            "retries": 0,
            "last_edit": 0,
            "stopped": False,
        }
        progress_lock = asyncio.Lock()
        PROGRESS_THROTTLE = 0.25

        async def on_result(result):
            """Called for each card result (hit notification)."""
            if result.status in ("charged", "approved"):
                cc_num = result.card.split("|")[0] if "|" in result.card else result.card
                try:
                    bin_data = get_bin_details(cc_num[:6])
                    if bin_data:
                        bin_info = f"{bin_data.get('vendor', 'N/A')} - {bin_data.get('type', 'N/A')} - {bin_data.get('level', 'N/A')}"
                        bank = bin_data.get('bank', 'N/A')
                        country = f"{bin_data.get('country', 'N/A')} {bin_data.get('flag', '')}"
                    else:
                        bin_info = bank = country = "N/A"
                except Exception:
                    bin_info = bank = country = "N/A"

                pr = result.extra.get("price", "0.00") if result.extra else "0.00"
                try:
                    pv = float(pr)
                    pr = f"{pv:.2f}" if pv != int(pv) else str(int(pv))
                except (TypeError, ValueError):
                    pr = str(pr) if pr else "0.00"

                gateway_display = f"Shopify Normal ${pr}"
                hit_header = "CHARGED" if result.status == "charged" else "CCN LIVE"
                hit_status = "Charged 💎" if result.status == "charged" else "Approved ✅"

                hit_message = f"""<b>[#Shopify] | {hit_header}</b> ✦
━━━━━━━━━━━━━━━
<b>[•] Card:</b> <code>{result.card}</code>
<b>[•] Gateway:</b> <code>{gateway_display}</code>
<b>[•] Status:</b> <code>{hit_status}</code>
<b>[•] Response:</b> <code>{result.response}</code>
<b>[•] Retries:</b> <code>{result.retries}</code>
━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━
<b>[+] BIN:</b> <code>{cc_num[:6]}</code>
<b>[+] Info:</b> <code>{bin_info}</code>
<b>[+] Bank:</b> <code>{bank}</code> 🏦
<b>[+] Country:</b> <code>{country}</code>
━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━
<b>[ﾒ] Checked By:</b> {checked_by} [<code>{plan} {badge}</code>]
<b>[ϟ] Dev:</b> <a href="https://t.me/Chr1shtopher">Chr1shtopher</a>
━━━━━━━━━━━━━━━"""
                try:
                    await message.reply(hit_message, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
                except Exception:
                    pass

        async def on_progress(batch):
            """Called for progress updates."""
            nonlocal progress_state

            async with progress_lock:
                # Check if stopped by user
                if msh_stop_requested.get(user_id):
                    if not progress_state["stopped"]:
                        progress_state["stopped"] = True
                        await queue.stop_batch(batch.batch_id)
                    return

                now = time.time()
                if (now - progress_state["last_edit"]) < PROGRESS_THROTTLE:
                    return

                progress_state["last_edit"] = now
                elapsed = now - start_time
                rate = (batch.processed / elapsed) if elapsed > 0 else 0
                sp = SPINNERS[batch.processed % 4]

                try:
                    await loader_msg.edit(
                        f"""<pre>{sp} [#MSH] | Mass Shopify Check</pre>
━━━━━━━━━━━━━━━
<b>🟢 Total CC:</b> <code>{batch.total_cards}</code>
<b>💬 Progress:</b> <code>{batch.processed}/{batch.total_cards}</code>
<b>✅ Approved:</b> <code>{batch.approved}</code>
<b>💎 Charged:</b> <code>{batch.charged}</code>
<b>❌ Declined:</b> <code>{batch.declined}</code>
<b>⚠️ Errors:</b> <code>{batch.errors}</code>
<b>🔄 Rotations:</b> <code>{batch.retries}</code>
<b>⏱️ Time:</b> <code>{elapsed:.1f}s</code> · <code>{rate:.1f} cc/s</code>
<b>⚡ Mode:</b> <code>Priority Queue ({priority_name})</code>
<b>👤 Checked By:</b> {checked_by} [<code>{plan} {badge}</code>]""",
                        parse_mode=ParseMode.HTML,
                        disable_web_page_preview=True,
                        reply_markup=stop_kb,
                    )
                except Exception:
                    pass

        async def on_complete(batch):
            """Called when batch is complete."""
            nonlocal progress_state

            end_time = time.time()
            timetaken = round(end_time - start_time, 2)
            rate_final = (batch.processed / timetaken) if timetaken > 0 else 0

            # Deduct credits
            if user_data["plan"].get("credits") != "∞":
                loop = asyncio.get_event_loop()
                count_to_deduct = batch.processed if batch.stopped else batch.total_cards
                await loop.run_in_executor(None, deduct_credit_bulk, user_id, count_to_deduct)

            current_time = datetime.now().strftime("%I:%M %p")
            header = "<pre>⏹ Stopped by user</pre>" if batch.stopped else "<pre>✦ CC Check Completed</pre>"

            completion_message = f"""{header}
━━━━━━━━━━━━━━━
🟢 <b>Total CC</b>     : <code>{batch.total_cards}</code>
💬 <b>Progress</b>    : <code>{batch.processed}/{batch.total_cards}</code>
✅ <b>Approved</b>    : <code>{batch.approved}</code>
💎 <b>Charged</b>     : <code>{batch.charged}</code>
❌ <b>Declined</b>    : <code>{batch.declined}</code>
⚠️ <b>Errors</b>      : <code>{batch.errors}</code>
🔄 <b>Rotations</b>   : <code>{batch.retries}</code>
━━━━━━━━━━━━━━━
⏱️ <b>Time</b> : <code>{timetaken}s</code> · <code>{rate_final:.1f} cc/s</code>
⚡ <b>Mode</b> : <code>Priority Queue ({priority_name})</code>
👤 <b>Checked By</b> : {checked_by} [<code>{plan} {badge}</code>]
🔧 <b>Dev</b>: <a href="https://t.me/Chr1shtopher">Chr1shtopher</a> <code>{current_time}</code>
━━━━━━━━━━━━━━━"""

            try:
                await loader_msg.edit(
                    completion_message,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True,
                    reply_markup=None,
                )
            except Exception:
                pass

            # Release user lock
            user_locks.pop(user_id, None)

        # Add batch to global queue (Producer)
        batch_id = await queue.add_batch(
            user_id=user_id,
            cards=all_cards,
            gateway="shopify",
            plan=plan,
            badge=badge,
            checked_by=checked_by,
            chat_id=message.chat.id,
            message_id=loader_msg.id,
            proxy=proxy,
            sites=user_sites,
            on_result=on_result,
            on_progress=on_progress,
            on_complete=on_complete,
        )

        # Store batch_id for stop functionality
        msh_stop_requested[f"batch_{user_id}"] = batch_id

        # Update message to show queued status
        queue_stats = await queue.get_queue_stats()
        try:
            await loader_msg.edit(
                f"""<pre>◐ [#MSH] | Mass Shopify Check</pre>
━━━━━━━━━━━━━━━
<b>[⚬] Gateway:</b> <code>{gateway}</code>
<b>[⚬] Cards:</b> <code>{card_count}</code>
<b>[⚬] Sites:</b> <code>{site_count}</code>
<b>[⚬] Mode:</b> <code>Priority Queue ⚡</code>
<b>[⚬] Priority:</b> <code>{priority_name} (P{priority})</code>
<b>[⚬] Queue Size:</b> <code>{queue_stats['queue_size']}</code>
<b>[⚬] Workers:</b> <code>{queue_stats['max_workers']} global</code>
<b>[⚬] Status:</b> <code>✓ Queued! Processing...</code>
━━━━━━━━━━━━━
<b>[⚬] Checked By:</b> {checked_by} [<code>{plan} {badge}</code>]""",
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
                reply_markup=stop_kb,
            )
        except Exception:
            pass

    except Exception as e:
        await message.reply(f"⚠️ Error: {e}", reply_to_message_id=message.id)
        user_locks.pop(user_id, None)


@Client.on_callback_query(filters.regex(r"^msh_stop_(\d+)$"))
async def msh_stop_callback(client, cq):
    """Stop a running /msh check. Mandatory: only the user who started it can stop."""
    try:
        if not cq.from_user:
            await cq.answer("Invalid request.", show_alert=True)
            return

        uid = cq.matches[0].group(1) if cq.matches else None

        # Only the user who started this check can stop it
        if not uid or str(cq.from_user.id) != uid:
            await cq.answer("Only the user who started this check can stop it.", show_alert=True)
            return

        # Set stop flag
        msh_stop_requested[uid] = True

        # Also stop via queue if batch_id exists
        batch_id = msh_stop_requested.get(f"batch_{uid}")
        if batch_id:
            from BOT.queue.manager import get_global_queue
            queue = await get_global_queue()
            await queue.stop_batch(batch_id)

        try:
            await cq.message.edit_text(
                "<pre>⏹ Stopping... Please wait.</pre>\n\n"
                "━━━━━━━━━━━━━━━\n"
                "The check will stop after current cards finish.",
                parse_mode=ParseMode.HTML,
                reply_markup=None,
            )
        except Exception:
            pass

        await cq.answer("Stop requested. Stopping after current cards…")

    except Exception:
        await cq.answer("Could not process.", show_alert=True)
