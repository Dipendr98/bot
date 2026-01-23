"""
TXT URL Handler
Handles multiple site management for card checking.
"""

import os
import json
import time
from typing import List, Dict

from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.enums import ParseMode

from BOT.Charge.Shopify.tls_session import TLSAsyncSession

TXT_SITES_PATH = "DATA/txtsite.json"
TEST_CARD = "4342562842964445|04|26|568"


def ensure_txt_sites_file():
    """Ensure txtsite.json exists."""
    if not os.path.exists(TXT_SITES_PATH):
        os.makedirs(os.path.dirname(TXT_SITES_PATH), exist_ok=True)
        with open(TXT_SITES_PATH, "w", encoding="utf-8") as f:
            json.dump({}, f)


def load_txt_sites() -> dict:
    """Load txt sites from file."""
    ensure_txt_sites_file()
    try:
        with open(TXT_SITES_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}


def save_txt_sites(data: dict):
    """Save txt sites to file."""
    ensure_txt_sites_file()
    with open(TXT_SITES_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)


async def validate_shopify_site(site_url: str, session: TLSAsyncSession) -> Dict:
    """
    Validate if a site is a working Shopify store.
    
    Returns dict with: valid, site, gateway, price
    """
    result = {
        "valid": False,
        "site": site_url,
        "gateway": "Unknown",
        "price": "N/A"
    }
    
    try:
        # Normalize URL
        if not site_url.startswith(("http://", "https://")):
            site_url = f"https://{site_url}"
        
        # Check products.json
        response = await session.get(
            f"{site_url}/products.json",
            follow_redirects=True,
            timeout=20
        )
        
        data = response.json()
        products = data.get("products", [])
        
        if not products:
            return result
        
        # Find available product with price
        for product in products:
            for variant in product.get("variants", []):
                if variant.get("available") and float(variant.get("price", 0)) > 0.10:
                    price = float(variant.get("price", 0))
                    result["price"] = f"{price:.2f}"
                    break
            if result["price"] != "N/A":
                break
        
        # Try to detect gateway
        home_response = await session.get(site_url, follow_redirects=True, timeout=15)
        
        # Extract gateway name
        text = home_response.text
        if '"extensibilityDisplayName":"' in text:
            start = text.index('"extensibilityDisplayName":"') + len('"extensibilityDisplayName":"')
            end = text.index('"', start)
            gateway = text[start:end]
            if gateway == "Shopify Payments":
                gateway = "Normal"
            result["gateway"] = gateway
        else:
            result["gateway"] = "Normal"
        
        result["valid"] = True
        result["site"] = site_url
        return result
        
    except Exception:
        return result


@Client.on_message(filters.command("txturl") & filters.private)
async def txturl_handler(client: Client, message: Message):
    """Add multiple sites for TXT checking."""
    args = message.command[1:]
    
    if not args:
        return await message.reply(
            """<pre>Usage Guide 📖</pre>
<b>Add multiple Shopify sites:</b>

<code>/txturl site1.com site2.com site3.com</code>

<b>Other Commands:</b>
• <code>/txtls</code> - List your TXT sites
• <code>/rurl site.com</code> - Remove a site""",
            parse_mode=ParseMode.HTML
        )
    
    user_id = str(message.from_user.id)
    clickable_name = f"<a href='tg://user?id={user_id}'>{message.from_user.first_name}</a>"
    start_time = time.time()
    
    wait_msg = await message.reply(
        f"<pre>🔍 Validating {len(args)} site(s)...</pre>",
        reply_to_message_id=message.id,
        parse_mode=ParseMode.HTML
    )
    
    # Load existing sites
    all_sites = load_txt_sites()
    user_sites = all_sites.get(user_id, [])
    existing_urls = {entry["site"] for entry in user_sites}
    
    supported_sites = []
    
    async with TLSAsyncSession(timeout_seconds=30) as session:
        for site in args[:10]:  # Limit to 10 sites
            if site in existing_urls:
                continue  # Skip duplicates
            
            try:
                result = await validate_shopify_site(site, session)
                if result["valid"]:
                    gateway = result.get("gateway", "Unknown")
                    price = result.get("price", "N/A")
                    gate_name = f"Shopify {gateway} ${price}"
                    supported_sites.append({
                        "site": result["site"],
                        "gate": gate_name
                    })
            except Exception:
                continue
    
    if not supported_sites:
        return await wait_msg.edit_text(
            "<pre>No Valid Sites Found ❌</pre>\n<b>Ensure the sites are Shopify stores with available products.</b>",
            parse_mode=ParseMode.HTML
        )
    
    # Save sites
    user_sites.extend(supported_sites)
    all_sites[user_id] = user_sites
    save_txt_sites(all_sites)
    
    # Build response
    result_lines = ["<pre>Sites Added ✅</pre>", "━━━━━━━━━━━━━"]
    
    for site_entry in supported_sites:
        result_lines.append(f"[⌯] <b>Site:</b> <code>{site_entry['site']}</code>")
        result_lines.append(f"[⌯] <b>Gateway:</b> <code>{site_entry['gate']}</code>")
        result_lines.append("")
    
    end_time = time.time()
    result_lines.append(f"[⌯] <b>Total Added:</b> <code>{len(supported_sites)}</code>")
    result_lines.append(f"[⌯] <b>Time:</b> <code>{round(end_time - start_time, 2)}s</code>")
    result_lines.append("━━━━━━━━━━━━━")
    result_lines.append(f"[⌯] <b>User:</b> {clickable_name}")
    
    await wait_msg.edit_text("\n".join(result_lines), parse_mode=ParseMode.HTML)


