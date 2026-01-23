import re
from pyrogram import Client, filters
from time import time
import asyncio
from BOT.Auth.StripeWC.api import async_check_stripe_wc
from BOT.helper.start import load_users
from BOT.helper.permissions import check_private_access, is_premium_user
from BOT.gc.credit import deduct_credit_bulk

user_locks = {}

@Client.on_message(filters.command("mswc") | filters.regex(r"^\$mswc(\s|$)"))
async def handle_mswc_command(client, message):
    """Handle mass Stripe WooCommerce Auth command: $mswc cc|mes|ano|cvv or $mswc cc|mes|ano|cvv site"""

    user_id = str(message.from_user.id)

    # Check if user has ongoing request
    if user_id in user_locks:
        return await message.reply(
            "<pre>⚠️ Wait!</pre>\n"
            "<b>Your previous</b> <code>$mswc</code> <b>request is still processing.</b>\n"
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

        # Extract site from command if provided
        site = None
        command_parts = message.text.split()
        if len(command_parts) > 1 and command_parts[-1].startswith("http"):
            site = command_parts[-1]

        # Extract cards
        target_text = None
        if message.reply_to_message and message.reply_to_message.text:
            target_text = message.reply_to_message.text
        elif len(message.text.split(maxsplit=1)) > 1:
            target_text = message.text.split(maxsplit=1)[1]

        if not target_text:
            return await message.reply(
                "❌ <b>Send cards in format:</b>\n<code>$mswc cc|mes|ano|cvv</code>\n"
                "<code>$mswc cc|mes|ano|cvv site</code>\n\n"
                "<b>Examples:</b>\n"
                "<code>$mswc 5312590016282230|12|2029|702\n5312590016282231|11|2028|701</code>\n"
                "<code>$mswc 5312590016282230|12|2029|702 https://epicalarc.com</code>",
                reply_to_message_id=message.id
            )

        # Find all cards
        cards = re.findall(r'(\d{12,19})\|(\d{1,2})\|(\d{2,4})\|(\d{3,4})', target_text)

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

        gateway = "Stripe WooCommerce Auth"
        if site:
            gateway = f"Stripe WC [{site.split('/')[2]}]"

        checked_by = f"<a href='tg://user?id={message.from_user.id}'>{message.from_user.first_name}</a>"

        # Initialize counters
        approved = 0
        declined = 0
        errors = 0
        results = []

        # Send initial message
        loader_msg = await message.reply(
            f"""<pre>━━━ Mass Stripe WooCommerce Auth ━━━</pre>
<b>Total Cards:</b> <code>{card_count}</code>
<b>Progress:</b> <code>0/{card_count}</code>
<b>Site:</b> <code>{site if site else 'epicalarc.com'}</code>

<b>Status:</b> <code>Starting...</code>
━━━━━━━━━━━━━━━
<b>Approved:</b> <code>0</code>
<b>Declined:</b> <code>0</code>
<b>Errors:</b> <code>0</code>""",
            reply_to_message_id=message.id
        )

        start_time = time()

        # Process each card
        for idx, (card, mes, ano, cvv) in enumerate(cards, 1):
            fullcc = f"{card}|{mes}|{ano}|{cvv}"

            # Check card
            result = await async_check_stripe_wc(card, mes, ano, cvv, site)
            status = result.get("status", "error")
            response = result.get("response", "Unknown")

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

                progress_msg = f"""<pre>━━━ Mass Stripe WooCommerce Auth ━━━</pre>
<b>Total Cards:</b> <code>{card_count}</code>
<b>Progress:</b> <code>{idx}/{card_count}</code>
<b>Site:</b> <code>{site if site else 'epicalarc.com'}</code>

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

        end_time = time()
        total_time = round(end_time - start_time, 2)

        # Deduct credits
        if user_data["plan"].get("credits") != "∞":
            loop = asyncio.get_event_loop()
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

        final_message = f"""<pre>━━━ Mass Stripe WooCommerce Auth ━━━</pre>
<b>Total Cards:</b> <code>{card_count}</code>
<b>Progress:</b> <code>{card_count}/{card_count}</code> ✓
<b>Site:</b> <code>{site if site else 'epicalarc.com'}</code>

<b>Results (Last 10):</b>
{results_text}
━━━━━━━━━━━━━━━
<b>✅ Approved:</b> <code>{approved}</code>
<b>❌ Declined:</b> <code>{declined}</code>
<b>⚠️ Errors:</b> <code>{errors}</code>

<b>⏱️ Total Time:</b> <code>{total_time}s</code>
<b>Gateway:</b> <code>{gateway}</code>
<b>Checked By:</b> {checked_by} [<code>{plan} {badge}</code>]
<b>Dev:</b> <a href="https://t.me/Chr1shtopher">Chr1shtopher</a> <code>{current_time}</code>"""

        await loader_msg.edit(final_message, disable_web_page_preview=True)

    except Exception as e:
        print(f"Error in $mswc command: {str(e)}")
        await message.reply(
            f"<b>⚠️ An error occurred:</b>\n<code>{str(e)}</code>",
            reply_to_message_id=message.id
        )

    finally:
        user_locks.pop(user_id, None)
