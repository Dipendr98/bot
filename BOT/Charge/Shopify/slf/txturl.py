"""
TXT URL Handler (Unified)
Professional batch site validation with lowest product parsing.
Works exactly like /addurl but for multiple sites at once.

Features:
- Robust batch URL processing
- Accurate lowest product detection
- Unified site storage with /addurl
- Group and private chat support
"""

import os
import json
import time
import asyncio
import re
from typing import List, Dict, Optional, Any
from urllib.parse import urlparse

from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.enums import ParseMode

from BOT.Charge.Shopify.tls_session import TLSAsyncSession
from BOT.helper.start import load_users
from BOT.tools.proxy import get_proxy

try:
    import cloudscraper
    HAS_CLOUDSCRAPER = True
except ImportError:
    HAS_CLOUDSCRAPER = False

# Import unified site manager
from BOT.Charge.Shopify.slf.site_manager import (
    add_sites_batch,
    get_user_sites,
    get_primary_site,
    clear_user_sites,
    remove_site_for_user,
    add_site_for_user,
)

TXT_SITES_PATH = "DATA/txtsite.json"

# Timeouts
FAST_TIMEOUT = 20
STANDARD_TIMEOUT = 40
FETCH_RETRIES = 2

# Currency symbols
CURRENCY_SYMBOLS = {
    'USD': '$', 'EUR': '€', 'GBP': '£', 'JPY': '¥', 'CNY': '¥',
    'INR': '₹', 'AUD': 'A$', 'CAD': 'C$', 'CHF': 'CHF', 'SGD': 'S$',
}


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


def normalize_url(url: str) -> str:
    """Normalize URL to standard https format."""
    url = url.strip().lower()
    url = url.rstrip('/')
    
    # Remove common path suffixes
    for suffix in ['/products', '/collections', '/cart', '/checkout', '/pages']:
        if suffix in url:
            url = url.split(suffix)[0]
    
    # Add protocol if missing
    if not url.startswith(('http://', 'https://')):
        url = f"https://{url}"
    
    try:
        parsed = urlparse(url)
        domain = parsed.netloc or parsed.path.split('/')[0]
        domain = domain.split(':')[0]
        return f"https://{domain}"
    except Exception:
        return url


def extract_urls_from_text(text: str) -> List[str]:
    """Extract all URLs/domains from text - robust version."""
    urls = []
    
    # Split by common delimiters
    parts = re.split(r'[\s,\n\r\t]+', text)
    
    for part in parts:
        part = part.strip()
        if not part:
            continue
        
        # Skip common non-domain strings
        if part in ['https://', 'http://', 'www.']:
            continue
        
        # Check if it looks like a domain or URL
        if '.' in part and len(part) >= 4:
            # Clean up the part
            part = part.strip('.,;:!?()[]{}')
            
            # Check for valid domain pattern
            domain_pattern = r'^(?:https?://)?(?:www\.)?([a-zA-Z0-9](?:[a-zA-Z0-9\-\.]{0,61}[a-zA-Z0-9])?(?:\.[a-zA-Z]{2,})+)$'
            if re.match(domain_pattern, part, re.IGNORECASE):
                urls.append(part)
    
    # Remove duplicates while preserving order
    seen = set()
    unique_urls = []
    for url in urls:
        normalized = normalize_url(url).lower()
        if normalized not in seen:
            seen.add(normalized)
            unique_urls.append(url)
    
    return unique_urls


def _parse_products_json_txt(raw: str) -> List[Dict]:
    """Robust JSON parse for products.json. Handles BOM, malformed edges."""
    if not raw or not raw.strip():
        return []
    text = raw.strip()
    if text.startswith("\ufeff"):
        text = text[1:]
    if text.lstrip().startswith("<"):
        return []
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    products = data.get("products") if isinstance(data, dict) else None
    return products if isinstance(products, list) else []


def _fetch_products_cloudscraper_txt_sync(base_url: str, proxy: Optional[str] = None) -> List[Dict]:
    """Sync fetch via cloudscraper (captcha bypass). Fallback when TLS fails."""
    if not HAS_CLOUDSCRAPER:
        return []
    url = f"{base_url.rstrip('/')}/products.json?limit=100"
    try:
        scraper = cloudscraper.create_scraper(
            browser={"browser": "chrome", "platform": "windows", "mobile": False}
        )
        if proxy and str(proxy).strip():
            px = str(proxy).strip()
            if not px.startswith(("http://", "https://")):
                px = f"http://{px}"
            scraper.proxies = {"http": px, "https": px}
        r = scraper.get(url, timeout=FAST_TIMEOUT)
        if r.status_code != 200:
            return []
        return _parse_products_json_txt(r.text or "")
    except Exception:
        return []


