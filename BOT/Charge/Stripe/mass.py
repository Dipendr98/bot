"""
Mass Stripe $20 Charge Handler with Global Priority Queue
Handles /mst command with Producer-Consumer Pattern for scalability.

Architecture:
- Producer: User sends /mst -> Cards added to Global Priority Queue
- Consumer: Global Worker Pool (500 workers) processes cards
- Priority: Premium users processed first (Priority 1-5), Free users last (Priority 10)
"""

import re
import time
import asyncio
from datetime import datetime
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.enums import ParseMode
from BOT.helper.start import load_users
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
mst_stop_requested: dict[str, bool] = {}

SPINNERS = ("◐", "◓", "◑", "◒")


def extract_cards(text):
    """Extract all cards from text."""
    return re.findall(r'(\d{12,19}\|\d{1,2}\|\d{2,4}\|\d{3,4})', text)


def get_status_flag(status, response):
    """Determine status flag from result."""
    if status == "charged":
        return "Charged 💎"
    elif status == "approved":
        return "Approved ✅"
    elif status == "declined":
        return "Declined ❌"
    else:
        return "Error ⚠️"


@Client.on_message(filters.command(["mst", "mstripe"]) | filters.regex(r"^\$mst(\s|$)"))
async def handle_mass_stripe(client, message):
    """
    Mass Stripe $20 Checker using Global Priority Queue.

    Producer-Consumer Pattern:
    1. User sends /mst with cards (Producer)
    2. Cards are added to Global Priority Queue
    3. Worker Pool processes cards (Consumer)
    4. Real-time updates sent back to user
    """
    if not message.from_user:
        return

    user_id = str(message.from_user.id)

    # Check if user has ongoing request
    if user_id in user_locks:
        return await message.reply(
            "<pre>⚠️ Wait!</pre>\n"
            "<b>Your previous</b> <code>/mst</code> <b>request is still processing.</b>",
            reply_to_message_id=message.id,
            parse_mode=ParseMode.HTML
        )

    user_locks[user_id] = True

    try:
        users = load_users()

        if user_id not in users:
            return await message.reply(
                """<pre>Access Denied 🚫</pre>
<b>You have to register first using</b> <code>/register</code> <b>command.</b>""",
                reply_to_message_id=message.id,
                parse_mode=ParseMode.HTML
            )

        # Check private access
        if not await check_private_access(message):
            return

        user_data = users[user_id]
        plan_info = user_data.get("plan", {})
        plan = plan_info.get("plan", "Free")
        badge = plan_info.get("badge", "🎟️")

        # Extract cards
        target_text = None
        if message.reply_to_message and message.reply_to_message.text:
            target_text = message.reply_to_message.text
        elif len(message.text.split(maxsplit=1)) > 1:
            target_text = message.text.split(maxsplit=1)[1]

        if not target_text:
            return await message.reply(
                "❌ <b>Send cards!</b>\n1 per line:\n<code>4242424242424242|08|28|690</code>",
                reply_to_message_id=message.id,
                parse_mode=ParseMode.HTML
            )

        all_cards = extract_cards(target_text)
        if not all_cards:
            return await message.reply(
                "❌ No valid cards found!",
                reply_to_message_id=message.id,
                parse_mode=ParseMode.HTML
            )

        # Check credits
        available_credits = user_data["plan"].get("credits", 0)
        card_count = len(all_cards)

        if available_credits != "∞":
            try:
                available_credits = int(available_credits)
                if card_count > available_credits:
                    return await message.reply(
                        """<pre>Notification ❗️</pre>
<b>Message :</b> <code>You Have Insufficient Credits</code>
━━━━━━━━━━━━━
<b>Type <code>/buy</code> to get Credits.</b>""",
                        reply_to_message_id=message.id,
                        parse_mode=ParseMode.HTML
                    )
            except:
                pass

        gateway = "Stripe $20 Balliante"
        checked_by = f"<a href='tg://user?id={message.from_user.id}'>{message.from_user.first_name}</a>"

        # Initialize stop flag
        mst_stop_requested[user_id] = False

        stop_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⏹ Stop Checking", callback_data=f"mst_stop_{user_id}")],
        ])

        # Get queue and show initial message
        from BOT.queue.manager import get_global_queue, Priority, get_priority_for_plan

        queue = await get_global_queue()
        queue_stats = await queue.get_queue_stats()
        priority = get_priority_for_plan(plan)
        priority_name = Priority(priority).name

        # Send loading message
        loader_msg = await message.reply(
            f"""<pre>◐ [#Stripe] | Mass Stripe $20 Check</pre>
━━━━━━━━━━━━━━━
<b>[⚬] Gateway:</b> <code>{gateway}</code>
<b>[⚬] Cards:</b> <code>{card_count}</code>
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
            "last_edit": 0,
            "stopped": False,
        }
        progress_lock = asyncio.Lock()
        PROGRESS_THROTTLE = 0.25

        async def on_result(result):
            """Called for each card result (hit notification)."""
            if result.status in ("charged", "approved"):
                card_num = result.card.split("|")[0] if "|" in result.card else result.card
                bin_info = "N/A"
                country_info = "N/A"
                try:
                    bin_data = get_bin_details(card_num[:6])
                    if bin_data:
                        bin_info = f"{bin_data.get('vendor', 'N/A')} - {bin_data.get('type', 'N/A')}"
                        country_info = f"{bin_data.get('country', 'N/A')} {bin_data.get('flag', '')}"
                except:
                    pass

                status_flag = get_status_flag(result.status, result.response)
                hit_msg = (
                    f"<b>[#Stripe] | {status_flag}</b> ✦\n"
                    f"━━━━━━━━━━━━━━━\n"
                    f"<b>[•] Card:</b> <code>{result.card}</code>\n"
                    f"<b>[•] Status:</b> <code>{status_flag}</code>\n"
                    f"<b>[•] Response:</b> <code>{result.response}</code>\n"
                    f"━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━\n"
                    f"<b>[+] BIN:</b> <code>{card_num[:6]}</code> | <code>{bin_info}</code>\n"
                    f"<b>[+] Country:</b> <code>{country_info}</code>\n"
                    f"━━━━━━━━━━━━━━━\n"
                    f"<b>[ﾒ] Checked By:</b> {checked_by}"
                )
                try:
                    await message.reply(hit_msg, parse_mode=ParseMode.HTML)
                except:
                    pass

        async def on_progress(batch):
            """Called for progress updates."""
            nonlocal progress_state

            async with progress_lock:
                # Check if stopped by user
                if mst_stop_requested.get(user_id):
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
                        f"""<pre>{sp} [#Stripe] | Mass Stripe $20 Check</pre>
━━━━━━━━━━━━━━━
<b>🟢 Total CC:</b> <code>{batch.total_cards}</code>
<b>💬 Progress:</b> <code>{batch.processed}/{batch.total_cards}</code>
<b>💎 Charged:</b> <code>{batch.charged}</code>
<b>✅ Approved:</b> <code>{batch.approved}</code>
<b>❌ Declined:</b> <code>{batch.declined}</code>
<b>⚠️ Errors:</b> <code>{batch.errors}</code>
<b>⏱️ Time:</b> <code>{elapsed:.1f}s</code> · <code>{rate:.1f} cc/s</code>
<b>⚡ Mode:</b> <code>Priority Queue ({priority_name})</code>
<b>👤 Checked By:</b> {checked_by} [<code>{plan} {badge}</code>]""",
                        parse_mode=ParseMode.HTML,
                        disable_web_page_preview=True,
                        reply_markup=stop_kb,
                    )
                except:
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
            header = "<pre>⏹ Stopped by user</pre>" if batch.stopped else "<b>[#Stripe] | MASS CHECK ✦</b>"

            completion_message = f"""{header}
━━━━━━━━━━━━━━━
🟢 <b>Total CC</b>     : <code>{batch.total_cards}</code>
💬 <b>Progress</b>    : <code>{batch.processed}/{batch.total_cards}</code>
💎 <b>Charged</b>     : <code>{batch.charged}</code>
✅ <b>Approved</b>    : <code>{batch.approved}</code>
❌ <b>Declined</b>    : <code>{batch.declined}</code>
⚠️ <b>Errors</b>      : <code>{batch.errors}</code>
━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━ ━
<b>[ﾒ] Checked By:</b> {checked_by} [<code>{plan} {badge}</code>]
<b>[ϟ] Dev:</b> <a href="https://t.me/Chr1shtopher">Chr1shtopher</a>
━━━━━━━━━━━━━━━
<b>[ﾒ] Time:</b> <code>{timetaken}s</code> · <code>{rate_final:.1f} cc/s</code>
<b>[ﾒ] Mode:</b> <code>Priority Queue ({priority_name})</code> | <code>{current_time}</code>"""

            try:
                await loader_msg.edit(
                    completion_message,
                    disable_web_page_preview=True,
                    parse_mode=ParseMode.HTML,
                    reply_markup=None,
                )
            except:
                pass

            # Release user lock
            user_locks.pop(user_id, None)

        # Add batch to global queue (Producer)
        batch_id = await queue.add_batch(
            user_id=user_id,
            cards=all_cards,
            gateway="stripe",
            plan=plan,
            badge=badge,
            checked_by=checked_by,
            chat_id=message.chat.id,
            message_id=loader_msg.id,
            on_result=on_result,
            on_progress=on_progress,
            on_complete=on_complete,
        )

        # Store batch_id for stop functionality
        mst_stop_requested[f"batch_{user_id}"] = batch_id

        # Update message to show queued status
        queue_stats = await queue.get_queue_stats()
        try:
            await loader_msg.edit(
                f"""<pre>◐ [#Stripe] | Mass Stripe $20 Check</pre>
━━━━━━━━━━━━━━━
<b>[⚬] Gateway:</b> <code>{gateway}</code>
<b>[⚬] Cards:</b> <code>{card_count}</code>
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
        except:
            pass

    except Exception as e:
        print(f"Error in /mst: {e}")
        import traceback
        traceback.print_exc()
        try:
            await message.reply(
                f"<b>⚠️ An error occurred:</b>\n<code>{str(e)}</code>",
                reply_to_message_id=message.id,
                parse_mode=ParseMode.HTML
            )
        except:
            pass
        user_locks.pop(user_id, None)


@Client.on_callback_query(filters.regex(r"^mst_stop_(\d+)$"))
async def mst_stop_callback(client, cq):
    """Stop a running /mst check. Only the user who started it can stop."""
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
        mst_stop_requested[uid] = True

        # Also stop via queue if batch_id exists
        batch_id = mst_stop_requested.get(f"batch_{uid}")
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
        except:
            pass

        await cq.answer("Stop requested. Stopping after current cards…")

    except Exception:
        await cq.answer("Could not process.", show_alert=True)