@Client.on_message(filters.command("txtls") & filters.private)
async def txtls_handler(client: Client, message: Message):
    """List user's TXT sites."""
    user_id = str(message.from_user.id)
    clickable_name = f"<a href='tg://user?id={user_id}'>{message.from_user.first_name}</a>"
    
    all_sites = load_txt_sites()
    user_sites = all_sites.get(user_id, [])
    
    if not user_sites:
        return await message.reply(
            "<pre>No Sites Found ℹ️</pre>\n<b>Use <code>/txturl site.com</code> to add sites.</b>",
            parse_mode=ParseMode.HTML
        )
    
    lines = ["<pre>Your TXT Sites 📋</pre>", "━━━━━━━━━━━━━"]
    
    for i, site_entry in enumerate(user_sites[:20], 1):  # Show max 20
        lines.append(f"<b>{i}.</b> <code>{site_entry['site']}</code>")
        lines.append(f"   <i>{site_entry.get('gate', 'Unknown')}</i>")
    
    if len(user_sites) > 20:
        lines.append(f"\n<i>... and {len(user_sites) - 20} more</i>")
    
    lines.append("━━━━━━━━━━━━━")
    lines.append(f"<b>Total:</b> <code>{len(user_sites)}</code> site(s)")
    lines.append(f"<b>User:</b> {clickable_name}")
    
    await message.reply("\n".join(lines), parse_mode=ParseMode.HTML)


@Client.on_message(filters.command("rurl") & filters.private)
async def rurl_handler(client: Client, message: Message):
    """Remove sites from TXT list."""
    args = message.command[1:]
    user_id = str(message.from_user.id)
    
    if not args:
        return await message.reply(
            "<b>Usage:</b> <code>/rurl site1.com site2.com</code>",
            parse_mode=ParseMode.HTML
        )
    
    all_sites = load_txt_sites()
    user_sites = all_sites.get(user_id, [])
    
    if not user_sites:
        return await message.reply(
            "<pre>No Sites Found ℹ️</pre>",
            parse_mode=ParseMode.HTML
        )
    
    # Track removed sites
    removed = []
    args_lower = [a.lower() for a in args]
    
    new_sites = []
    for entry in user_sites:
        site_lower = entry["site"].lower().replace("https://", "").replace("http://", "")
        if any(arg in site_lower or site_lower in arg for arg in args_lower):
            removed.append(entry["site"])
        else:
            new_sites.append(entry)
    
    all_sites[user_id] = new_sites
    save_txt_sites(all_sites)
    
    if removed:
        removed_list = "\n".join([f"• <code>{s}</code>" for s in removed[:5]])
        await message.reply(
            f"<pre>Sites Removed ✅</pre>\n{removed_list}",
            parse_mode=ParseMode.HTML
        )
    else:
        await message.reply(
            "<pre>No Matching Sites Found ❌</pre>",
            parse_mode=ParseMode.HTML
        )


@Client.on_message(filters.command("clearurl") & filters.private)
async def clearurl_handler(client: Client, message: Message):
    """Clear all TXT sites for user."""
    user_id = str(message.from_user.id)
    
    all_sites = load_txt_sites()
    
    if user_id in all_sites:
        count = len(all_sites[user_id])
        del all_sites[user_id]
        save_txt_sites(all_sites)
        
        await message.reply(
            f"<pre>All Sites Cleared ✅</pre>\n<b>Removed:</b> <code>{count}</code> site(s)",
            parse_mode=ParseMode.HTML
        )
    else:
        await message.reply(
            "<pre>No Sites Found ℹ️</pre>",
            parse_mode=ParseMode.HTML
        )
