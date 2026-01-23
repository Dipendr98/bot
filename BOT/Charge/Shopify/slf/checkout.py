"""
Professional Shopify Checkout API
Complete checkout flow for both digital and physical products.
Handles all Shopify payment gateways with proper error handling.
"""

import json
import time
import random
import asyncio
from typing import Dict, Any, Optional, Tuple
from urllib.parse import urlparse

from BOT.Charge.Shopify.tls_session import TLSAsyncSession


# ============================================================================
# CONFIGURATION
# ============================================================================

# Currency to Country mapping
CURRENCY_TO_COUNTRY = {
    "USD": "US", "CAD": "CA", "INR": "IN", "AED": "AE",
    "HKD": "HK", "GBP": "GB", "CHF": "CH", "EUR": "DE",
    "AUD": "AU", "NZD": "NZ", "JPY": "JP", "SGD": "SG",
}

# Address book for different countries
ADDRESS_BOOK = {
    "US": {
        "address1": "123 Main Street", "city": "New York", "postalCode": "10001",
        "zoneCode": "NY", "countryCode": "US", "phone": "2125551234", "currencyCode": "USD"
    },
    "CA": {
        "address1": "88 Queen Street", "city": "Toronto", "postalCode": "M5J2J3",
        "zoneCode": "ON", "countryCode": "CA", "phone": "4165550198", "currencyCode": "CAD"
    },
    "GB": {
        "address1": "221B Baker Street", "city": "London", "postalCode": "NW1 6XE",
        "zoneCode": "ENG", "countryCode": "GB", "phone": "2079460123", "currencyCode": "GBP"
    },
    "AU": {
        "address1": "1 Martin Place", "city": "Sydney", "postalCode": "2000",
        "zoneCode": "NSW", "countryCode": "AU", "phone": "291234567", "currencyCode": "AUD"
    },
    "DE": {
        "address1": "Friedrichstraße 123", "city": "Berlin", "postalCode": "10117",
        "zoneCode": "BE", "countryCode": "DE", "phone": "3012345678", "currencyCode": "EUR"
    },
    "IN": {
        "address1": "221B MG Road", "city": "Mumbai", "postalCode": "400001",
        "zoneCode": "MH", "countryCode": "IN", "phone": "9876543210", "currencyCode": "INR"
    },
    "DEFAULT": {
        "address1": "123 Main Street", "city": "New York", "postalCode": "10001",
        "zoneCode": "NY", "countryCode": "US", "phone": "2125551234", "currencyCode": "USD"
    },
}

# User agents for browser simulation
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
]

# Email domains for checkout
EMAIL_DOMAINS = ["gmail.com", "outlook.com", "yahoo.com", "protonmail.com"]

# Names for checkout
FIRST_NAMES = ["John", "Emma", "Michael", "Sarah", "David", "Lisa", "James", "Emily", "Robert", "Anna"]
LAST_NAMES = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis", "Wilson", "Moore"]


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def extract_between(text: str, start: str, end: str) -> Optional[str]:
    """Extract string between two markers."""
    try:
        start_idx = text.index(start) + len(start)
        end_idx = text.index(end, start_idx)
        return text[start_idx:end_idx]
    except (ValueError, IndexError):
        return None


def get_random_user_agent() -> str:
    """Get a random user agent."""
    return random.choice(USER_AGENTS)


def get_platform(ua: str) -> str:
    """Determine platform from user agent."""
    if "Android" in ua:
        return "Android"
    elif "iPhone" in ua or "iPad" in ua:
        return "iOS"
    elif "Macintosh" in ua:
        return "macOS"
    elif "Windows" in ua:
        return "Windows"
    return "Unknown"


