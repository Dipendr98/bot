# from pyrogram import Client, filters
# from pyrogram.types import Message
# import json, re, os, asyncio, httpx

# PROXY_FILE = "DATA/proxy.json"

# def load_proxies():
#     return json.load(open(PROXY_FILE)) if os.path.exists(PROXY_FILE) else {}

# def save_proxies(data):
#     with open(PROXY_FILE, "w") as f:
#         json.dump(data, f, indent=2)

# def normalize_proxy(proxy_raw: str) -> str:
#     proxy_raw = proxy_raw.strip()

#     # 1. Already full proxy URL
#     if proxy_raw.startswith("http://") or proxy_raw.startswith("https://"):
#         return proxy_raw

#     # 2. Format: USER:PASS@HOST:PORT
#     match1 = re.fullmatch(r"(.+?):(.+?)@([a-zA-Z0-9\.\-]+):(\d+)", proxy_raw)
#     if match1:
#         user, pwd, host, port = match1.groups()
#         return f"http://{user}:{pwd}@{host}:{port}"

#     # 3. Format: HOST:PORT:USER:PASS
#     match2 = re.fullmatch(r"([a-zA-Z0-9\.\-]+):(\d+):(.+?):(.+)", proxy_raw)
#     if match2:
#         host, port, user, pwd = match2.groups()
#         return f"http://{user}:{pwd}@{host}:{port}"

#     return None

# async def get_ip(proxy_url):
#     try:
#         transport = httpx.AsyncHTTPTransport(proxy=proxy_url)
#         async with httpx.AsyncClient(transport=transport, timeout=10) as client:
#             res = await client.get("https://ipinfo.io/json")
#             if res.status_code == 200:
#                 return res.json().get("ip"), None
#             return None, res.status_code
#     except Exception as e:
#         return None, str(e)

# @Client.on_message(filters.command("setpx") & filters.private)
# async def set_proxy(client, message: Message):
#     if len(message.command) < 2:
#         return await message.reply("❌ Format: `/setpx proxy`", quote=True)

#     raw_proxy = message.text.split(maxsplit=1)[1].strip()
#     proxy_url = normalize_proxy(raw_proxy)

#     if not proxy_url:
#         return await message.reply("❌ Invalid proxy format.\nSupported:\n- IP:PORT:USER:PASS\n- USER:PASS@IP:PORT\n- Full proxy link", quote=True)

#     msg = await message.reply("⏳ Checking proxy quality...", quote=True)

#     ip1, err1 = await get_ip(proxy_url)
#     await asyncio.sleep(2)
#     ip2, err2 = await get_ip(proxy_url)

#     if not ip1 or not ip2:
#         err_msg = err1 or err2 or "Unknown error"
#         return await msg.edit(f"❌ Your proxy failed to connect.\n**Error:** `{err_msg}`")

#     if ip1 == ip2:
#         return await msg.edit(f"⚠️ Proxy connected, but both IPs are the same:\n`{ip1}`\n\nThis is **not a high-quality proxy**. Try rotating/resi proxy.")

#     # Save proxy for user
#     user_id = str(message.from_user.id)
#     data = load_proxies()
#     data[user_id] = proxy_url
#     save_proxies(data)

#     await msg.edit(f"✅ Proxy saved successfully!\n\n🔁 Rotated IPs:\n- `{ip1}`\n- `{ip2}`")

# def get_proxy(user_id: int) -> str | None:

#     if not os.path.exists(PROXY_FILE):
#         return None

#     try:
#         data = json.load(open(PROXY_FILE))
#         return data.get(str(user_id))
#     except Exception:
#         return None

from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.enums import ParseMode
import re, asyncio, httpx, os, random

from BOT.db.store import get_proxy as _get_proxies, set_proxy as _set_proxy, delete_proxy as _delete_proxy, add_proxies as _add_proxies, load_proxies, save_proxies

# Import advanced proxy manager
from BOT.tools.proxy_manager import (
    normalize_proxy,
    validate_proxy,
    test_proxy_rotation,
    bulk_test_proxies,
    get_rotator,
    get_rotating_proxy as _get_rotating_proxy_async,
    get_rotating_proxy_sync,
    record_proxy_result,
    set_rotation_strategy,
    get_rotation_strategy,
    get_proxy_stats,
    clear_bad_proxies,
    reset_proxy_health,
    enable_all_proxies,
    RotationStrategy,
)


