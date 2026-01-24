"""
Professional Shopify Site URL Handler
Robust site validation, gateway detection, and management for Shopify checkers.
"""

import os
import json
import time
import asyncio
import re
import random
from urllib.parse import urlparse
from typing import Optional, Dict, Any, Tuple, List

from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.enums import ParseMode

from BOT.Charge.Shopify.tls_session import TLSAsyncSession
from BOT.tools.proxy import get_proxy
from BOT.helper.start import load_users

# File paths
SITES_PATH = "DATA/sites.json"
TXT_SITES_PATH = "DATA/txtsite.json"

# User agents pool for realistic requests
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1",
]

# Timeout configurations
FAST_TIMEOUT = 15
STANDARD_TIMEOUT = 30
MAX_RETRIES = 2

# Gateway identifiers
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
    """
    Normalize and clean URL to standard format.
    Handles various input formats: domain only, with/without protocol, with paths.
    """
    url = url.strip().lower()
    
    # Remove trailing slashes
    url = url.rstrip('/')
    
    # Remove common path suffixes
    for suffix in ['/products', '/collections', '/cart', '/checkout', '/pages']:
        if suffix in url:
            url = url.split(suffix)[0]
    
    # Add protocol if missing
    if not url.startswith(('http://', 'https://')):
        url = f"https://{url}"
    
    # Parse and reconstruct to get clean domain
    try:
        parsed = urlparse(url)
        domain = parsed.netloc or parsed.path.split('/')[0]
        # Remove any port numbers for cleaner URL
        domain = domain.split(':')[0]
        return f"https://{domain}"
    except Exception:
        return url


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
    }


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
    
    # Try to extract gateway name from Shopify checkout
    gateway = extract_between(page_content, 'extensibilityDisplayName&quot;:&quot;', '&quot')
    if gateway:
        if gateway == "Shopify Payments":
            return "Normal"
        return gateway
    
    # Fallback to pattern matching
    for gateway_name, patterns in GATEWAY_PATTERNS.items():
        for pattern in patterns:
            if pattern in content_lower:
                return gateway_name
    
    return "Unknown"


def get_min_price_product(products_data: list) -> Optional[Tuple[int, float]]:
    """
    Find the cheapest available product from products.json data.
    Returns (product_id, price) or None.
    """
    products = {}
    
    for product in products_data:
        variants = product.get("variants", [])
        for variant in variants:
            try:
                product_id = variant.get("id")
                available = variant.get("available", False)
                price = float(variant.get("price", 0))
                
                # Skip free or unavailable products
                if price < 0.10 or not available:
                    continue
                
                products[product_id] = price
            except (ValueError, TypeError):
                continue
    
    if products:
        min_id = min(products, key=products.get)
        return min_id, products[min_id]
    
    return None


async def validate_shopify_site(url: str, session: TLSAsyncSession) -> Dict[str, Any]:
    """
    Validate if a URL is a working Shopify store.
    
    Returns:
        Dict with keys: valid, url, gateway, price, error
    """
    result = {
        "valid": False,
        "url": url,
        "gateway": "Unknown",
        "price": "N/A",
        "error": None,
        "product_id": None,
    }
    
    try:
        normalized_url = normalize_url(url)
        result["url"] = normalized_url
        
        headers = get_random_headers()
        
        # Step 1: Check products.json endpoint (Shopify signature)
        products_url = f"{normalized_url}/products.json"
        
        try:
            response = await asyncio.wait_for(
                session.get(products_url, headers=headers, follow_redirects=True),
                timeout=FAST_TIMEOUT
            )
        except asyncio.TimeoutError:
            result["error"] = "Timeout"
            return result
        
        # Check if response is valid JSON
        try:
            data = response.json()
        except (json.JSONDecodeError, ValueError):
            result["error"] = "Not Shopify"
            return result
        
        # Verify it has products structure
        products = data.get("products", [])
        if not products:
            result["error"] = "No Products"
            return result
        
        # Step 2: Find cheapest available product
        product_info = get_min_price_product(products)
        if not product_info:
            result["error"] = "No Available Products"
            return result
        
        product_id, price = product_info
        result["product_id"] = product_id
        result["price"] = f"{price:.2f}"
        
        # Step 3: Quick checkout page check for gateway detection
        try:
            # Get site access token for cart creation
            home_response = await asyncio.wait_for(
                session.get(normalized_url, headers=headers, follow_redirects=True),
                timeout=FAST_TIMEOUT
            )
            
            site_key = extract_between(home_response.text, '"accessToken":"', '"')
            
            if site_key:
                # Create cart to get checkout URL
                cart_headers = {
                    **headers,
                    'content-type': 'application/json',
                    'origin': normalized_url,
                    'x-shopify-storefront-access-token': site_key,
                }
                
                cart_payload = {
                    'query': 'mutation cartCreate($input:CartInput!){result:cartCreate(input:$input){cart{id checkoutUrl}errors:userErrors{message}}}',
                    'variables': {
                        'input': {
                            'lines': [{
                                'merchandiseId': f'gid://shopify/ProductVariant/{product_id}',
                                'quantity': 1,
                            }],
                        },
                    },
                }
                
                cart_response = await asyncio.wait_for(
                    session.post(
                        f'{normalized_url}/api/unstable/graphql.json',
                        params={'operation_name': 'cartCreate'},
                        headers=cart_headers,
                        json=cart_payload,
                        follow_redirects=True
                    ),
                    timeout=STANDARD_TIMEOUT
                )
                
                cart_data = cart_response.json()
                checkout_url = cart_data.get("data", {}).get("result", {}).get("cart", {}).get("checkoutUrl")
                
                if checkout_url:
                    # Fetch checkout page for gateway detection
                    checkout_response = await asyncio.wait_for(
                        session.get(checkout_url, headers=headers, follow_redirects=True),
                        timeout=STANDARD_TIMEOUT
                    )
                    
                    result["gateway"] = detect_gateway(checkout_response.text)
            else:
                # No site key found, try basic detection
                result["gateway"] = "Normal"
                
        except Exception:
            # Gateway detection failed, but site is still valid Shopify
            result["gateway"] = "Normal"
        
        result["valid"] = True
        return result
        
    except Exception as e:
        result["error"] = str(e)[:50]
        return result