async def fetch_products_json(
    session: TLSAsyncSession,
    base_url: str,
    proxy: Optional[str] = None,
) -> List[Dict]:
    """Fetch products from Shopify /products.json. TLS first, cloudscraper fallback. Robust JSON."""
    products_url = f"{base_url.rstrip('/')}/products.json?limit=100"
    products: List[Dict] = []

    for _ in range(FETCH_RETRIES):
        try:
            resp = await asyncio.wait_for(
                session.get(products_url, follow_redirects=True),
                timeout=FAST_TIMEOUT,
            )
            if resp.status_code != 200:
                break
            raw = getattr(resp, "content", None)
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", errors="ignore")
            elif hasattr(resp, "text"):
                raw = getattr(resp, "text", "") or ""
            else:
                raw = ""
            products = _parse_products_json_txt(raw)
            if products:
                return products
        except (asyncio.TimeoutError, json.JSONDecodeError, Exception):
            pass

    if HAS_CLOUDSCRAPER and not products:
        try:
            products = await asyncio.to_thread(
                _fetch_products_cloudscraper_txt_sync,
                base_url,
                proxy,
            )
        except Exception:
            pass
    return products if isinstance(products, list) else []


def find_lowest_variant(products: List[Dict]) -> Optional[Dict]:
    """Find lowest priced available product from products list."""
    lowest_price = float('inf')
    lowest_product = None
    lowest_variant = None
    
    for product in products:
        variants = product.get('variants', [])
        
        for variant in variants:
            try:
                # Check availability
                available = variant.get('available', False)
                price_str = variant.get('price', '0')
                price = float(price_str) if price_str else 0.0
                
                # Skip unavailable or free products
                if not available or price < 0.10:
                    continue
                
                if price < lowest_price:
                    lowest_price = price
                    lowest_product = product
                    lowest_variant = variant
                    
            except (ValueError, TypeError):
                continue
    
    if lowest_product and lowest_variant:
        return {
            'product': lowest_product,
            'variant': lowest_variant,
            'price': lowest_price
        }
    
    return None


