"""
TXT URL Handler (Unified)
Handles multiple site management for card checking.
Works in both private chats and groups with lowest product parsing.

Features:
- Batch URL processing for large numbers of sites
- Lowest product detection
- Unified site storage with /addurl
- Group and private chat support
"""

import os
import json
import time
import asyncio
import re
from typing import List, Dict, Optional

from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.enums import ParseMode

from BOT.Charge.Shopify.tls_session import TLSAsyncSession
from BOT.helper.start import load_users

# Import from addurl for shared functionality
from BOT.Charge.Shopify.slf.addurl import (
    validate_and_parse_site,
    normalize_url,
    get_random_headers,
    STANDARD_TIMEOUT,
)

# Import unified site manager
from BOT.Charge.Shopify.slf.site_manager import (
    add_sites_batch,
    get_user_sites,
    get_primary_site,
    clear_user_sites,
    remove_site_for_user,
)

TXT_SITES_PATH = "DATA/txtsite.json"


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


def extract_urls_from_text(text: str) -> List[str]:
    """Extract all URLs/domains from text."""
    urls = []
    
    # Pattern for full URLs
    url_pattern = r'https?://[^\s<>"{}|\\^`\[\]]+'
    urls.extend(re.findall(url_pattern, text))
    
    # Pattern for domains without protocol
    if not urls:
        domain_pattern = r'(?:[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}'
        domains = re.findall(domain_pattern, text)
        # Filter out common non-domain patterns
        for d in domains:
            if d not in ['example.com', 'test.com'] and len(d) > 4:
                urls.append(d)
    
    # Remove duplicates while preserving order
    seen = set()
    unique_urls = []
    for url in urls:
        normalized = normalize_url(url).lower()
        if normalized not in seen:
            seen.add(normalized)
            unique_urls.append(url)
    
    return unique_urls


async def validate_sites_batch_optimized(
    urls: List[str],
    progress_callback=None,
    batch_size: int = 5
) -> List[Dict]:
    """
    Validate multiple sites with progress reporting.
    
    Args:
        urls: List of URLs to validate
        progress_callback: Optional async callback for progress updates
        batch_size: Number of sites to check concurrently
        
    Returns:
        List of validation results
    """
    results = []
    total = len(urls)
    processed = 0
    
    async with TLSAsyncSession(timeout_seconds=STANDARD_TIMEOUT) as session:
        for i in range(0, len(urls), batch_size):
            batch = urls[i:i + batch_size]
            tasks = [validate_and_parse_site(url, session) for url in batch]
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for url, result in zip(batch, batch_results):
                if isinstance(result, Exception):
                    results.append({
                        "valid": False,
                        "url": url,
                        "gateway": "Unknown",
                        "price": "N/A",
                        "error": str(result)[:50]
                    })
                else:
                    results.append(result)
            
            processed += len(batch)
            
            # Report progress
            if progress_callback:
                await progress_callback(processed, total, len([r for r in results if r.get("valid")]))
            
            # Small delay between batches
            if i + batch_size < len(urls):
                await asyncio.sleep(0.5)
    
    return results