async def get_ip(proxy_url: str):
    """Validate proxy and get IP. Returns (ip, error)."""
    success, result, _ = await validate_proxy(proxy_url, timeout=10)
    if success:
        return result, None
    return None, result


def get_proxy(user_id: int | str) -> str | None:
    """Return user's first proxy from store (MongoDB or JSON). Used by checks, addurl, txturl."""
    # Legacy wrapper: only returns first proxy for backward compatibility
    # For rotation, use get_rotating_proxy instead
    p = _get_proxies(str(user_id))
    if p and isinstance(p, list) and len(p) > 0:
        return p[0]
    return None


def get_rotating_proxy(user_id: int | str) -> str | None:
    """
    Get next proxy from user's list using rotation strategy.
    This is the sync version - use for non-async code.
    Health-aware: skips disabled proxies.
    """
    return get_rotating_proxy_sync(str(user_id))


async def get_rotating_proxy_async(user_id: int | str, session_key: str = None) -> str | None:
    """
    Async version of get_rotating_proxy with full rotation strategy support.
    Use this in async checkers for best performance.

    Args:
        user_id: User's ID
        session_key: Optional key for sticky sessions (same card = same proxy)
    """
    return await _get_rotating_proxy_async(str(user_id), session_key)

@Client.on_message(filters.command("setpx") & ~filters.private)
async def setpx_group_redirect(client, message: Message):
    """Redirect /setpx command in groups to private chat."""
    from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    from pyrogram.enums import ParseMode
    
    try:
        bot_info = await client.get_me()
        bot_username = bot_info.username
        bot_link = f"https://t.me/{bot_username}"
    except:
        bot_link = "https://t.me/"
    
    await message.reply(
        f"""<pre>🔒 Private Command</pre>
━━━━━━━━━━━━━━━
<b>This command only works in private chat.</b>

<b>Command:</b> <code>/setpx</code>
<b>Purpose:</b> Set proxy for mass checking

<b>How to use:</b>
1️⃣ Click the button below
2️⃣ Use <code>/setpx ip:port:user:pass</code> there

<b>Why private?</b>
• 🔐 Protects your proxy credentials
• ⚡ Secure configuration
━━━━━━━━━━━━━━━
<i>Your data security is our priority!</i>""",
        reply_to_message_id=message.id,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📱 Open Private Chat", url=bot_link)]
        ])
    )


@Client.on_message(filters.command("import_proxies") & filters.private)
async def import_proxies_handler(client, message: Message):
    if not message.reply_to_message or not message.reply_to_message.document:
        return await message.reply("❌ Reply to a .txt file containing proxies.", quote=True)
        
    doc = await message.reply_to_message.download()
    try:
        with open(doc, "r", encoding="utf-8") as f:
            lines = f.readlines()
            
        valid_proxies = []
        for line in lines:
            p = normalize_proxy(line.strip())
            if p: 
                valid_proxies.append(p)
            
        if not valid_proxies:
            return await message.reply("❌ No valid proxies found in file.", quote=True)
            
        count = _add_proxies(str(message.from_user.id), valid_proxies)
        await message.reply(f"✅ Imported **{count}** proxies successfully!", quote=True)
        
    finally:
        if os.path.exists(doc): 
            os.remove(doc)

