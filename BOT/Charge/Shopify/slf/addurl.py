"""
Professional Shopify Site URL Handler (Unified)
Robust site validation with lowest product parsing for /addurl and /txturl commands.
Works in both private chats and groups.

Features:
- Lowest product price detection
- Gateway detection
- Test check before saving
- Unified site storage
- Group and private chat support
"""

import os
import json
import time
import asyncio
import re
import random
import hashlib
from urllib.parse import urlparse
from typing import Optional, Dict, Any, Tuple, List

from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.enums import ParseMode, ChatType

from BOT.Charge.Shopify.tls_session import TLSAsyncSession
from BOT.tools.proxy import get_proxy
from BOT.helper.start import load_users

try:
    import cloudscraper
    HAS_CLOUDSCRAPER = True
except ImportError:
    HAS_CLOUDSCRAPER = False

# Import unified site manager
from BOT.Charge.Shopify.slf.site_manager import (
    add_site_for_user,
    add_sites_batch,
    get_primary_site,
    get_user_sites,
    clear_user_sites,
)

# Timeout configurations
FAST_TIMEOUT = 18
STANDARD_TIMEOUT = 35
MAX_RETRIES = 3
FETCH_RETRIES = 2

# Currency symbols mapping
CURRENCY_SYMBOLS = {
    'USD': '$', 'EUR': '€', 'GBP': '£', 'JPY': '¥', 'CNY': '¥',
    'INR': '₹', 'AUD': 'A$', 'CAD': 'C$', 'CHF': 'CHF', 'SGD': 'S$',
    'NZD': 'NZ$', 'MXN': 'MX$', 'BRL': 'R$', 'ZAR': 'R', 'AED': 'د.إ',
    'SEK': 'kr', 'NOK': 'kr', 'DKK': 'kr', 'PLN': 'zł', 'THB': '฿',
    'IDR': 'Rp', 'MYR': 'RM', 'PHP': '₱', 'HKD': 'HK$', 'KRW': '₩',
    'TRY': '₺', 'RUB': '₽', 'ILS': '₪', 'CZK': 'Kč', 'HUF': 'Ft'
}

# User agents pool
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
]

# Gateway patterns
GATEWAY_PATTERNS = {
    "Shopify Payments": ["shopify payments", "normal"],
    "Stripe": ["stripe"],
    "PayPal": ["paypal", "braintree paypal"],
    "Braintree": ["braintree"],
    "Authorize.net": ["authorize", "authorizenet"],
    "Square": ["square"],
    "Klarna": ["klarna"],
    "Affirm": ["affirm"],
    "Afterpay": ["afterpay", "clearpay"],
    "Shop Pay": ["shop pay", "shoppay"],
}


def normalize_url(url: str) -> str:
    """Normalize and clean URL to standard format."""
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


def clean_domain(domain: str) -> str:
    """Clean and validate domain format."""
    domain = domain.replace('https://', '').replace('http://', '').strip('/')
    domain = domain.split('/')[0]
    domain = domain.lower()
    
    if not domain or len(domain) < 3:
        raise ValueError("Domain too short")
    
    if not re.match(r'^[a-zA-Z0-9]([a-zA-Z0-9\-\.]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z]{2,})+$', domain):
        raise ValueError("Invalid domain format")
    
    return domain


def get_random_headers() -> Dict[str, str]:
    """Generate random but realistic browser headers."""
    ua = random.choice(USER_AGENTS)
    return {
        "User-Agent": ua,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Cache-Control": "no-cache",
        "sec-ch-ua": '"Chromium";v="120", "Not/A)Brand";v="24"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
    }


def _parse_products_json(raw: str) -> List[Dict]:
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


def _fetch_products_cloudscraper_sync(base_url: str, proxy: Optional[str] = None) -> List[Dict]:
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
        raw = r.text
        return _parse_products_json(raw)
    except Exception:
        return []


def extract_between(text: str, start_marker: str, end_marker: str) -> Optional[str]:
    """Extract string between two markers."""
    try:
        start_idx = text.index(start_marker) + len(start_marker)
        end_idx = text.index(end_marker, start_idx)
        return text[start_idx:end_idx]
    except (ValueError, IndexError):
        return None