@Client.on_message(filters.command("txturl"))
async def txturl_handler(client: Client, message: Message):
    """
    Add multiple sites for TXT checking.
    Works in both private chats and groups.
    Parses lowest products and saves to unified storage.
    
    Usage:
        /txturl site1.com site2.com site3.com
        /txturl (reply to message with URLs)
    """
    user_id = str(message.from_user.id)
    user_name = message.from_user.first_name
    clickable_name = f"<a href='tg://user?id={user_id}'>{user_name}</a>"
    
    # Check if user is registered
    users = load_users()
    if user_id not in users:
        return await message.reply(
            """<pre>Access Denied 🚫</pre>
<b>You must register first using</b> <code>/register</code> <b>command.</b>""",
            reply_to_message_id=message.id,
            parse_mode=ParseMode.HTML
        )
    
    # Get URLs from command args or reply
    args = message.command[1:]
    
    # Also check reply message for URLs
    if message.reply_to_message and message.reply_to_message.text:
        reply_urls = extract_urls_from_text(message.reply_to_message.text)
        args.extend(reply_urls)
    
    # If still no args and command text has more content
    if not args and len(message.text.split('\n')) > 1:
        # Multi-line input
        text = message.text.split('\n', 1)[1] if '\n' in message.text else ""
        args.extend(extract_urls_from_text(text))
    
    if not args:
        return await message.reply(
            """<pre>📖 Bulk Site Addition</pre>
━━━━━━━━━━━━━━━
<b>Add multiple Shopify sites at once:</b>

<code>/txturl site1.com site2.com site3.com</code>

<b>Or reply to a message containing URLs:</b>
Reply to list of URLs with <code>/txturl</code>

<b>Other Commands:</b>
• <code>/addurl</code> - Add single site
• <code>/txtls</code> - List all your sites
• <code>/rurl site.com</code> - Remove a site
• <code>/clearurl</code> - Clear all sites
━━━━━━━━━━━━━━━
<i>Works in groups & private chats!</i>""",
            reply_to_message_id=message.id,
            parse_mode=ParseMode.HTML
        )
    
    # Limit to 50 URLs at once
    urls = list(set(args))[:50]
    total_urls = len(urls)
    start_time = time.time()
    
    # Get existing sites to check for duplicates
    existing_sites = get_user_sites(user_id)
    existing_urls = {s.get("url", "").lower().rstrip("/") for s in existing_sites}
    
    # Filter out duplicates
    new_urls = []
    for url in urls:
        normalized = normalize_url(url).lower().rstrip("/")
        if normalized not in existing_urls:
            new_urls.append(url)
    
    if not new_urls:
        return await message.reply(
            f"""<pre>All Sites Already Exist ℹ️</pre>
<b>All {total_urls} provided sites are already in your list.</b>

Use <code>/txtls</code> to view your sites.""",
            reply_to_message_id=message.id,
            parse_mode=ParseMode.HTML
        )
    
    wait_msg = await message.reply(
        f"""<pre>🔍 Processing {len(new_urls)} Sites...</pre>
━━━━━━━━━━━━━
<b>New Sites:</b> <code>{len(new_urls)}</code>
<b>Skipped (duplicates):</b> <code>{total_urls - len(new_urls)}</code>
<b>Status:</b> <i>Parsing lowest products...</i>""",
        reply_to_message_id=message.id,
        parse_mode=ParseMode.HTML
    )
    
    # Progress callback
    async def update_progress(processed: int, total: int, valid: int):
        try:
            await wait_msg.edit_text(
                f"""<pre>🔍 Processing Sites...</pre>
━━━━━━━━━━━━━
<b>Progress:</b> <code>{processed}/{total}</code>
<b>Valid So Far:</b> <code>{valid}</code>
<b>Status:</b> <i>Parsing products...</i>""",
                parse_mode=ParseMode.HTML
            )
        except:
            pass
    
    try:
        # Validate all sites with progress updates
        results = await validate_sites_batch_optimized(
            new_urls,
            progress_callback=update_progress if len(new_urls) > 5 else None,
            batch_size=5
        )
        
        # Separate valid and invalid sites
        valid_sites = [r for r in results if r.get("valid")]
        invalid_sites = [r for r in results if not r.get("valid")]
        
        time_taken = round(time.time() - start_time, 2)
        
        if not valid_sites:
            error_lines = []
            for site in invalid_sites[:5]:
                error_lines.append(f"• <code>{site.get('url', 'Unknown')[:35]}</code>")
            
            return await wait_msg.edit_text(
                f"""<pre>No Valid Sites Found ❌</pre>
━━━━━━━━━━━━━
<b>Processed:</b> <code>{len(new_urls)}</code>
<b>Valid:</b> <code>0</code>

<b>Failed Sites:</b>
{chr(10).join(error_lines)}

<b>Tips:</b>
• Ensure sites are Shopify stores
• Check if stores have products
━━━━━━━━━━━━━
⏱️ <b>Time:</b> <code>{time_taken}s</code>""",
                parse_mode=ParseMode.HTML
            )
        
        # Prepare sites for batch save
        sites_to_add = []
        for site in valid_sites:
            gateway = site.get("gateway", "Unknown")
            price = site.get("price", "N/A")
            gate_name = f"Shopify {gateway} ${price}" if price != "N/A" else f"Shopify {gateway}"
            
            sites_to_add.append({
                "url": site["url"],
                "gateway": gate_name,
                "price": price
            })
        
        # Save to unified storage
        added_count = add_sites_batch(user_id, sites_to_add)
        
        # Also save to legacy storage for compatibility
        all_sites = load_txt_sites()
        user_sites = all_sites.get(user_id, [])
        for site in valid_sites:
            user_sites.append({
                "site": site["url"],
                "gate": f"Shopify {site.get('gateway', 'Unknown')} ${site.get('price', 'N/A')}"
            })
        all_sites[user_id] = user_sites
        save_txt_sites(all_sites)
        
        # Build response
        result_lines = [
            "<pre>Sites Added Successfully ✅</pre>",
            "━━━━━━━━━━━━━"
        ]
        
        # Show first 5 valid sites
        for site in valid_sites[:5]:
            price_display = site.get("formatted_price", f"${site.get('price', 'N/A')}")
            product = site.get("product_title", "N/A")[:25]
            result_lines.append(f"[⌯] <code>{site['url'][:35]}</code>")
            result_lines.append(f"    📦 {product}... | {price_display}")
        
        if len(valid_sites) > 5:
            result_lines.append(f"\n<i>...and {len(valid_sites) - 5} more sites</i>")
        
        result_lines.extend([
            "━━━━━━━━━━━━━",
            f"[⌯] <b>Added:</b> <code>{added_count}</code> new sites",
            f"[⌯] <b>Failed:</b> <code>{len(invalid_sites)}</code>",
            f"[⌯] <b>Time:</b> <code>{time_taken}s</code>",
            "━━━━━━━━━━━━━",
            f"[⌯] <b>User:</b> {clickable_name}",
        ])
        
        # Buttons
        buttons = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("📋 View All", callback_data="txtls_view"),
                InlineKeyboardButton("✓ Check Card", callback_data="show_check_help")
            ]
        ])
        
        await wait_msg.edit_text(
            "\n".join(result_lines),
            parse_mode=ParseMode.HTML,
            reply_markup=buttons,
            disable_web_page_preview=True
        )
        
    except Exception as e:
        time_taken = round(time.time() - start_time, 2)
        await wait_msg.edit_text(
            f"""<pre>Error Occurred ⚠️</pre>
━━━━━━━━━━━━━
<b>Error:</b> <code>{str(e)[:100]}</code>
<b>Time:</b> <code>{time_taken}s</code>

<b>Please try again.</b>""",
            parse_mode=ParseMode.HTML
        )