@Client.on_message(filters.command("setpx") & filters.private)
async def set_proxy(client, message: Message):
    """Set proxy for mass checking. Private chat only for security. Adds to list if not exists."""
    if len(message.command) < 2:
        return await message.reply(
            """<pre>Proxy Setup 🔧</pre>
━━━━━━━━━━━━━
<b>Format:</b> <code>/setpx proxy</code>

<b>Supported Formats:</b>
• <code>ip:port:user:pass</code>
• <code>user:pass@ip:port</code>
• <code>http://user:pass@ip:port</code>

<b>Example:</b>
<code>/setpx 192.168.1.1:8080:user:pass</code>

<b>Note:</b> This adds the proxy to your list. Use <code>/import_proxies</code> to bulk import from file.
━━━━━━━━━━━━━""",
            quote=True
        )

    raw_proxy = message.text.split(maxsplit=1)[1].strip()
    proxy_url = normalize_proxy(raw_proxy)

    if not proxy_url:
        return await message.reply(
            "<pre>Invalid format ❌</pre>\n<b>Supported:</b>\n~ {ip}:{port}:{user}:{pass}\n~ {user}:{pass}@{ip}:{port}\n~ {protocol}://{user}:{pass}@{ip}:{port}",
            quote=True,
        )

    user_id = str(message.from_user.id)
    existing_proxies = _get_proxies(user_id)
    if existing_proxies and proxy_url in existing_proxies:
        return await message.reply("<b>This proxy is already added ⚠️</b>", quote=True)

    msg = await message.reply("<pre>Validating Proxy 🔘</pre>", quote=True)

    ip, err = await get_ip(proxy_url)

    if not ip:
        err_msg = err or "Unknown error"
        return await msg.edit(
            f"""<pre>Connection Failure ❌</pre>
━━━━━━━━━━━━━
<b>Error:</b> <code>{err_msg[:100]}</code>
━━━━━━━━━━━━━
<b>Tips:</b>
• Check if proxy is active
• Verify credentials are correct
• Try a different proxy"""
        )

    # Add to list instead of replacing
    added = _add_proxies(user_id, [proxy_url])
    total_count = len(_get_proxies(user_id))

    try:
        proxy_clean = proxy_url.replace("http://", "").replace("https://", "")
        if "@" in proxy_clean:
            creds, hostport = proxy_clean.split("@")
            host = hostport.split(":")[0]
            port = hostport.split(":")[1] if ":" in hostport else "N/A"
        else:
            host = proxy_clean.split(":")[0]
            port = proxy_clean.split(":")[1] if ":" in proxy_clean else "N/A"
    except:
        host = "N/A"
        port = "N/A"

    await msg.edit(
        f"""<pre>Proxy Added ✅</pre>
━━━━━━━━━━━━━
<b>[•] Host:</b> <code>{host}</code>
<b>[•] Port:</b> <code>{port}</code>
<b>[•] IP:</b> <code>{ip}</code>
<b>[•] Status:</b> <code>Active ✓</code>
<b>[•] Total Proxies:</b> <code>{total_count}</code>
━━━━━━━━━━━━━
<b>Ready for mass checking!</b>"""
    )

@Client.on_message(filters.command("delpx"))
async def delete_proxy(client, message: Message):
    user_id = str(message.from_user.id)
    if not _get_proxies(user_id):
        return await message.reply("<b>No proxy was found to delete !!!</b>", quote=True)
    _delete_proxy(user_id)
    await message.reply("<b>All your proxies have been removed ✅</b>", quote=True)