def get_address_for_site(url: str, currency: str = None, country: str = None) -> Dict[str, str]:
    """Get appropriate address for a site based on domain, currency, or country."""
    # Try domain TLD first
    try:
        domain = urlparse(url).netloc
        tld = domain.split('.')[-1].upper()
        if tld in ADDRESS_BOOK:
            return ADDRESS_BOOK[tld]
    except:
        pass
    
    # Try currency mapping
    if currency:
        country_from_currency = CURRENCY_TO_COUNTRY.get(currency.upper())
        if country_from_currency and country_from_currency in ADDRESS_BOOK:
            return ADDRESS_BOOK[country_from_currency]
    
    # Try direct country
    if country and country.upper() in ADDRESS_BOOK:
        return ADDRESS_BOOK[country.upper()]
    
    return ADDRESS_BOOK["DEFAULT"]


def generate_random_email() -> str:
    """Generate a random email address."""
    domain = random.choice(EMAIL_DOMAINS)
    username = f"{''.join(random.choices('abcdefghijklmnopqrstuvwxyz', k=8))}{random.randint(100, 999)}"
    return f"{username}@{domain}"


def generate_random_name() -> Tuple[str, str]:
    """Generate random first and last name."""
    return random.choice(FIRST_NAMES), random.choice(LAST_NAMES)


def parse_card(card_string: str) -> Optional[Tuple[str, str, str, str]]:
    """Parse card string in format cc|mm|yy|cvv."""
    try:
        parts = card_string.split("|")
        if len(parts) != 4:
            return None
        cc, mm, yy, cvv = [p.strip() for p in parts]
        
        # Normalize year to 2 digits
        if len(yy) == 4:
            yy = yy[-2:]
        
        # Normalize month to 2 digits
        if len(mm) == 1:
            mm = f"0{mm}"
            
        return cc, mm, yy, cvv
    except:
        return None


def get_product_from_json(products_data: list) -> Optional[Tuple[int, float]]:
    """Find cheapest available product. Returns (product_id, price) or None."""
    available_products = {}
    
    for product in products_data:
        variants = product.get("variants", [])
        for variant in variants:
            try:
                product_id = variant.get("id")
                available = variant.get("available", False)
                price = float(variant.get("price", 0))
                
                # Skip unavailable or free products
                if not available or price < 0.10:
                    continue
                
                available_products[product_id] = price
            except (ValueError, TypeError):
                continue
    
    if available_products:
        min_id = min(available_products, key=available_products.get)
        return min_id, available_products[min_id]
    
    return None


# ============================================================================
# RESPONSE PARSING
# ============================================================================

# Response status mapping
RESPONSE_MAPPING = {
    # Success responses
    "ORDER_PLACED": {"status": "CHARGED", "emoji": "💎", "ccn": False},
    "THANK_YOU": {"status": "CHARGED", "emoji": "💎", "ccn": False},
    
    # CVV/CCN responses (card is valid but declined)
    "3DS_REQUIRED": {"status": "CCN", "emoji": "✅", "ccn": True},
    "INCORRECT_CVC": {"status": "CCN", "emoji": "✅", "ccn": True},
    "INCORRECT_CVV": {"status": "CCN", "emoji": "✅", "ccn": True},
    "INVALID_CVC": {"status": "CCN", "emoji": "✅", "ccn": True},
    "MISMATCHED_ZIP": {"status": "CCN", "emoji": "✅", "ccn": True},
    "MISMATCHED_PIN": {"status": "CCN", "emoji": "✅", "ccn": True},
    "MISMATCHED_BILLING": {"status": "CCN", "emoji": "✅", "ccn": True},
    "MISMATCHED_BILL": {"status": "CCN", "emoji": "✅", "ccn": True},
    "INCORRECT_ADDRESS": {"status": "CCN", "emoji": "✅", "ccn": True},
    "INCORRECT_ZIP": {"status": "CCN", "emoji": "✅", "ccn": True},
    "AUTHENTICATION_FAILED": {"status": "CCN", "emoji": "✅", "ccn": True},
    "3D_SECURE_REQUIRED": {"status": "CCN", "emoji": "✅", "ccn": True},
    "FRAUD_SUSPECTED": {"status": "CCN", "emoji": "⚠️", "ccn": True},
    
    # Decline responses
    "CARD_DECLINED": {"status": "DECLINED", "emoji": "❌", "ccn": False},
    "INSUFFICIENT_FUNDS": {"status": "DECLINED", "emoji": "❌", "ccn": False},
    "GENERIC_ERROR": {"status": "DECLINED", "emoji": "❌", "ccn": False},
    "INCORRECT_NUMBER": {"status": "DECLINED", "emoji": "❌", "ccn": False},
    "INVALID_NUMBER": {"status": "DECLINED", "emoji": "❌", "ccn": False},
    "CARD_EXPIRED": {"status": "DECLINED", "emoji": "❌", "ccn": False},
    "CARD_NOT_SUPPORTED": {"status": "DECLINED", "emoji": "❌", "ccn": False},
    
    # Error responses
    "PRODUCT_EMPTY": {"status": "ERROR", "emoji": "⚠️", "ccn": False},
    "SITE_DEAD": {"status": "ERROR", "emoji": "⚠️", "ccn": False},
    "HANDLE_EMPTY": {"status": "ERROR", "emoji": "⚠️", "ccn": False},
    "RECEIPT_EMPTY": {"status": "ERROR", "emoji": "⚠️", "ccn": False},
    "HCAPTCHA_DETECTED": {"status": "ERROR", "emoji": "⚠️", "ccn": False},
    "RATE_LIMIT": {"status": "ERROR", "emoji": "⚠️", "ccn": False},
}