@Client.on_message(filters.command("txtls"))
async def txtls_handler(client: Client, message: Message):
    """List user's all sites using unified site manager."""
    user_id = str(message.from_user.id)
    clickable_name = f"<a href='tg://user?id={user_id}'>{message.from_user.first_name}</a>"
    
    # Use unified site manager
    unified_sites = get_user_sites(user_id)
    
    if not unified_sites:
        return await message.reply(
            """<pre>No Sites Found ℹ️</pre>
<b>You haven't added any sites yet.</b>

<b>Add sites using:</b>
• <code>/addurl store.com</code> - Single site
• <code>/txturl site1.com site2.com</code> - Multiple sites""",
            reply_to_message_id=message.id,
            parse_mode=ParseMode.HTML
        )
    
    lines = ["<pre>📋 Your Shopify Sites</pre>", "━━━━━━━━━━━━━"]
    
    for i, site in enumerate(unified_sites[:20], 1):
        url = site.get("url", "N/A")
        gateway = site.get("gateway", "Unknown")
        is_primary = "⭐" if site.get("is_primary") else ""
        
        # Extract price from gateway string if present
        price = site.get("price", "")
        if not price and "$" in gateway:
            try:
                price = gateway.split("$")[1].split()[0]
            except:
                price = "N/A"
        
        lines.append(f"<b>{i}.</b> {is_primary}<code>{url[:40]}</code>")
        lines.append(f"   <i>{gateway[:35]}</i>")
    
    if len(unified_sites) > 20:
        lines.append(f"\n<i>... and {len(unified_sites) - 20} more sites</i>")
    
    lines.extend([
        "━━━━━━━━━━━━━",
        f"<b>Total:</b> <code>{len(unified_sites)}</code> site(s)",
        f"<b>User:</b> {clickable_name}",
        "",
        "<b>Commands:</b>",
        "• <code>/sh</code> - Check card",
        "• <code>/rurl site.com</code> - Remove site",
        "• <code>/clearurl</code> - Clear all"
    ])
    
    await message.reply(
        "\n".join(lines),
        reply_to_message_id=message.id,
        parse_mode=ParseMode.HTML
    )