async def validate_sites_batch(urls: List[str], user_proxy: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Validate multiple Shopify sites concurrently.
    
    Args:
        urls: List of URLs to validate
        user_proxy: Optional user proxy string
        
    Returns:
        List of validation results
    """
    results = []
    
    async with TLSAsyncSession(timeout_seconds=STANDARD_TIMEOUT) as session:
        # Process sites concurrently in batches for efficiency
        batch_size = 5  # Process 5 sites at a time
        
        for i in range(0, len(urls), batch_size):
            batch = urls[i:i + batch_size]
            tasks = [validate_shopify_site(url, session) for url in batch]
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
    
    return results


def save_site_for_user(user_id: str, site: str, gateway: str) -> bool:
    """Save a site for a user using unified site manager."""
    from BOT.Charge.Shopify.slf.site_manager import add_site_for_user
    # Extract price from gateway string if present
    price = "N/A"
    if "$" in gateway:
        try:
            price = gateway.split("$")[1].split()[0]
        except:
            pass
    return add_site_for_user(user_id, site, gateway, price, set_primary=True)


def get_user_current_site(user_id: str) -> Optional[Dict[str, str]]:
    """Get user's currently saved site using unified site manager."""
    from BOT.Charge.Shopify.slf.site_manager import get_primary_site
    site = get_primary_site(user_id)
    if site:
        return {
            "site": site.get("url"),
            "gate": site.get("gateway")
        }
    return None


@Client.on_message(filters.command(["addurl", "slfurl", "seturl"]) & ~filters.private)
async def addurl_group_redirect(client: Client, message: Message):
    """Redirect /addurl command in groups to private chat."""
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

<b>Command:</b> <code>/addurl</code>
<b>Purpose:</b> Add Shopify sites for checking

<b>How to use:</b>
1️⃣ Click the button below
2️⃣ Use <code>/addurl site.com</code> there

<b>Why private?</b>
• 🔐 Protects your site data
• ⚡ Personal site management
━━━━━━━━━━━━━━━
<i>Your data security is our priority!</i>""",
        reply_to_message_id=message.id,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📱 Open Private Chat", url=bot_link)]
        ])
    )


@Client.on_message(filters.command(["addurl", "slfurl", "seturl"]) & filters.private)
async def add_site_handler(client: Client, message: Message):
    """
    Handle /addurl command to add and validate Shopify sites.
    
    Usage:
        /addurl https://example.myshopify.com
        /addurl example.com
        /addurl site1.com site2.com site3.com  (multiple sites)
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
            reply_to_message_id=message.id
        )
    
    # Get URLs from command
    args = message.command[1:]
    
    # Also support reply to message containing URLs
    if not args and message.reply_to_message and message.reply_to_message.text:
        # Extract URLs from replied message
        url_pattern = r'https?://[^\s<>"{}|\\^`\[\]]+'
        args = re.findall(url_pattern, message.reply_to_message.text)
        if not args:
            # Try to find domain-like patterns
            domain_pattern = r'(?:[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}'
            args = re.findall(domain_pattern, message.reply_to_message.text)
    
    if not args:
        return await message.reply(
            """<pre>Usage Guide 📖</pre>
<b>Add a Shopify site for card checking:</b>

<code>/addurl https://example.myshopify.com</code>
<code>/addurl example.com</code>
<code>/addurl site1.com site2.com</code> <i>(multiple)</i>

<b>After adding:</b> Use <code>/sh</code> or <code>/slf</code> to check cards

<b>Other Commands:</b>
• <code>/mysite</code> - View your current site
• <code>/delsite</code> - Remove your site""",
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
<b>Status:</b> <i>Checking...</i>""",
        reply_to_message_id=message.id,
        parse_mode=ParseMode.HTML
    )
    
    try:
        # Get user's proxy if set
        user_proxy = get_proxy(int(user_id))
        
        # Validate all sites
        results = await validate_sites_batch(urls, user_proxy)
        
        # Separate valid and invalid sites
        valid_sites = [r for r in results if r["valid"]]
        invalid_sites = [r for r in results if not r["valid"]]
        
        time_taken = round(time.time() - start_time, 2)
        
        if not valid_sites:
            # No valid sites found
            error_lines = []
            for site in invalid_sites[:5]:  # Show first 5 errors
                error_lines.append(f"• <code>{site['url']}</code> → {site.get('error', 'Invalid')}")
            
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
• Try with full URL: https://store.myshopify.com
━━━━━━━━━━━━━
⏱️ <b>Time:</b> <code>{time_taken}s</code>""",
                parse_mode=ParseMode.HTML
            )
        
        # Use the first valid site as primary
        primary_site = valid_sites[0]
        site_url = primary_site["url"]
        gateway = primary_site["gateway"]
        price = primary_site["price"]
        gate_name = f"Shopify {gateway} ${price}"
        
        # Save the primary site
        saved = save_site_for_user(user_id, site_url, gate_name)
        
        # Build response
        response_lines = [
            f"<pre>Site Added Successfully ✅</pre>",
            "━━━━━━━━━━━━━"
        ]
        
        # Primary site info
        response_lines.extend([
            f"[⌯] <b>Site:</b> <code>{site_url}</code>",
            f"[⌯] <b>Gateway:</b> <code>{gateway}</code>",
            f"[⌯] <b>Price:</b> <code>${price}</code>",
            f"[⌯] <b>Status:</b> <code>Active ✓</code>",
        ])
        
        # Show additional valid sites if any
        if len(valid_sites) > 1:
            response_lines.append("")
            response_lines.append(f"<b>Other Valid Sites ({len(valid_sites) - 1}):</b>")
            for site in valid_sites[1:5]:  # Show up to 4 more
                response_lines.append(f"• <code>{site['url']}</code> ({site['gateway']})")
        
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
                InlineKeyboardButton("📋 My Site", callback_data="show_my_site")
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
    """Show user's currently saved site."""
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
    
    await message.reply(
        f"""<pre>Your Site Info 📋</pre>
━━━━━━━━━━━━━
[⌯] <b>Site:</b> <code>{site_info.get('site', 'N/A')}</code>
[⌯] <b>Gateway:</b> <code>{site_info.get('gate', 'Unknown')}</code>
━━━━━━━━━━━━━
<b>Commands:</b> <code>/sh</code> or <code>/slf</code> to check cards""",
        reply_to_message_id=message.id,
        parse_mode=ParseMode.HTML
    )


