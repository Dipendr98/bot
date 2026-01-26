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
import re, asyncio, httpx, os, random

from BOT.db.store import get_proxy as _get_proxies, set_proxy as _set_proxy, delete_proxy as _delete_proxy, add_proxies as _add_proxies


def normalize_proxy(proxy_raw: str) -> str:
    proxy_raw = proxy_raw.strip()

    # 1. Already full proxy URL
    if proxy_raw.startswith("http://") or proxy_raw.startswith("https://"):
        return proxy_raw

    # 2. Format: USER:PASS@HOST:PORT
    match1 = re.fullmatch(r"(.+?):(.+?)@([a-zA-Z0-9\.\-]+):(\d+)", proxy_raw)
    if match1:
        user, pwd, host, port = match1.groups()
        return f"http://{user}:{pwd}@{host}:{port}"

    # 3. Format: HOST:PORT:USER:PASS
    match2 = re.fullmatch(r"([a-zA-Z0-9\.\-]+):(\d+):(.+?):(.+)", proxy_raw)
    if match2:
        host, port, user, pwd = match2.groups()
        return f"http://{user}:{pwd}@{host}:{port}"

    return None

async def get_ip(proxy_url: str):
    try:
        async with httpx.AsyncClient(
            proxies=proxy_url,     # ✅ works with httpx==0.27.2
            timeout=10,
            follow_redirects=True,
        ) as client:
            res = await client.get("https://ipinfo.io/json")
            res.raise_for_status()
            return res.json().get("ip"), None
    except Exception as e:
        return None, str(e)

def get_proxy(user_id: int | str) -> str | None:
    """Return user's proxy from store (MongoDB or JSON). Used by checks, addurl, txturl."""
    # Legacy wrapper: only returns first proxy for backward compatibility if needed
    # But usually checks should use get_rotating_proxy
    p = _get_proxies(str(user_id))
    if p and isinstance(p, list) and len(p) > 0:
        return p[0]
    return None

def get_rotating_proxy(user_id: int | str) -> str | None:
    """Get a random proxy from user's list."""
    proxies = _get_proxies(str(user_id))  # Now returns list
    if not proxies:
        return None
    return random.choice(proxies)

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
        from pyrogram.enums import ParseMode
        proxy_count = len(proxies)
        
        if proxy_count == 1:
            # Single proxy - show details
            proxy = proxies[0]
            proxy_clean = (proxy or "").replace("http://", "").replace("https://", "")
            if "@" not in proxy_clean:
                return await message.reply(
                    f"<b>Proxy stored ✓</b>\n<code>{proxy_clean[:60]}...</code>" 
                    if len(proxy_clean) > 60 else f"<b>Proxy stored ✓</b>\n<code>{proxy_clean}</code>"
                )
            creds, hostport = proxy_clean.split("@", 1)
            username = creds.split(":")[0]
            host = hostport.split(":")[0]

            await message.reply(
                f"<pre>Proxy | {user_id}</pre>\n"
                f"<b>✦ Username:</b> <code>{username}</code>\n"
                f"<b>✦ Host:</b> <code>{host}</code>\n"
                f"<b>✦ Total:</b> <code>1</code>\n"
                f"<b>✦ Rotation:</b> <code>Enabled</code>",
                parse_mode=ParseMode.HTML
            )
        else:
            # Multiple proxies - show all with rotation info
            preview_lines = []
            for i, proxy in enumerate(proxies[:10], 1):
                proxy_clean = (proxy or "").replace("http://", "").replace("https://", "")
                if "@" in proxy_clean:
                    creds, hostport = proxy_clean.split("@", 1)
                    username = creds.split(":")[0]
                    host = hostport.split(":")[0]
                    preview_lines.append(f"<b>{i}.</b> <code>{host}</code> (<code>{username}</code>)")
                else:
                    host = proxy_clean.split(":")[0] if ":" in proxy_clean else proxy_clean[:30]
                    preview_lines.append(f"<b>{i}.</b> <code>{host}</code>")
            
            more_text = f"\n<i>... and {proxy_count - 10} more proxy(ies)</i>" if proxy_count > 10 else ""
            
            await message.reply(
                f"<pre>Proxies | {user_id}</pre>\n"
                f"<b>Total:</b> <code>{proxy_count}</code>\n"
                f"<b>Rotation:</b> <code>Enabled (Random Selection)</code>\n\n"
                f"<b>Proxy List:</b>\n" + "\n".join(preview_lines) + more_text + "\n\n"
                f"<i>Each request uses a random proxy from this list for better distribution.</i>",
                parse_mode=ParseMode.HTML
            )
    except Exception as e:
        await message.reply(f"❌ Failed to parse proxies.\n<code>{e}</code>")