@Client.on_message(filters.command("getpx"))
async def getpx_handler(client, message):
    user_id = str(message.from_user.id)
    proxies = _get_proxies(user_id)

    if not proxies:
        return await message.reply("<b>You haven't set any proxy yet ❌</b>")

    try:
        proxy_count = len(proxies)
        strategy = get_rotation_strategy(user_id)
        strategy_display = strategy.replace("_", " ").title()

        # Get stats for health info
        stats = get_proxy_stats(user_id)

        if proxy_count == 1:
            # Single proxy - show details
            proxy = proxies[0]
            proxy_clean = (proxy or "").replace("http://", "").replace("https://", "")
            if "@" not in proxy_clean:
                return await message.reply(
                    f"<b>Proxy stored ✓</b>\n<code>{proxy_clean[:60]}...</code>"
                    if len(proxy_clean) > 60 else f"<b>Proxy stored ✓</b>\n<code>{proxy_clean}</code>",
                    parse_mode=ParseMode.HTML
                )
            creds, hostport = proxy_clean.split("@", 1)
            username = creds.split(":")[0]
            host = hostport.split(":")[0]

            await message.reply(
                f"<pre>Proxy | {user_id}</pre>\n"
                f"<b>✦ Username:</b> <code>{username}</code>\n"
                f"<b>✦ Host:</b> <code>{host}</code>\n"
                f"<b>✦ Total:</b> <code>1</code>\n"
                f"<b>✦ Strategy:</b> <code>{strategy_display}</code>\n"
                f"<b>✦ Status:</b> <code>Active</code>",
                parse_mode=ParseMode.HTML
            )
        else:
            # Multiple proxies - show all with rotation info
            preview_lines = []
            for i, proxy in enumerate(proxies[:10], 1):
                proxy_clean = (proxy or "").replace("http://", "").replace("https://", "")
                # Get health status
                p_stats = next((p for p in stats["proxies"] if proxy in p.get("proxy_full", p.get("proxy", ""))), None)
                status_icon = "🟢" if not p_stats or p_stats.get("status") == "Active" else "🔴"

                if "@" in proxy_clean:
                    creds, hostport = proxy_clean.split("@", 1)
                    username = creds.split(":")[0]
                    host = hostport.split(":")[0]
                    preview_lines.append(f"<b>{i}.</b> {status_icon} <code>{host}</code> (<code>{username[:8]}...</code>)")
                else:
                    host = proxy_clean.split(":")[0] if ":" in proxy_clean else proxy_clean[:30]
                    preview_lines.append(f"<b>{i}.</b> {status_icon} <code>{host}</code>")

            more_text = f"\n<i>... and {proxy_count - 10} more proxy(ies)</i>" if proxy_count > 10 else ""

            await message.reply(
                f"<pre>Proxies | {user_id}</pre>\n"
                f"<b>Total:</b> <code>{proxy_count}</code>\n"
                f"<b>Active:</b> <code>{stats['active_count']}</code> | <b>Disabled:</b> <code>{stats['disabled_count']}</code>\n"
                f"<b>Strategy:</b> <code>{strategy_display}</code>\n"
                f"<b>Success Rate:</b> <code>{stats['overall_success_rate']}</code>\n\n"
                f"<b>Proxy List:</b>\n" + "\n".join(preview_lines) + more_text + "\n\n"
                f"<i>Use /pxstats for detailed stats, /pxhelp for all commands.</i>",
                parse_mode=ParseMode.HTML
            )
    except Exception as e:
        await message.reply(f"❌ Failed to parse proxies.\n<code>{e}</code>")


# ============================================================================
# New Advanced Proxy Commands
# ============================================================================

@Client.on_message(filters.command("testpx") & filters.private)
async def test_proxies_handler(client, message: Message):
    """Test all user proxies and show results."""
    user_id = str(message.from_user.id)
    proxies = _get_proxies(user_id)

    if not proxies:
        return await message.reply(
            "<pre>No Proxies Found</pre>\n"
            "Add proxies using <code>/setpx</code> or <code>/import_proxies</code>",
            parse_mode=ParseMode.HTML
        )

    msg = await message.reply(
        f"<pre>Testing {len(proxies)} Proxies...</pre>\n"
        "<i>This may take a moment...</i>",
        parse_mode=ParseMode.HTML
    )

    results = await bulk_test_proxies(proxies, timeout=15)

    # Build result message
    success_count = sum(1 for r in results if r["success"])
    fail_count = len(results) - success_count

    lines = []
    for i, r in enumerate(results[:15], 1):
        if r["success"]:
            latency = f"{r['latency_ms']:.0f}ms" if r['latency_ms'] else "N/A"
            lines.append(f"<b>{i}.</b> {r['proxy']} - <code>Active</code> ({latency})")
        else:
            error = (r.get('error') or 'Unknown')[:30]
            lines.append(f"<b>{i}.</b> {r['proxy']} - <code>Failed</code> ({error})")

    more_text = f"\n<i>... and {len(results) - 15} more</i>" if len(results) > 15 else ""

    await msg.edit(
        f"<pre>Proxy Test Results</pre>\n"
        f"━━━━━━━━━━━━━\n"
        f"<b>Total:</b> <code>{len(proxies)}</code>\n"
        f"<b>Active:</b> <code>{success_count}</code>\n"
        f"<b>Failed:</b> <code>{fail_count}</code>\n"
        f"━━━━━━━━━━━━━\n"
        f"<b>Results:</b>\n" + "\n".join(lines) + more_text + "\n\n"
        f"<i>Use /clearbadpx to remove failed proxies</i>",
        parse_mode=ParseMode.HTML
    )