def parse_checkout_response(response_text: str) -> Dict[str, Any]:
    """Parse checkout response and return standardized result."""
    response_upper = response_text.upper().replace("_", " ").replace("-", " ")
    
    for key, mapping in RESPONSE_MAPPING.items():
        key_normalized = key.replace("_", " ")
        if key_normalized in response_upper or key in response_upper:
            return {
                "status": mapping["status"],
                "response": key,
                "emoji": mapping["emoji"],
                "is_ccn": mapping["ccn"],
                "raw": response_text
            }
    
    # Default to unknown
    return {
        "status": "UNKNOWN",
        "response": response_text[:100] if len(response_text) > 100 else response_text,
        "emoji": "❓",
        "is_ccn": False,
        "raw": response_text
    }


# ============================================================================
# MAIN CHECKOUT FUNCTION
# ============================================================================

async def shopify_checkout(
    site_url: str,
    card: str,
    session: Optional[TLSAsyncSession] = None
) -> Dict[str, Any]:
    """
    Complete Shopify checkout with card.
    
    Args:
        site_url: Shopify store URL
        card: Card in format cc|mm|yy|cvv
        session: Optional TLSAsyncSession (will create if not provided)
    
    Returns:
        Dict with: status, response, gateway, price, time_taken, etc.
    """
    start_time = time.time()
    
    # Initialize result
    result = {
        "status": "ERROR",
        "response": "UNKNOWN_ERROR",
        "gateway": "Unknown",
        "price": "0.00",
        "cc": card,
        "site": site_url,
        "time_taken": 0,
        "is_ccn": False,
        "emoji": "⚠️",
    }
    
    # Parse card
    card_parts = parse_card(card)
    if not card_parts:
        result["response"] = "INVALID_CARD_FORMAT"
        result["time_taken"] = round(time.time() - start_time, 2)
        return result
    
    cc, mm, yy, cvv = card_parts
    
    # Create session if not provided
    own_session = False
    if session is None:
        session = TLSAsyncSession(timeout_seconds=60)
        own_session = True
    
    try:
        # Normalize URL
        if not site_url.startswith(("http://", "https://")):
            site_url = f"https://{site_url}"
        
        parsed = urlparse(site_url)
        domain = parsed.netloc
        base_url = f"https://{domain}"
        
        result["site"] = base_url
        
        # Browser simulation setup
        user_agent = get_random_user_agent()
        platform = get_platform(user_agent)
        is_mobile = "Android" in user_agent or "iPhone" in user_agent
        mobile_flag = "?1" if is_mobile else "?0"
        
        first_name, last_name = generate_random_name()
        email = generate_random_email()
        
        # ================================================================
        # STEP 1: Get products from site
        # ================================================================
        headers = {"User-Agent": user_agent}
        
        try:
            products_response = await session.get(
                f"{base_url}/products.json",
                headers=headers,
                follow_redirects=True,
                timeout=30
            )
            products_data = products_response.json()
        except Exception as e:
            result["response"] = "SITE_UNREACHABLE"
            result["time_taken"] = round(time.time() - start_time, 2)
            return result
        
        # Get cheapest available product
        product_info = get_product_from_json(products_data.get("products", []))
        if not product_info:
            result["response"] = "NO_AVAILABLE_PRODUCTS"
            result["time_taken"] = round(time.time() - start_time, 2)
            return result
        
        product_id, price = product_info
        result["price"] = f"{price:.2f}"
        
        # ================================================================
        # STEP 2: Get site access token
        # ================================================================
        try:
            home_response = await session.get(base_url, headers=headers, follow_redirects=True, timeout=30)
            site_key = extract_between(home_response.text, '"accessToken":"', '"')
        except:
            result["response"] = "SITE_DEAD"
            result["time_taken"] = round(time.time() - start_time, 2)
            return result
        
        if not site_key:
            result["response"] = "NO_ACCESS_TOKEN"
            result["time_taken"] = round(time.time() - start_time, 2)
            return result
        
        # ================================================================
        # STEP 3: Create cart
        # ================================================================
        cart_headers = {
            'accept': 'application/json',
            'accept-language': 'en-US,en;q=0.9',
            'content-type': 'application/json',
            'origin': base_url,
            'sec-ch-ua': '"Chromium";v="120", "Not/A)Brand";v="24"',
            'sec-ch-ua-mobile': mobile_flag,
            'sec-ch-ua-platform': f'"{platform}"',
            'sec-fetch-dest': 'empty',
            'sec-fetch-mode': 'cors',
            'sec-fetch-site': 'same-origin',
            'user-agent': user_agent,
            'x-shopify-storefront-access-token': site_key,
        }
        
        cart_payload = {
            'query': 'mutation cartCreate($input:CartInput!$country:CountryCode$language:LanguageCode)@inContext(country:$country language:$language){result:cartCreate(input:$input){cart{id checkoutUrl}errors:userErrors{message field code}}}',
            'variables': {
                'input': {
                    'lines': [{'merchandiseId': f'gid://shopify/ProductVariant/{product_id}', 'quantity': 1}],
                },
                'country': 'US',
                'language': 'EN',
            },
        }
        
        try:
            cart_response = await session.post(
                f'{base_url}/api/unstable/graphql.json',
                params={'operation_name': 'cartCreate'},
                headers=cart_headers,
                json=cart_payload,
                follow_redirects=True,
                timeout=30
            )
            cart_data = cart_response.json()
            checkout_url = cart_data["data"]["result"]["cart"]["checkoutUrl"]
        except Exception as e:
            result["response"] = "CART_CREATION_FAILED"
            result["time_taken"] = round(time.time() - start_time, 2)
            return result
        
        if not checkout_url:
            result["response"] = "NO_CHECKOUT_URL"
            result["time_taken"] = round(time.time() - start_time, 2)
            return result
        
        # Small delay to simulate human behavior
        await asyncio.sleep(0.5)
        
        # ================================================================
        # STEP 4: Load checkout page
        # ================================================================
        checkout_headers = {
            'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'accept-language': 'en-US,en;q=0.9',
            'sec-ch-ua': '"Chromium";v="120", "Not/A)Brand";v="24"',
            'sec-ch-ua-mobile': mobile_flag,
            'sec-ch-ua-platform': f'"{platform}"',
            'sec-fetch-dest': 'document',
            'sec-fetch-mode': 'navigate',
            'sec-fetch-site': 'same-origin',
            'upgrade-insecure-requests': '1',
            'user-agent': user_agent,
        }
        
        try:
            checkout_response = await session.get(
                checkout_url,
                headers=checkout_headers,
                params={'auto_redirect': 'false'},
                follow_redirects=True,
                timeout=30
            )
            checkout_html = checkout_response.text
        except:
            result["response"] = "CHECKOUT_LOAD_FAILED"
            result["time_taken"] = round(time.time() - start_time, 2)
            return result
        
        # Extract checkout tokens and data
        payment_method_id = extract_between(checkout_html, 'paymentMethodIdentifier&quot;:&quot;', '&quot')
        stable_id = extract_between(checkout_html, 'stableId&quot;:&quot;', '&quot')
        queue_token = extract_between(checkout_html, 'queueToken&quot;:&quot;', '&quot')
        currency_code = extract_between(checkout_html, 'currencyCode&quot;:&quot;', '&quot') or "USD"
        country_code = extract_between(checkout_html, 'countryCode&quot;:&quot;', '&quot') or "US"
        session_token = extract_between(checkout_html, 'serialized-session-token" content="&quot;', '&quot')
        source_token = extract_between(checkout_html, 'serialized-source-token" content="&quot;', '&quot')
        
        # Detect gateway
        gateway = extract_between(checkout_html, 'extensibilityDisplayName&quot;:&quot;', '&quot')
        if gateway == "Shopify Payments" or not gateway:
            gateway = "Normal"
        result["gateway"] = gateway
        
        # Detect delivery method type (SHIPPING or NONE for digital)
        delivery_method = extract_between(checkout_html, 'deliveryMethodTypes&quot;:[&quot;', '&quot;]')
        is_digital_product = not delivery_method or delivery_method == "NONE" or "SHIPPING" not in checkout_html.upper()
        
        # Get address based on site/currency
        address = get_address_for_site(base_url, currency_code, country_code)
        
        # Check for missing critical tokens
        if not session_token or not source_token:
            result["response"] = "CHECKOUT_TOKENS_MISSING"
            result["time_taken"] = round(time.time() - start_time, 2)
            return result
        
        # ================================================================
        # STEP 5: Create payment session (card tokenization)
        # ================================================================
        pci_headers = {
            'accept': 'application/json',
            'accept-language': 'en-US,en;q=0.9',
            'content-type': 'application/json',
            'origin': 'https://checkout.pci.shopifyinc.com',
            'sec-ch-ua': '"Chromium";v="120", "Not/A)Brand";v="24"',
            'sec-ch-ua-mobile': mobile_flag,
            'sec-ch-ua-platform': f'"{platform}"',
            'sec-fetch-dest': 'empty',
            'sec-fetch-mode': 'cors',
            'sec-fetch-site': 'same-origin',
            'user-agent': user_agent,
        }
        
        card_payload = {
            'credit_card': {
                'number': cc,
                'month': mm,
                'year': yy if len(yy) == 4 else f"20{yy}",
                'verification_value': cvv,
                'name': f'{first_name} {last_name}',
            },
            'payment_session_scope': domain,
        }
        
        try:
            pci_response = await session.post(
                'https://checkout.pci.shopifyinc.com/sessions',
                headers=pci_headers,
                json=card_payload,
                timeout=30
            )
            session_id = pci_response.json().get("id")
        except Exception as e:
            result["response"] = "CARD_TOKENIZATION_FAILED"
            result["time_taken"] = round(time.time() - start_time, 2)
            return result
        
        if not session_id:
            result["response"] = "NO_SESSION_ID"
            result["time_taken"] = round(time.time() - start_time, 2)
            return result
        
        # ================================================================
        # STEP 6: Submit for completion (actual charge)
        # ================================================================
        submit_headers = {
            'accept': 'application/json',
            'accept-language': 'en-US',
            'content-type': 'application/json',
            'origin': base_url,
            'referer': checkout_url,
            'sec-ch-ua': '"Chromium";v="120", "Not/A)Brand";v="24"',
            'sec-ch-ua-mobile': mobile_flag,
            'sec-ch-ua-platform': f'"{platform}"',
            'sec-fetch-dest': 'empty',
            'sec-fetch-mode': 'cors',
            'sec-fetch-site': 'same-origin',
            'user-agent': user_agent,
            'x-checkout-one-session-token': session_token,
            'x-checkout-web-source-id': source_token,
        }
        
        # Build delivery section based on product type
        if is_digital_product:
            # Digital product - no shipping
            delivery_section = {
                'deliveryLines': [],
                'noDeliveryRequired': [{'stableId': stable_id}] if stable_id else [],
            }
        else:
            # Physical product - need shipping
            delivery_section = {
                'deliveryLines': [{
                    'destination': {
                        'streetAddress': {
                            'address1': address["address1"],
                            'city': address["city"],
                            'countryCode': address["countryCode"],
                            'postalCode': address["postalCode"],
                            'firstName': first_name,
                            'lastName': last_name,
                            'zoneCode': address["zoneCode"],
                            'phone': address["phone"],
                        },
                    },
                    'selectedDeliveryStrategy': {
                        'deliveryStrategyMatchingConditions': {
                            'estimatedTimeInTransit': {'any': True},
                            'shipments': {'any': True},
                        },
                    },
                    'targetMerchandiseLines': {
                        'lines': [{'stableId': stable_id}] if stable_id else [],
                    },
                }],
            }
        
        submit_payload = {
            'query': 'mutation SubmitForCompletion($input:NegotiationInput!,$attemptToken:String!){submitForCompletion(input:$input attemptToken:$attemptToken){...on SubmitSuccess{receipt{...on ProcessedReceipt{id}}}...on SubmitFailed{reason}...on SubmitRejected{errors{...on NegotiationError{code localizedMessage}}}}}',
            'variables': {
                'input': {
                    'sessionInput': {'sessionToken': session_token},
                    'queueToken': queue_token,
                    'delivery': delivery_section,
                    'merchandise': {
                        'merchandiseLines': [{
                            'stableId': stable_id,
                            'merchandise': {
                                'productVariantReference': {
                                    'variantId': f'gid://shopify/ProductVariant/{product_id}',
                                },
                            },
                            'quantity': {'items': {'value': 1}},
                        }] if stable_id else [],
                    },
                    'payment': {
                        'totalAmount': {'any': True},
                        'paymentLines': [{
                            'paymentMethod': {
                                'directPaymentMethod': {
                                    'paymentMethodIdentifier': payment_method_id,
                                    'sessionId': session_id,
                                    'billingAddress': {
                                        'streetAddress': {
                                            'address1': address["address1"],
                                            'city': address["city"],
                                            'countryCode': address["countryCode"],
                                            'postalCode': address["postalCode"],
                                            'firstName': first_name,
                                            'lastName': last_name,
                                            'zoneCode': address["zoneCode"],
                                            'phone': address["phone"],
                                        },
                                    },
                                },
                            },
                            'amount': {'value': {'amount': str(price), 'currencyCode': currency_code}},
                        }],
                        'billingAddress': {
                            'streetAddress': {
                                'address1': address["address1"],
                                'city': address["city"],
                                'countryCode': address["countryCode"],
                                'postalCode': address["postalCode"],
                                'firstName': first_name,
                                'lastName': last_name,
                                'zoneCode': address["zoneCode"],
                                'phone': address["phone"],
                            },
                        },
                    },
                    'buyerIdentity': {
                        'email': email,
                        'rememberMe': False,
                    },
                },
                'attemptToken': f'{source_token}-submit',
            },
            'operationName': 'SubmitForCompletion',
        }
        
        # Submit checkout
        try:
            submit_response = await session.post(
                f'{base_url}/checkouts/unstable/graphql',
                params={'operationName': 'SubmitForCompletion'},
                headers=submit_headers,
                json=submit_payload,
                timeout=60
            )
            response_text = submit_response.text
        except Exception as e:
            result["response"] = f"SUBMIT_FAILED: {str(e)[:50]}"
            result["time_taken"] = round(time.time() - start_time, 2)
            return result
        
        # Parse the response
        response_upper = response_text.upper()
        
        # Check for success (order placed)
        if "PROCESSERECEIPT" in response_upper.replace(" ", "") or '"ID"' in response_upper:
            if "SUBMITFAILED" not in response_upper and "SUBMITREJECTED" not in response_upper:
                result["status"] = "CHARGED"
                result["response"] = "ORDER_PLACED"
                result["emoji"] = "💎"
                result["is_ccn"] = False
        
        # Check for specific decline codes
        elif "3DS" in response_upper or "THREE_D" in response_upper:
            result["status"] = "CCN"
            result["response"] = "3DS_REQUIRED"
            result["emoji"] = "✅"
            result["is_ccn"] = True
        elif "INCORRECT_CVC" in response_upper or "INCORRECT_CVV" in response_upper or "INVALID_CVC" in response_upper:
            result["status"] = "CCN"
            result["response"] = "INCORRECT_CVC"
            result["emoji"] = "✅"
            result["is_ccn"] = True
        elif "INCORRECT_ADDRESS" in response_upper or "INCORRECT_ZIP" in response_upper:
            result["status"] = "CCN"
            result["response"] = "INCORRECT_ADDRESS"
            result["emoji"] = "✅"
            result["is_ccn"] = True
        elif "MISMATCHED" in response_upper:
            result["status"] = "CCN"
            result["response"] = "MISMATCHED_BILLING"
            result["emoji"] = "✅"
            result["is_ccn"] = True
        elif "FRAUD" in response_upper:
            result["status"] = "CCN"
            result["response"] = "FRAUD_SUSPECTED"
            result["emoji"] = "⚠️"
            result["is_ccn"] = True
        elif "INSUFFICIENT_FUNDS" in response_upper:
            result["status"] = "DECLINED"
            result["response"] = "INSUFFICIENT_FUNDS"
            result["emoji"] = "❌"
        elif "DECLINED" in response_upper or "CARD_DECLINED" in response_upper:
            result["status"] = "DECLINED"
            result["response"] = "CARD_DECLINED"
            result["emoji"] = "❌"
        elif "INCORRECT_NUMBER" in response_upper or "INVALID_NUMBER" in response_upper:
            result["status"] = "DECLINED"
            result["response"] = "INCORRECT_NUMBER"
            result["emoji"] = "❌"
        elif "EXPIRED" in response_upper:
            result["status"] = "DECLINED"
            result["response"] = "CARD_EXPIRED"
            result["emoji"] = "❌"
        elif "NOT_SUPPORTED" in response_upper:
            result["status"] = "DECLINED"
            result["response"] = "CARD_NOT_SUPPORTED"
            result["emoji"] = "❌"
        elif "CAPTCHA" in response_upper:
            result["status"] = "ERROR"
            result["response"] = "CAPTCHA_DETECTED"
            result["emoji"] = "⚠️"
        elif "GENERIC_ERROR" in response_upper:
            result["status"] = "DECLINED"
            result["response"] = "GENERIC_ERROR"
            result["emoji"] = "❌"
        else:
            # Try to extract error message
            try:
                error_data = submit_response.json()
                if "errors" in str(error_data):
                    errors = error_data.get("data", {}).get("submitForCompletion", {}).get("errors", [])
                    if errors:
                        error_msg = errors[0].get("code", "UNKNOWN_ERROR")
                        result["response"] = error_msg.upper()
                elif "reason" in str(error_data):
                    reason = error_data.get("data", {}).get("submitForCompletion", {}).get("reason", "UNKNOWN")
                    result["response"] = reason.upper()
            except:
                result["response"] = response_text[:100] if len(response_text) > 100 else response_text
        
        result["time_taken"] = round(time.time() - start_time, 2)
        return result
        
    except Exception as e:
        result["response"] = f"ERROR: {str(e)[:80]}"
        result["time_taken"] = round(time.time() - start_time, 2)
        return result
    
    finally:
        if own_session:
            try:
                await session.close()
            except:
                pass


# ============================================================================
# CONVENIENCE WRAPPER
# ============================================================================

async def check_card(site_url: str, card: str) -> Dict[str, Any]:
    """
    Simple wrapper to check a card on a Shopify site.
    
    Args:
        site_url: Shopify store URL
        card: Card in format cc|mm|yy|cvv
        
    Returns:
        Dict with checkout result
    """
    return await shopify_checkout(site_url, card)