async def validate_site_robust(
    url: str,
    session: TLSAsyncSession,
    proxy: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Validate a single site and find lowest product.
    Uses robust fetch with optional cloudscraper fallback.
    """
    result = {
        "valid": False,
        "url": url,
        "gateway": "Normal",
        "price": "N/A",
        "product_title": None,
        "product_id": None,
        "formatted_price": None,
        "error": None,
    }
    try:
        normalized = normalize_url(url)
        result["url"] = normalized
        products = await fetch_products_json(session, normalized, proxy)
        if not products:
            result["error"] = "No products or not Shopify"
            return result
        
        # Find lowest variant
        lowest = find_lowest_variant(products)
        
        if not lowest:
            result["error"] = "No available products"
            return result
        
        # Success - populate result
        result["valid"] = True
        result["price"] = f"{lowest['price']:.2f}"
        result["formatted_price"] = f"${lowest['price']:.2f}"
        result["product_title"] = lowest['product'].get('title', 'N/A')[:50]
        result["product_id"] = lowest['variant'].get('id')
        
        return result
        
    except Exception as e:
        result["error"] = str(e)[:50]
        return result


async def validate_sites_batch(
    urls: List[str],
    progress_callback=None,
    batch_size: int = 5,
    user_proxy: Optional[str] = None,
) -> List[Dict]:
    """
    Validate multiple sites with progress reporting.
    Uses robust validation; optional proxy and cloudscraper fallback.
    """
    results = []
    total = len(urls)
    processed = 0
    proxy_url = None
    if user_proxy and str(user_proxy).strip():
        px = str(user_proxy).strip()
        proxy_url = px if px.startswith(("http://", "https://")) else f"http://{px}"

    async with TLSAsyncSession(timeout_seconds=STANDARD_TIMEOUT, proxy=proxy_url) as session:
        for i in range(0, len(urls), batch_size):
            batch = urls[i:i + batch_size]
            tasks = [validate_site_robust(url, session, proxy_url) for url in batch]
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for url, result in zip(batch, batch_results):
                if isinstance(result, Exception):
                    results.append({
                        "valid": False,
                        "url": normalize_url(url),
                        "gateway": "Unknown",
                        "price": "N/A",
                        "error": str(result)[:50]
                    })
                else:
                    results.append(result)
            
            processed += len(batch)
            
            # Report progress
            if progress_callback:
                valid_so_far = len([r for r in results if r.get("valid")])
                await progress_callback(processed, total, valid_so_far)
            
            # Small delay between batches
            if i + batch_size < len(urls):
                await asyncio.sleep(0.3)
    
    return results


@Client.on_message(filters.command("txturl"))
async def txturl_handler(client: Client, message: Message):
    """
    Add multiple sites for checking.
    Works exactly like /addurl but for bulk sites.
    
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
    
    # Collect URLs from multiple sources
    all_urls = []
    
    # 1. From command arguments
    args = message.command[1:]
    all_urls.extend(args)
    
    # 2. From reply message
    if message.reply_to_message and message.reply_to_message.text:
        reply_text = message.reply_to_message.text
        reply_urls = extract_urls_from_text(reply_text)
        all_urls.extend(reply_urls)
    
    # 3. From multi-line input in the same message
    if '\n' in message.text:
        lines = message.text.split('\n')[1:]  # Skip first line (command)
        for line in lines:
            line_urls = extract_urls_from_text(line)
            all_urls.extend(line_urls)
    
    # Clean and dedupe URLs
    unique_urls = []
    seen = set()
    for url in all_urls:
        url = url.strip()
        if not url or url.startswith('/'):
            continue
        normalized = normalize_url(url).lower()
        if normalized not in seen and '.' in url:
            seen.add(normalized)
            unique_urls.append(url)
    
    if not unique_urls:
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
    urls = unique_urls[:50]
    total_urls = len(urls)
    start_time = time.time()
    
    # Check for duplicates with existing sites
    existing_sites = get_user_sites(user_id)
    existing_urls = {s.get("url", "").lower().rstrip("/") for s in existing_sites}
    
    new_urls = []
    skipped = 0
    for url in urls:
        normalized = normalize_url(url).lower().rstrip("/")
        if normalized not in existing_urls:
            new_urls.append(url)
        else:
            skipped += 1
    
    if not new_urls:
        return await message.reply(
            f"""<pre>All Sites Already Exist ℹ️</pre>
<b>All {total_urls} provided sites are already in your list.</b>

Use <code>/txtls</code> to view your sites.""",
            reply_to_message_id=message.id,
            parse_mode=ParseMode.HTML
        )
    
    # Show processing message
    wait_msg = await message.reply(
        f"""<pre>🔍 Processing {len(new_urls)} Sites...</pre>
━━━━━━━━━━━━━
<b>New Sites:</b> <code>{len(new_urls)}</code>
<b>Skipped (duplicates):</b> <code>{skipped}</code>
<b>Status:</b> <i>Parsing lowest products...</i>""",
        reply_to_message_id=message.id,
        parse_mode=ParseMode.HTML
    )
    
    # Progress callback
    last_update = [0]  # Use list for mutable closure
    
    async def update_progress(processed: int, total: int, valid: int):
        # Only update every 3 sites to avoid flood
        if processed - last_update[0] >= 3 or processed == total:
            last_update[0] = processed
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
        user_proxy = None
        try:
            user_proxy = get_proxy(int(user_id))
        except Exception:
            pass
        results = await validate_sites_batch(
            new_urls,
            progress_callback=update_progress if len(new_urls) > 3 else None,
            batch_size=5,
            user_proxy=user_proxy,
        )
        
        # Separate valid and invalid sites
        valid_sites = [r for r in results if r.get("valid")]
        invalid_sites = [r for r in results if not r.get("valid")]
        
        time_taken = round(time.time() - start_time, 2)
        
        if not valid_sites:
            error_lines = []
            for site in invalid_sites[:5]:
                url = site.get('url', 'Unknown')[:30]
                err = site.get('error', 'Unknown')[:20]
                error_lines.append(f"• <code>{url}</code> - {err}")
            
            return await wait_msg.edit_text(
                f"""<pre>No Valid Sites Found ❌</pre>
━━━━━━━━━━━━━
<b>Processed:</b> <code>{len(new_urls)}</code>
<b>Valid:</b> <code>0</code>

<b>Failed Sites:</b>
{chr(10).join(error_lines)}

<b>Tips:</b>
• Ensure sites are Shopify stores
• Check if stores have available products
━━━━━━━━━━━━━
⏱️ <b>Time:</b> <code>{time_taken}s</code>""",
                parse_mode=ParseMode.HTML
            )
        
        # Prepare sites for batch save
        sites_to_add = []
        for site in valid_sites:
            gateway = site.get("gateway", "Normal")
            price = site.get("price", "N/A")
            gate_name = f"Shopify {gateway} ${price}"
            
            sites_to_add.append({
                "url": site["url"],
                "gateway": gate_name,
                "price": price
            })
        
        added_count = add_sites_batch(user_id, sites_to_add)

        # Build response
        result_lines = [
            "<pre>Sites Added Successfully ✅</pre>",
            "━━━━━━━━━━━━━"
        ]
        
        # Show first 8 valid sites
        for site in valid_sites[:8]:
            price_display = site.get("formatted_price", f"${site.get('price', 'N/A')}")
            product = site.get("product_title", "N/A")
            if product and len(product) > 25:
                product = product[:25] + "..."
            url = site['url'].replace('https://', '')[:30]
            result_lines.append(f"[⌯] <code>{url}</code>")
            result_lines.append(f"    📦 {product} | {price_display}")
        
        if len(valid_sites) > 8:
            result_lines.append(f"\n<i>...and {len(valid_sites) - 8} more sites</i>")
        
        result_lines.extend([
            "━━━━━━━━━━━━━",
            f"[⌯] <b>Added:</b> <code>{len(valid_sites)}</code> sites",
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
        import traceback
        traceback.print_exc()
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
        url = site.get("url", "N/A").replace('https://', '')
        gateway = site.get("gateway", "Unknown")
        is_primary = "⭐" if site.get("is_primary") else ""
        
        # Extract price from gateway string if present
        price = site.get("price", "")
        if not price and "$" in gateway:
            try:
                price = gateway.split("$")[1].split()[0]
            except:
                price = "N/A"
        
        lines.append(f"<b>{i}.</b> {is_primary}<code>{url[:35]}</code>")
        lines.append(f"   <i>${price}</i>")
    
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
    
    removed = []
    args_lower = [a.lower().replace("https://", "").replace("http://", "").rstrip("/") for a in args]

    for arg in args_lower:
        for site in unified_sites:
            site_url = site.get("url", "").lower().replace("https://", "").replace("http://", "").rstrip("/")
            if arg in site_url or site_url in arg:
                if remove_site_for_user(user_id, site.get("url", "")):
                    removed.append(site.get("url", ""))
                break

    if removed:
        removed_list = "\n".join([f"• <code>{s.replace('https://', '')[:35]}</code>" for s in removed[:5]])
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
    """Clear all sites for user (unified storage). Idempotent."""
    user_id = str(message.from_user.id)
    count = clear_user_sites(user_id)
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
        url = site.get("url", "N/A").replace('https://', '')[:30]
        is_primary = "⭐" if site.get("is_primary") else ""
        price = site.get("price", "N/A")
        lines.append(f"{i}. {is_primary}<code>{url}</code> ${price}")
    
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


@Client.on_callback_query(filters.regex("^show_check_help$"))
async def show_check_help_from_txturl(client, callback_query):
    """Show card checking help from txturl."""
    await callback_query.answer()
    await callback_query.message.reply(
        """<pre>📖 Card Checking Guide</pre>
━━━━━━━━━━━━━━━
<b>Single Card Check:</b>
<code>/sh 4111111111111111|12|2025|123</code>

<b>Reply to Card:</b>
Reply to a message containing a card with <code>/sh</code>

<b>Mass Check:</b>
<code>/msh</code> (reply to list of cards)

<b>Format:</b> <code>cc|mm|yy|cvv</code> or <code>cc|mm|yyyy|cvv</code>
━━━━━━━━━━━━━━━""",
        parse_mode=ParseMode.HTML
    )