@Client.on_message(filters.command("pxstats") & filters.private)
async def proxy_stats_handler(client, message: Message):
    """Show proxy statistics and health metrics."""
    user_id = str(message.from_user.id)
    proxies = _get_proxies(user_id)

    if not proxies:
        return await message.reply(
            "<pre>No Proxies Found</pre>\n"
            "Add proxies using <code>/setpx</code> or <code>/import_proxies</code>",
            parse_mode=ParseMode.HTML
        )

    stats = get_proxy_stats(user_id)

    # Build stats display
    lines = []
    for i, p in enumerate(stats["proxies"][:10], 1):
        status_icon = "🟢" if p["status"] == "Active" else "🔴"
        lines.append(
            f"<b>{i}.</b> {p['proxy']}\n"
            f"   {status_icon} {p['status']} | <code>{p['success']}</code>/<code>{p['fail']}</code> | {p['success_rate']} | {p['avg_latency']}"
        )

    more_text = f"\n<i>... and {len(stats['proxies']) - 10} more</i>" if len(stats["proxies"]) > 10 else ""

    strategy_display = stats["strategy"].replace("_", " ").title()

    await message.reply(
        f"<pre>Proxy Statistics</pre>\n"
        f"━━━━━━━━━━━━━\n"
        f"<b>Total Proxies:</b> <code>{stats['total_proxies']}</code>\n"
        f"<b>Active:</b> <code>{stats['active_count']}</code> | <b>Disabled:</b> <code>{stats['disabled_count']}</code>\n"
        f"<b>Total Requests:</b> <code>{stats['total_success'] + stats['total_fail']}</code>\n"
        f"<b>Success Rate:</b> <code>{stats['overall_success_rate']}</code>\n"
        f"<b>Strategy:</b> <code>{strategy_display}</code>\n"
        f"━━━━━━━━━━━━━\n"
        f"<b>Proxy Health:</b> (Success/Fail | Rate | Latency)\n" + "\n".join(lines) + more_text + "\n\n"
        f"<b>Commands:</b>\n"
        f"• <code>/setrotation &lt;strategy&gt;</code> - Change rotation\n"
        f"• <code>/clearbadpx</code> - Remove failed proxies\n"
        f"• <code>/enablepx</code> - Re-enable all proxies\n"
        f"• <code>/resetpx</code> - Reset health stats",
        parse_mode=ParseMode.HTML
    )


@Client.on_message(filters.command("setrotation") & filters.private)
async def set_rotation_handler(client, message: Message):
    """Set proxy rotation strategy."""
    user_id = str(message.from_user.id)

    strategies = {
        "random": "Random selection from pool",
        "round_robin": "Sequential rotation through list",
        "weighted": "Prefer proxies with higher success rates",
        "least_used": "Use least recently used proxy",
        "fastest": "Prefer proxies with lowest latency",
    }

    if len(message.command) < 2:
        current = get_rotation_strategy(user_id)
        strat_list = "\n".join([f"• <code>{k}</code> - {v}" for k, v in strategies.items()])
        return await message.reply(
            f"<pre>Proxy Rotation Strategy</pre>\n"
            f"━━━━━━━━━━━━━\n"
            f"<b>Current:</b> <code>{current}</code>\n\n"
            f"<b>Available Strategies:</b>\n{strat_list}\n\n"
            f"<b>Usage:</b> <code>/setrotation &lt;strategy&gt;</code>\n"
            f"<b>Example:</b> <code>/setrotation weighted</code>",
            parse_mode=ParseMode.HTML
        )

    strategy = message.command[1].lower()

    if strategy not in strategies:
        return await message.reply(
            f"<b>Invalid strategy!</b>\n"
            f"Available: <code>{', '.join(strategies.keys())}</code>",
            parse_mode=ParseMode.HTML
        )

    if set_rotation_strategy(user_id, strategy):
        await message.reply(
            f"<pre>Rotation Strategy Updated</pre>\n"
            f"━━━━━━━━━━━━━\n"
            f"<b>Strategy:</b> <code>{strategy}</code>\n"
            f"<b>Description:</b> {strategies[strategy]}",
            parse_mode=ParseMode.HTML
        )
    else:
        await message.reply("<b>Failed to set rotation strategy</b>")