@Client.on_message(filters.command(["delsite", "removesite", "clearsite", "remurl"]))
async def delete_site_handler(client: Client, message: Message):
    """Delete user's saved site. Also handles /remurl."""
    user_id = str(message.from_user.id)
    
    try:
        if os.path.exists(SITES_PATH):
            with open(SITES_PATH, "r", encoding="utf-8") as f:
                all_sites = json.load(f)
            
            if user_id in all_sites:
                del all_sites[user_id]
                
                with open(SITES_PATH, "w", encoding="utf-8") as f:
                    json.dump(all_sites, f, indent=4)
                
                return await message.reply(
                    "<pre>Site Removed ✅</pre>\n<b>Your site has been deleted successfully.</b>",
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
            f"<pre>Error ⚠️</pre>\n<code>{str(e)}</code>",
            reply_to_message_id=message.id,
            parse_mode=ParseMode.HTML
        )


# Callback query handlers for buttons
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


@Client.on_callback_query(filters.regex("^show_my_site$"))
async def show_my_site_callback(client, callback_query):
    """Show user's site via callback with detailed popup."""
    user_id = str(callback_query.from_user.id)
    site_info = get_user_current_site(user_id)
    
    if site_info:
        site_url = site_info.get('site', 'N/A')
        gateway = site_info.get('gate', 'Unknown')
        
        # Show detailed popup
        await callback_query.answer(
            f"📋 YOUR SITE INFO\n\n"
            f"🌐 Site: {site_url[:40]}...\n"
            f"⚡ Gate: {gateway[:30]}\n\n"
            f"Use /sh to check cards!",
            show_alert=True
        )
    else:
        await callback_query.answer(
            "❌ No site saved!\n\n"
            "Use /addurl https://store.com to add a Shopify site.",
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
