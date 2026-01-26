"""
Queue Status Command
Provides real-time monitoring of the Global Priority Queue.
"""

from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from BOT.helper.start import load_users
from BOT.queue.manager import Priority


@Client.on_message(filters.command(["qstatus", "queuestatus", "qs"]))
async def queue_status_handler(client, message):
    """
    Display global queue statistics.

    Shows:
    - Queue size and worker count
    - Priority breakdown
    - Processing statistics
    - User's position in queue
    """
    if not message.from_user:
        return

    user_id = str(message.from_user.id)
    users = load_users()

    if user_id not in users:
        return await message.reply(
            "<pre>Access Denied 🚫</pre>\n"
            "<b>You have to register first using</b> <code>/register</code> <b>command.</b>",
            reply_to_message_id=message.id,
            parse_mode=ParseMode.HTML
        )

    try:
        from BOT.queue.manager import get_global_queue

        queue = await get_global_queue()
        stats = await queue.get_queue_stats()
        user_pos = await queue.get_user_position(user_id)

        # Priority breakdown
        priority_breakdown = stats.get("priority_breakdown", {})
        priority_lines = []
        for p in sorted(priority_breakdown.keys()):
            try:
                p_name = Priority(p).name
            except ValueError:
                p_name = f"P{p}"
            priority_lines.append(f"    <code>{p_name} (P{p})</code>: <code>{priority_breakdown[p]}</code>")

        priority_text = "\n".join(priority_lines) if priority_lines else "    <code>Empty</code>"

        # Calculate queue health
        queue_size = stats.get("queue_size", 0)
        max_workers = stats.get("max_workers", 500)
        health = "🟢 Healthy"
        if queue_size > max_workers * 2:
            health = "🟡 Busy"
        if queue_size > max_workers * 5:
            health = "🔴 Overloaded"

        # User position info
        user_tasks = user_pos.get("tasks_in_queue", 0)
        user_position = user_pos.get("estimated_position", 0)
        user_info = f"<code>{user_tasks}</code> tasks"
        if user_position > 0:
            user_info += f" (position ~<code>{user_position}</code>)"

        status_msg = f"""<pre>📊 Global Queue Status</pre>
━━━━━━━━━━━━━━━

<b>🔄 Queue Overview</b>
    <b>Status:</b> {health}
    <b>Queue Size:</b> <code>{queue_size}</code> cards
    <b>Active Batches:</b> <code>{stats.get('active_batches', 0)}</code>
    <b>Global Workers:</b> <code>{max_workers}</code>

<b>📈 Processing Stats</b>
    <b>Total Queued:</b> <code>{stats.get('total_queued', 0)}</code>
    <b>Total Processed:</b> <code>{stats.get('total_processed', 0)}</code>
    <b>Total Charged:</b> <code>{stats.get('total_charged', 0)}</code>
    <b>Total Approved:</b> <code>{stats.get('total_approved', 0)}</code>

<b>🎯 Priority Breakdown</b>
{priority_text}

<b>👤 Your Tasks</b>
    <b>In Queue:</b> {user_info}

━━━━━━━━━━━━━━━
<b>Priority Levels:</b>
• <code>OWNER (P0)</code> - Highest
• <code>VIP (P1)</code>
• <code>ELITE (P2)</code>
• <code>PLUS (P3)</code>
• <code>STANDARD (P5)</code>
• <code>FREE (P10)</code> - Lowest

<i>Lower priority number = processed first</i>
━━━━━━━━━━━━━━━"""

        await message.reply(
            status_msg,
            reply_to_message_id=message.id,
            parse_mode=ParseMode.HTML
        )

    except Exception as e:
        await message.reply(
            f"<b>⚠️ Error getting queue status:</b>\n<code>{str(e)}</code>",
            reply_to_message_id=message.id,
            parse_mode=ParseMode.HTML
        )


@Client.on_message(filters.command(["qpos", "queuepos", "myqueue"]))
async def queue_position_handler(client, message):
    """
    Show user's position in the queue.
    """
    if not message.from_user:
        return

    user_id = str(message.from_user.id)
    users = load_users()

    if user_id not in users:
        return await message.reply(
            "<pre>Access Denied 🚫</pre>\n"
            "<b>You have to register first using</b> <code>/register</code> <b>command.</b>",
            reply_to_message_id=message.id,
            parse_mode=ParseMode.HTML
        )

    try:
        from BOT.queue.manager import get_global_queue, get_priority_for_plan

        queue = await get_global_queue()
        user_pos = await queue.get_user_position(user_id)
        stats = await queue.get_queue_stats()

        user_data = users[user_id]
        plan = user_data.get("plan", {}).get("plan", "Free")
        priority = get_priority_for_plan(plan)

        user_tasks = user_pos.get("tasks_in_queue", 0)
        position = user_pos.get("estimated_position", 0)

        if user_tasks == 0:
            status_msg = f"""<pre>📍 Your Queue Position</pre>
━━━━━━━━━━━━━━━

<b>Status:</b> <code>No tasks in queue</code>

<b>Your Plan:</b> <code>{plan}</code>
<b>Your Priority:</b> <code>P{priority}</code>

<b>Queue Size:</b> <code>{stats.get('queue_size', 0)}</code>
<b>Workers:</b> <code>{stats.get('max_workers', 500)}</code>

━━━━━━━━━━━━━━━
<i>Use /msh or /mst to add cards to the queue</i>"""
        else:
            eta = "Processing now" if position <= stats.get('max_workers', 500) else f"~{position // 50}s"
            status_msg = f"""<pre>📍 Your Queue Position</pre>
━━━━━━━━━━━━━━━

<b>Your Tasks:</b> <code>{user_tasks}</code>
<b>Position:</b> <code>~{position}</code>
<b>ETA:</b> <code>{eta}</code>

<b>Your Plan:</b> <code>{plan}</code>
<b>Your Priority:</b> <code>P{priority}</code>

<b>Queue Size:</b> <code>{stats.get('queue_size', 0)}</code>
<b>Workers:</b> <code>{stats.get('max_workers', 500)}</code>

━━━━━━━━━━━━━━━
<i>Higher priority (lower number) = processed first</i>"""

        await message.reply(
            status_msg,
            reply_to_message_id=message.id,
            parse_mode=ParseMode.HTML
        )

    except Exception as e:
        await message.reply(
            f"<b>⚠️ Error:</b>\n<code>{str(e)}</code>",
            reply_to_message_id=message.id,
            parse_mode=ParseMode.HTML
        )