@Client.on_message(filters.command("clearbadpx") & filters.private)
async def clear_bad_proxies_handler(client, message: Message):
    """Remove disabled/failed proxies."""
    user_id = str(message.from_user.id)
    proxies = _get_proxies(user_id)

    if not proxies:
        return await message.reply("<b>No proxies to clean</b>")

    removed = clear_bad_proxies(user_id)

    if removed > 0:
        remaining = len(_get_proxies(user_id))
        await message.reply(
            f"<pre>Proxy Cleanup Complete</pre>\n"
            f"━━━━━━━━━━━━━\n"
            f"<b>Removed:</b> <code>{removed}</code> bad proxy(ies)\n"
            f"<b>Remaining:</b> <code>{remaining}</code> proxy(ies)",
            parse_mode=ParseMode.HTML
        )
    else:
        await message.reply(
            "<pre>No Bad Proxies Found</pre>\n"
            "All your proxies are healthy!",
            parse_mode=ParseMode.HTML
        )


@Client.on_message(filters.command("enablepx") & filters.private)
async def enable_proxies_handler(client, message: Message):
    """Re-enable all disabled proxies."""
    user_id = str(message.from_user.id)
    proxies = _get_proxies(user_id)

    if not proxies:
        return await message.reply("<b>No proxies found</b>")

    enable_all_proxies(user_id)
    await message.reply(
        f"<pre>Proxies Re-enabled</pre>\n"
        f"━━━━━━━━━━━━━\n"
        f"<b>All {len(proxies)} proxies are now active!</b>\n\n"
        f"<i>Disabled proxies have been re-enabled and their cooldown reset.</i>",
        parse_mode=ParseMode.HTML
    )


@Client.on_message(filters.command("resetpx") & filters.private)
async def reset_proxy_health_handler(client, message: Message):
    """Reset proxy health statistics."""
    user_id = str(message.from_user.id)
    proxies = _get_proxies(user_id)

    if not proxies:
        return await message.reply("<b>No proxies found</b>")

    reset_proxy_health(user_id)
    await message.reply(
        f"<pre>Proxy Health Reset</pre>\n"
        f"━━━━━━━━━━━━━\n"
        f"<b>Reset stats for {len(proxies)} proxies!</b>\n\n"
        f"<i>All success/failure counts and latency data cleared.</i>",
        parse_mode=ParseMode.HTML
    )


@Client.on_message(filters.command("rmpx") & filters.private)
async def remove_single_proxy_handler(client, message: Message):
    """Remove a specific proxy by index."""
    user_id = str(message.from_user.id)
    proxies = _get_proxies(user_id)

    if not proxies:
        return await message.reply("<b>No proxies found</b>")

    if len(message.command) < 2:
        return await message.reply(
            f"<pre>Remove Proxy</pre>\n"
            f"━━━━━━━━━━━━━\n"
            f"<b>Usage:</b> <code>/rmpx &lt;index&gt;</code>\n"
            f"<b>Example:</b> <code>/rmpx 1</code> - Remove first proxy\n\n"
            f"<i>Use /getpx to see proxy indices</i>",
            parse_mode=ParseMode.HTML
        )

    try:
        idx = int(message.command[1]) - 1  # Convert to 0-based
        if idx < 0 or idx >= len(proxies):
            return await message.reply(
                f"<b>Invalid index!</b>\nValid range: 1-{len(proxies)}",
                parse_mode=ParseMode.HTML
            )

        removed_proxy = proxies[idx]
        proxies.pop(idx)

        # Save updated list
        data = load_proxies()
        data[user_id] = proxies
        save_proxies(data)

        # Clean up health record
        reset_proxy_health(user_id, removed_proxy)

        # Mask proxy for display
        proxy_display = removed_proxy.replace("http://", "").replace("https://", "")
        if "@" in proxy_display:
            creds, hostport = proxy_display.split("@", 1)
            proxy_display = f"{creds.split(':')[0][:3]}***@{hostport}"

        await message.reply(
            f"<pre>Proxy Removed</pre>\n"
            f"━━━━━━━━━━━━━\n"
            f"<b>Removed:</b> <code>{proxy_display}</code>\n"
            f"<b>Remaining:</b> <code>{len(proxies)}</code> proxy(ies)",
            parse_mode=ParseMode.HTML
        )

    except ValueError:
        await message.reply("<b>Please provide a valid number</b>")