@Client.on_message(filters.command("rurl"))
async def rurl_handler(client: Client, message: Message):
    """Remove sites from user's list."""
    args = message.command[1:]
    user_id = str(message.from_user.id)
    
    if not args:
        return await message.reply(
            """<b>Usage:</b> <code>/rurl site1.com site2.com</code>

<b>Removes specified sites from your list.</b>""",
            reply_to_message_id=message.id,
            parse_mode=ParseMode.HTML
        )
    
    # Get current sites
    unified_sites = get_user_sites(user_id)
    
    if not unified_sites:
        return await message.reply(
            "<pre>No Sites Found ℹ️</pre>",
            reply_to_message_id=message.id,
            parse_mode=ParseMode.HTML
        )
    
    # Track removed sites
    removed = []
    args_lower = [a.lower().replace("https://", "").replace("http://", "").rstrip("/") for a in args]
    
    for arg in args_lower:
        for site in unified_sites:
            site_url = site.get("url", "").lower().replace("https://", "").replace("http://", "").rstrip("/")
            if arg in site_url or site_url in arg:
                if remove_site_for_user(user_id, site.get("url", "")):
                    removed.append(site.get("url", ""))
                break
    
    # Also update legacy storage
    all_sites = load_txt_sites()
    user_sites = all_sites.get(user_id, [])
    new_sites = []
    for entry in user_sites:
        site_lower = entry.get("site", "").lower().replace("https://", "").replace("http://", "")
        if not any(arg in site_lower or site_lower in arg for arg in args_lower):
            new_sites.append(entry)
    all_sites[user_id] = new_sites
    save_txt_sites(all_sites)
    
    if removed:
        removed_list = "\n".join([f"• <code>{s[:40]}</code>" for s in removed[:5]])
        if len(removed) > 5:
            removed_list += f"\n<i>...and {len(removed) - 5} more</i>"
        
        await message.reply(
            f"""<pre>Sites Removed ✅</pre>
━━━━━━━━━━━━━
{removed_list}

<b>Removed:</b> <code>{len(removed)}</code> site(s)""",
            reply_to_message_id=message.id,
            parse_mode=ParseMode.HTML
        )
    else:
        await message.reply(
            "<pre>No Matching Sites Found ❌</pre>",
            reply_to_message_id=message.id,
            parse_mode=ParseMode.HTML
        )


@Client.on_message(filters.command("clearurl"))
async def clearurl_handler(client: Client, message: Message):
    """Clear all sites for user."""
    user_id = str(message.from_user.id)
    
    # Clear from unified storage
    count = clear_user_sites(user_id)
    
    # Also clear from legacy storage
    all_sites = load_txt_sites()
    if user_id in all_sites:
        legacy_count = len(all_sites[user_id])
        del all_sites[user_id]
        save_txt_sites(all_sites)
        count = max(count, legacy_count)
    
    if count > 0:
        await message.reply(
            f"""<pre>All Sites Cleared ✅</pre>
━━━━━━━━━━━━━
<b>Removed:</b> <code>{count}</code> site(s)

<b>Add new sites:</b>
• <code>/addurl store.com</code>
• <code>/txturl site1.com site2.com</code>""",
            reply_to_message_id=message.id,
            parse_mode=ParseMode.HTML
        )
    else:
        await message.reply(
            "<pre>No Sites Found ℹ️</pre>",
            reply_to_message_id=message.id,
            parse_mode=ParseMode.HTML
        )


# ==================== CALLBACK HANDLERS ====================

@Client.on_callback_query(filters.regex("^txtls_view$"))
async def txtls_view_callback(client, callback_query):
    """View sites list via callback."""
    user_id = str(callback_query.from_user.id)
    sites = get_user_sites(user_id)
    
    if not sites:
        await callback_query.answer("❌ No sites found!", show_alert=True)
        return
    
    lines = ["<pre>📋 Your Sites</pre>", "━━━━━━━━━━━━━"]
    
    for i, site in enumerate(sites[:15], 1):
        url = site.get("url", "N/A")[:35]
        is_primary = "⭐" if site.get("is_primary") else ""
        lines.append(f"{i}. {is_primary}<code>{url}</code>")
    
    if len(sites) > 15:
        lines.append(f"\n<i>...and {len(sites) - 15} more</i>")
    
    lines.extend([
        "━━━━━━━━━━━━━",
        f"<b>Total:</b> <code>{len(sites)}</code>",
        "<b>Use:</b> <code>/txtls</code> for full list"
    ])
    
    await callback_query.answer()
    await callback_query.message.reply(
        "\n".join(lines),
        parse_mode=ParseMode.HTML
    )
