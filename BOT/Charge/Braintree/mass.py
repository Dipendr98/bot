import re
import time
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from BOT.helper.start import load_users
from BOT.helper.permissions import check_private_access, is_premium_user
from BOT.Charge.Braintree.api import check_braintree
from BOT.gc.credit import deduct_credit_bulk

user_locks = {}


def extract_cards(text):
    """Extract multiple card details from text"""
    return re.findall(r'(\d{12,19})\|(\d{1,2})\|(\d{2,4})\|(\d{3,4})', text)


@Client.on_message(filters.command(["mbr", "mbraintree"]) | filters.regex(r"^\$mbr(\s|$)"))
async def handle_mass_braintree(client, message):
    """
    Handle mass Braintree card checking

    Usage: /mbr or $mbr with multiple cards
    Example:
    /mbr 4405639706340195|03|2029|734
    5312590016282230|12|2029|702
    """
    user_id = str(message.from_user.id)

    # Check if user has ongoing request
    if user_id in user_locks:
        return await message.reply(
            "<pre>⚠️ Wait!</pre>\n"
            "<b>Your previous</b> <code>$mbr</code> <b>request is still processing.</b>\n"
            "<b>Please wait until it finishes.</b>",
            reply_to_message_id=message.id
        )

    user_locks[user_id] = True

    try:
        # Load users
        users = load_users()

        # Check if user is registered
        if user_id not in users:
            return await message.reply(
                """<pre>Access Denied 🚫</pre>
<b>You have to register first using</b> <code>/register</code> <b>command.</b>""",
                reply_to_message_id=message.id
            )

        # Premium check
        if not await is_premium_user(message):
            return

        # Private access check
        if not await check_private_access(message):
            return

        user_data = users[user_id]
        plan = user_data.get("plan", {}).get("plan", "Free")
        badge = user_data.get("plan", {}).get("badge", "🎟️")
        mlimit = user_data.get("plan", {}).get("mlimit", 5)

        # Extract cards
        target_text = None
        if message.reply_to_message and message.reply_to_message.text:
            target_text = message.reply_to_message.text
        elif len(message.text.split(maxsplit=1)) > 1:
            target_text = message.text.split(maxsplit=1)[1]

        if not target_text:
            return await message.reply(
                "❌ <b>Send cards in format:</b>\n<code>$mbr cc|mes|ano|cvv</code>\n\n"
                "<b>Example:</b>\n"
                "<code>$mbr 4405639706340195|03|2029|734\n5312590016282230|12|2029|702</code>",
                reply_to_message_id=message.id
            )

        # Find all cards
        cards = extract_cards(target_text)

        if not cards:
            return await message.reply(
                "❌ <b>No valid cards found!</b>\n"
                "<b>Format:</b> <code>cc|mes|ano|cvv</code>",
                reply_to_message_id=message.id
            )

        # Check mass limit
        card_count = len(cards)
        if card_count > mlimit:
            return await message.reply(
                f"<pre>⚠️ Mass Limit Exceeded</pre>\n"
                f"<b>Your plan allows maximum</b> <code>{mlimit}</code> <b>cards per mass check.</b>\n"
                f"<b>You sent:</b> <code>{card_count}</code> <b>cards.</b>\n\n"
                f"<b>Upgrade your plan to check more cards!</b>",
                reply_to_message_id=message.id
            )

        # Check credits
        available_credits = user_data["plan"].get("credits", 0)
        if available_credits != "∞":
            try:
                available_credits = int(available_credits)
                if available_credits < card_count:
                    return await message.reply(
                        f"""<pre>Notification ❗️</pre>
<b>Message :</b> <code>You Have Insufficient Credits</code>
<b>Required:</b> <code>{card_count}</code> <b>credits</b>
<b>Available:</b> <code>{available_credits}</code> <b>credits</b>
━━━━━━━━━━━━━
<b>Type <code>/buy</code> to get Credits.</b>""",
                        reply_to_message_id=message.id
                    )
            except:
                return await message.reply(
                    "⚠️ Error reading your credit balance.",
                    reply_to_message_id=message.id
                )

        checked_by = f"<a href='tg://user?id={message.from_user.id}'>{message.from_user.first_name}</a>"

        # Initialize counters
        approved = 0
        declined = 0
        errors = 0
        results = []

        # Send initial message
        loader_msg = await message.reply(
            f"""<pre>━━━ Mass Braintree Charge ━━━</pre>
<b>Total Cards:</b> <code>{card_count}</code>
<b>Progress:</b> <code>0/{card_count}</code>
<b>Gateway:</b> <code>Braintree [Pixorize $29.99]</code>

<b>Status:</b> <code>Starting...</code>
━━━━━━━━━━━━━━━
<b>✅ Approved:</b> <code>0</code>
<b>❌ Declined:</b> <code>0</code>
<b>⚠️ Errors:</b> <code>0</code>""",
            reply_to_message_id=message.id
        )

        start_time = time.time()

        # Process each card
        for idx, (card, mes, ano, cvv) in enumerate(cards, 1):
            fullcc = f"{card}|{mes}|{ano}|{cvv}"

            # Check card
            result = await check_braintree(card, mes, ano, cvv)
            status = result.get("status", "error")
            response = result.get("message", "Unknown")

            # Update counters
            if status == "approved":
                approved += 1
                status_emoji = "✅"
            elif status == "declined":
                declined += 1
                status_emoji = "❌"
            else:
                errors += 1
                status_emoji = "⚠️"

            # Store result
            results.append({
                "card": fullcc,
                "status": status,
                "response": response,
                "emoji": status_emoji
            })

            # Update message every card or every 3 seconds
            if idx % 1 == 0 or idx == card_count:
                # Show last 10 results
                recent_results = results[-10:]
                results_text = "\n".join([
                    f"{r['emoji']} <code>{r['card']}</code> | <code>{r['response'][:30]}</code>"
                    for r in recent_results
                ])

                progress_msg = f"""<pre>━━━ Mass Braintree Charge ━━━</pre>
<b>Total Cards:</b> <code>{card_count}</code>
<b>Progress:</b> <code>{idx}/{card_count}</code>
<b>Gateway:</b> <code>Braintree [Pixorize $29.99]</code>

<b>Recent Results:</b>
{results_text}
━━━━━━━━━━━━━━━
<b>✅ Approved:</b> <code>{approved}</code>
<b>❌ Declined:</b> <code>{declined}</code>
<b>⚠️ Errors:</b> <code>{errors}</code>"""

                try:
                    await loader_msg.edit(progress_msg, disable_web_page_preview=True)
                except:
                    pass

        end_time = time.time()
        total_time = round(end_time - start_time, 2)

        # Deduct credits
        if user_data["plan"].get("credits") != "∞":
            from asyncio import get_event_loop
            loop = get_event_loop()
            await loop.run_in_executor(None, deduct_credit_bulk, user_id, card_count)

        # Final summary
        from datetime import datetime
        current_time = datetime.now().strftime("%I:%M %p")

        # Show last 10 results
        recent_results = results[-10:]
        results_text = "\n".join([
            f"{r['emoji']} <code>{r['card']}</code> | <code>{r['response'][:30]}</code>"
            for r in recent_results
        ])

        final_message = f"""<pre>━━━ Mass Braintree Charge ━━━</pre>
<b>Total Cards:</b> <code>{card_count}</code>
<b>Progress:</b> <code>{card_count}/{card_count}</code> ✓
<b>Gateway:</b> <code>Braintree [Pixorize $29.99]</code>

<b>Results (Last 10):</b>
{results_text}
━━━━━━━━━━━━━━━
<b>✅ Approved:</b> <code>{approved}</code>
<b>❌ Declined:</b> <code>{declined}</code>
<b>⚠️ Errors:</b> <code>{errors}</code>

<b>⏱️ Total Time:</b> <code>{total_time}s</code>
<b>Checked By:</b> {checked_by} [<code>{plan} {badge}</code>]
<b>Dev:</b> <a href="https://t.me/Chr1shtopher">Chr1shtopher</a> <code>{current_time}</code>"""

        # Add buttons
        buttons = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Support", url="https://t.me/Chr1shtopher"),
                InlineKeyboardButton("Plans", callback_data="plans_info")
            ]
        ])

        await loader_msg.edit(final_message, reply_markup=buttons, disable_web_page_preview=True)

    except Exception as e:
        print(f"Error in $mbr command: {str(e)}")
        import traceback
        traceback.print_exc()
        await message.reply(
            f"<b>⚠️ An error occurred:</b>\n<code>{str(e)}</code>",
            reply_to_message_id=message.id
        )

    finally:
        user_locks.pop(user_id, None)