@Client.on_message(filters.command("checkrotation") & filters.private)
async def check_rotation_handler(client, message: Message):
    """Test if a proxy provides IP rotation."""
    user_id = str(message.from_user.id)

    if len(message.command) < 2:
        # Test user's first proxy
        proxies = _get_proxies(user_id)
        if not proxies:
            return await message.reply(
                "<pre>No Proxy Set</pre>\n"
                "Add a proxy first using <code>/setpx</code>",
                parse_mode=ParseMode.HTML
            )
        proxy_url = proxies[0]
    else:
        raw_proxy = message.text.split(maxsplit=1)[1].strip()
        proxy_url = normalize_proxy(raw_proxy)
        if not proxy_url:
            return await message.reply(
                "<b>Invalid proxy format!</b>\n"
                "Supported: ip:port:user:pass, user:pass@ip:port, or full URL",
                parse_mode=ParseMode.HTML
            )

    msg = await message.reply(
        "<pre>Testing IP Rotation...</pre>\n"
        "<i>Making 3 test requests...</i>",
        parse_mode=ParseMode.HTML
    )

    is_rotating, ips, status = await test_proxy_rotation(proxy_url, test_count=3)

    if not ips:
        await msg.edit(
            f"<pre>Rotation Test Failed</pre>\n"
            f"━━━━━━━━━━━━━\n"
            f"<b>Error:</b> <code>{status}</code>",
            parse_mode=ParseMode.HTML
        )
        return

    rotation_icon = "🔄" if is_rotating else "📌"
    rotation_type = "Rotating" if is_rotating else "Static"

    ip_list = "\n".join([f"• <code>{ip}</code>" for ip in ips])

    await msg.edit(
        f"<pre>IP Rotation Test</pre>\n"
        f"━━━━━━━━━━━━━\n"
        f"{rotation_icon} <b>Type:</b> <code>{rotation_type}</code>\n"
        f"<b>Unique IPs:</b> <code>{len(ips)}</code>\n\n"
        f"<b>IPs Detected:</b>\n{ip_list}\n\n"
        f"<i>{status}</i>",
        parse_mode=ParseMode.HTML
    )


@Client.on_message(filters.command("pxhelp") & filters.private)
async def proxy_help_handler(client, message: Message):
    """Show all proxy commands."""
    await message.reply(
        """<pre>Proxy Commands</pre>
━━━━━━━━━━━━━
<b>Basic Commands:</b>
• <code>/setpx &lt;proxy&gt;</code> - Add a proxy
• <code>/getpx</code> - View your proxies
• <code>/delpx</code> - Delete all proxies
• <code>/rmpx &lt;index&gt;</code> - Remove specific proxy
• <code>/import_proxies</code> - Bulk import from file

<b>Testing Commands:</b>
• <code>/testpx</code> - Test all proxies
• <code>/checkrotation</code> - Test IP rotation

<b>Statistics & Health:</b>
• <code>/pxstats</code> - View proxy statistics
• <code>/clearbadpx</code> - Remove failed proxies
• <code>/enablepx</code> - Re-enable disabled proxies
• <code>/resetpx</code> - Reset health stats

<b>Rotation Settings:</b>
• <code>/setrotation &lt;strategy&gt;</code> - Set rotation mode

<b>Rotation Strategies:</b>
• <code>random</code> - Random selection (default)
• <code>round_robin</code> - Sequential rotation
• <code>weighted</code> - Prefer high success rate
• <code>least_used</code> - Use least recent proxy
• <code>fastest</code> - Prefer low latency

<b>Supported Proxy Formats:</b>
• <code>ip:port:user:pass</code>
• <code>user:pass@ip:port</code>
• <code>http://user:pass@ip:port</code>
• <code>socks5://user:pass@ip:port</code>
━━━━━━━━━━━━━
<i>Pro tip: Use rotating/residential proxies for best results!</i>""",
        parse_mode=ParseMode.HTML
    )