def detect_gateway(page_content: str) -> str:
    """Detect payment gateway from page content."""
    content_lower = page_content.lower()
    
    gateway = extract_between(page_content, 'extensibilityDisplayName&quot;:&quot;', '&quot')
    if gateway:
        if gateway == "Shopify Payments":
            return "Normal"
        return gateway
    
    for gateway_name, patterns in GATEWAY_PATTERNS.items():
        for pattern in patterns:
            if pattern in content_lower:
                return gateway_name
    
    return "Unknown"


def get_currency_symbol(code: str) -> str:
    """Get currency symbol for code."""
    return CURRENCY_SYMBOLS.get(code.upper(), f"{code} ")


async def fetch_products_json(
    session: TLSAsyncSession,
    base_url: str,
    proxy: Optional[str] = None,
) -> List[Dict]:
    """Fetch products from Shopify /products.json. TLS first, then cloudscraper fallback. Robust JSON parse."""
    products_url = f"{base_url.rstrip('/')}/products.json?limit=100"
    products: List[Dict] = []

    for attempt in range(FETCH_RETRIES):
        try:
            resp = await asyncio.wait_for(
                session.get(
                    products_url,
                    headers=get_random_headers(),
                    follow_redirects=True,
                ),
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
            products = _parse_products_json(raw)
            if products:
                return products
        except (asyncio.TimeoutError, json.JSONDecodeError, Exception):
            pass

    if HAS_CLOUDSCRAPER and not products:
        try:
            products = await asyncio.to_thread(
                _fetch_products_cloudscraper_sync,
                base_url,
                proxy,
            )
        except Exception:
            pass
    return products if isinstance(products, list) else []


def find_lowest_variant_from_products(products: List[Dict]) -> Optional[Dict]:
    """Find lowest priced available product from products list - robust version."""
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


async def validate_and_parse_site(
    url: str,
    session: TLSAsyncSession,
    proxy: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Validate if a URL is a working Shopify store and parse lowest product.
    Uses robust validation logic and optional cloudscraper fallback.
    """
    result = {
        "valid": False,
        "url": url,
        "gateway": "Normal",
        "price": "N/A",
        "error": None,
        "product_id": None,
        "product_title": None,
        "currency": "USD",
        "formatted_price": None,
    }
    
    try:
        normalized_url = normalize_url(url)
        result["url"] = normalized_url
        
        products = await fetch_products_json(session, normalized_url, proxy)
        
        if not products:
            result["error"] = "No products or not Shopify"
            return result
        
        # Find lowest variant using robust method
        lowest = find_lowest_variant_from_products(products)
        
        if not lowest:
            result["error"] = "No available products"
            return result
        
        # Populate result
        result["valid"] = True
        result["product_id"] = lowest['variant'].get('id')
        result["product_title"] = lowest['product'].get('title', 'N/A')[:50]
        result["price"] = f"{lowest['price']:.2f}"
        result["formatted_price"] = f"${lowest['price']:.2f}"
        
        return result
        
    except Exception as e:
        result["error"] = str(e)[:50]
        return result


async def validate_sites_batch(urls: List[str], user_proxy: Optional[str] = None) -> List[Dict[str, Any]]:
    """Validate multiple Shopify sites concurrently. Uses TLS + optional proxy; cloudscraper fallback."""
    results = []
    proxy_url = None
    if user_proxy and str(user_proxy).strip():
        px = str(user_proxy).strip()
        proxy_url = px if px.startswith(("http://", "https://")) else f"http://{px}"
    
    async with TLSAsyncSession(timeout_seconds=STANDARD_TIMEOUT, proxy=proxy_url) as session:
        batch_size = 5
        for i in range(0, len(urls), batch_size):
            batch = urls[i:i + batch_size]
            tasks = [validate_and_parse_site(url, session, proxy_url) for url in batch]
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for url, result in zip(batch, batch_results):
                if isinstance(result, Exception):
                    results.append({
                        "valid": False,
                        "url": normalize_url(url),
                        "gateway": "Normal",
                        "price": "N/A",
                        "error": str(result)[:50]
                    })
                else:
                    results.append(result)
            
            # Small delay between batches
            if i + batch_size < len(urls):
                await asyncio.sleep(0.3)
    
    return results


def save_site_for_user_unified(user_id: str, site: str, gateway: str, price: str = "N/A") -> bool:
    """Save a site for a user using unified site manager."""
    gate_name = f"Shopify {gateway} ${price}" if price != "N/A" else f"Shopify {gateway}"
    return add_site_for_user(user_id, site, gate_name, price, set_primary=True)


def get_user_current_site(user_id: str) -> Optional[Dict[str, str]]:
    """Get user's currently saved site using unified site manager."""
    site = get_primary_site(user_id)
    if site:
        return {
            "site": site.get("url"),
            "gate": site.get("gateway"),
            "price": site.get("price", "N/A")
        }
    return None


# ==================== COMMAND HANDLERS ====================

@Client.on_message(filters.command(["addurl", "slfurl", "seturl"]))
async def add_site_handler(client: Client, message: Message):
    """
    Handle /addurl command to add and validate Shopify sites.
    Works in both private chats and groups.
    Parses lowest product and validates before saving.
    
    Usage:
        /addurl https://example.myshopify.com
        /addurl example.com
        /addurl site1.com site2.com site3.com (multiple sites)
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
    
    # Get URLs from command
    args = message.command[1:]
    
    # Also support reply to message containing URLs
    if not args and message.reply_to_message and message.reply_to_message.text:
        url_pattern = r'https?://[^\s<>"{}|\\^`\[\]]+'
        args = re.findall(url_pattern, message.reply_to_message.text)
        if not args:
            domain_pattern = r'(?:[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}'
            args = re.findall(domain_pattern, message.reply_to_message.text)
    
    if not args:
        return await message.reply(
            """<pre>📖 Add Site Guide</pre>
━━━━━━━━━━━━━━━
<b>Add a Shopify site for checking:</b>

<code>/addurl https://store.myshopify.com</code>
<code>/addurl store.com</code>
<code>/addurl site1.com site2.com</code> <i>(multiple)</i>

<b>After adding:</b> Use <code>/sh</code> or <code>/slf</code> to check cards

<b>Other Commands:</b>
• <code>/mysite</code> - View your current site
• <code>/txturl</code> - Add multiple sites
• <code>/txtls</code> - List all your sites
• <code>/delsite</code> - Remove your site
━━━━━━━━━━━━━━━
<i>Works in groups & private chats!</i>""",
            reply_to_message_id=message.id,
            parse_mode=ParseMode.HTML
        )
    
    # Limit to 10 URLs at once
    urls = args[:10]
    total_urls = len(urls)
    
    start_time = time.time()
    
    # Show processing message
    status_msg = await message.reply(
        f"""<pre>🔍 Validating Shopify Sites...</pre>
━━━━━━━━━━━━━
<b>Sites:</b> <code>{total_urls}</code>
<b>Status:</b> <i>Parsing lowest products...</i>""",
        reply_to_message_id=message.id,
        parse_mode=ParseMode.HTML
    )
    
    try:
        # Get user's proxy if set
        user_proxy = get_proxy(int(user_id))
        
        # Validate all sites with lowest product parsing
        results = await validate_sites_batch(urls, user_proxy)
        
        # Separate valid and invalid sites
        valid_sites = [r for r in results if r["valid"]]
        invalid_sites = [r for r in results if not r["valid"]]
        
        time_taken = round(time.time() - start_time, 2)
        
        if not valid_sites:
            error_lines = []
            for site in invalid_sites[:5]:
                error_lines.append(f"• <code>{site['url'][:40]}</code> → {site.get('error', 'Invalid')}")
            
            error_text = "\n".join(error_lines)
            
            return await status_msg.edit_text(
                f"""<pre>No Valid Sites Found ❌</pre>
━━━━━━━━━━━━━
<b>Checked:</b> <code>{total_urls}</code> site(s)
<b>Valid:</b> <code>0</code>

<b>Errors:</b>
{error_text}

<b>Tips:</b>
• Ensure the site is a Shopify store
• Check if the store has available products
• Try with full URL: https://store.com
━━━━━━━━━━━━━
⏱️ <b>Time:</b> <code>{time_taken}s</code>""",
                parse_mode=ParseMode.HTML
            )
        
        # Use the first valid site as primary
        primary_site = valid_sites[0]
        site_url = primary_site["url"]
        gateway = primary_site["gateway"]
        price = primary_site["price"]
        product_title = primary_site.get("product_title", "N/A")
        formatted_price = primary_site.get("formatted_price", f"${price}")
        
        # Save the primary site
        saved = save_site_for_user_unified(user_id, site_url, gateway, price)
        
        # Build response
        response_lines = [
            f"<pre>Site Added Successfully ✅</pre>",
            "━━━━━━━━━━━━━"
        ]
        
        # Primary site info with product details
        response_lines.extend([
            f"[⌯] <b>Site:</b> <code>{site_url}</code>",
            f"[⌯] <b>Gateway:</b> <code>{gateway}</code>",
            f"[⌯] <b>Lowest Price:</b> <code>{formatted_price}</code>",
            f"[⌯] <b>Product:</b> <code>{product_title}...</code>",
            f"[⌯] <b>Status:</b> <code>Active ✓</code>",
        ])
        
        # Show additional valid sites if any
        if len(valid_sites) > 1:
            response_lines.append("")
            response_lines.append(f"<b>Other Valid Sites ({len(valid_sites) - 1}):</b>")
            for site in valid_sites[1:5]:
                price_display = site.get("formatted_price", f"${site.get('price', 'N/A')}")
                response_lines.append(f"• <code>{site['url'][:35]}</code> [{price_display}]")
        
        # Show failed sites count
        if invalid_sites:
            response_lines.append("")
            response_lines.append(f"<b>Failed:</b> <code>{len(invalid_sites)}</code> site(s)")
        
        response_lines.extend([
            "━━━━━━━━━━━━━",
            f"[⌯] <b>Command:</b> <code>/sh</code> or <code>/slf</code>",
            f"[⌯] <b>Time:</b> <code>{time_taken}s</code>",
            f"[⌯] <b>User:</b> {clickable_name}",
        ])
        
        # Buttons
        buttons = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✓ Check Card", callback_data="show_check_help"),
                InlineKeyboardButton("📋 My Sites", callback_data="show_my_sites")
            ]
        ])
        
        await status_msg.edit_text(
            "\n".join(response_lines),
            parse_mode=ParseMode.HTML,
            reply_markup=buttons,
            disable_web_page_preview=True
        )
        
    except Exception as e:
        time_taken = round(time.time() - start_time, 2)
        await status_msg.edit_text(
            f"""<pre>Error Occurred ⚠️</pre>
━━━━━━━━━━━━━
<b>Error:</b> <code>{str(e)[:100]}</code>
<b>Time:</b> <code>{time_taken}s</code>

<b>Please try again or contact support.</b>""",
            parse_mode=ParseMode.HTML
        )


@Client.on_message(filters.command(["mysite", "getsite", "siteinfo"]))
async def my_site_handler(client: Client, message: Message):
    """Show user's currently saved primary site."""
    user_id = str(message.from_user.id)
    
    site_info = get_user_current_site(user_id)
    
    if not site_info:
        return await message.reply(
            """<pre>No Site Found ℹ️</pre>
<b>You haven't added any site yet.</b>

Use <code>/addurl https://store.com</code> to add a Shopify site.""",
            reply_to_message_id=message.id,
            parse_mode=ParseMode.HTML
        )
    
    # Get all sites count
    all_sites = get_user_sites(user_id)
    total_count = len(all_sites)
    
    await message.reply(
        f"""<pre>Your Primary Site 📋</pre>
━━━━━━━━━━━━━
[⌯] <b>Site:</b> <code>{site_info.get('site', 'N/A')}</code>
[⌯] <b>Gateway:</b> <code>{site_info.get('gate', 'Unknown')}</code>
[⌯] <b>Price:</b> <code>${site_info.get('price', 'N/A')}</code>
━━━━━━━━━━━━━
<b>Total Sites:</b> <code>{total_count}</code>
<b>Commands:</b> <code>/sh</code> or <code>/slf</code> to check cards
<b>List All:</b> <code>/txtls</code>""",
        reply_to_message_id=message.id,
        parse_mode=ParseMode.HTML
    )


@Client.on_message(filters.command(["delsite", "removesite", "clearsite", "remurl"]))
async def delete_site_handler(client: Client, message: Message):
    """Delete all of user's saved sites (unified storage). Idempotent; safe to run repeatedly."""
    user_id = str(message.from_user.id)
    try:
        count = clear_user_sites(user_id)
        if count > 0:
            return await message.reply(
                f"<pre>Sites Removed ✅</pre>\n<b>Cleared {count} site(s).</b> You can add again with <code>/addurl</code>.",
                reply_to_message_id=message.id,
                parse_mode=ParseMode.HTML
            )
        await message.reply(
            "<pre>No Site Found ℹ️</pre>\n<b>You don't have any site saved.</b>",
            reply_to_message_id=message.id,
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        await message.reply(
            f"<pre>Error ⚠️</pre>\n<code>{str(e)[:80]}</code>",
            reply_to_message_id=message.id,
            parse_mode=ParseMode.HTML
        )


# ==================== CALLBACK HANDLERS ====================

@Client.on_callback_query(filters.regex("^show_check_help$"))
async def show_check_help_callback(client, callback_query):
    """Show card checking help."""
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
━━━━━━━━━━━━━━━
<b>Supported Gates:</b>
• Shopify Payments (Normal)
• Stripe
• PayPal/Braintree
━━━━━━━━━━━━━━━""",
        parse_mode=ParseMode.HTML
    )


@Client.on_callback_query(filters.regex("^show_my_sites$"))
async def show_my_sites_callback(client, callback_query):
    """Show user's all sites."""
    user_id = str(callback_query.from_user.id)
    sites = get_user_sites(user_id)
    
    if not sites:
        await callback_query.answer("❌ No sites saved!", show_alert=True)
        return
    
    # Build sites list
    lines = ["<pre>📋 Your Sites</pre>", "━━━━━━━━━━━━━"]
    
    for i, site in enumerate(sites[:10], 1):
        is_primary = "⭐" if site.get("is_primary") else ""
        url = site.get("url", "N/A")[:35]
        lines.append(f"{i}. {is_primary}<code>{url}</code>")
    
    if len(sites) > 10:
        lines.append(f"\n<i>...and {len(sites) - 10} more</i>")
    
    lines.append("━━━━━━━━━━━━━")
    lines.append(f"<b>Total:</b> <code>{len(sites)}</code> sites")
    
    await callback_query.answer()
    await callback_query.message.reply(
        "\n".join(lines),
        parse_mode=ParseMode.HTML
    )


@Client.on_callback_query(filters.regex("^show_my_site$"))
async def show_my_site_callback(client, callback_query):
    """Show user's primary site."""
    user_id = str(callback_query.from_user.id)
    site_info = get_user_current_site(user_id)
    
    if site_info:
        await callback_query.answer(
            f"📋 YOUR SITE\n\n"
            f"🌐 {site_info.get('site', 'N/A')[:40]}\n"
            f"⚡ {site_info.get('gate', 'Unknown')[:30]}\n\n"
            f"Use /sh to check cards!",
            show_alert=True
        )
    else:
        await callback_query.answer(
            "❌ No site saved!\n\n"
            "Use /addurl to add a site.",
            show_alert=True
        )


@Client.on_callback_query(filters.regex("^plans_info$"))
async def plans_info_callback(client, callback_query):
    """Show plans information."""
    await callback_query.answer()
    await callback_query.message.reply(
        """<pre>💎 Available Plans</pre>
━━━━━━━━━━━━━━━
<b>🎟️ Free Plan:</b>
• 10 credits/day
• 10s antispam delay
• Basic features

<b>⭐ Premium Plan:</b>
• 500 credits/day
• 3s antispam delay
• All gates access
• Priority support

<b>👑 VIP Plan:</b>
• Unlimited credits
• No antispam delay
• All features
• 24/7 support
━━━━━━━━━━━━━━━
Use <code>/buy</code> to purchase!""",
        parse_mode=ParseMode.HTML
    )
