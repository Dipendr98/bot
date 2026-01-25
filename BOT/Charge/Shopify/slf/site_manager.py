"""
Unified Site Manager for Shopify Checkers
Manages all user sites in a single storage and provides site rotation for retry logic.
Bulletproof JSON load/save: atomic writes, retries, robust parsing.
"""

import os
import json
import random
import tempfile
import shutil
from typing import List, Dict, Optional, Tuple, Any
from dataclasses import dataclass

# Storage paths
UNIFIED_SITES_PATH = "DATA/user_sites.json"
LEGACY_SITES_PATH = "DATA/sites.json"
LEGACY_TXT_SITES_PATH = "DATA/txtsite.json"
LOAD_SAVE_RETRIES = 3


@dataclass
class SiteInfo:
    """Represents a single site with its details."""
    url: str
    gateway: str
    price: str = "N/A"
    active: bool = True
    fail_count: int = 0


def ensure_data_directory():
    """Ensure DATA directory exists."""
    os.makedirs("DATA", exist_ok=True)


def _robust_json_load(path: str) -> Optional[Dict[str, Any]]:
    """Load JSON with retries, BOM stripping, and graceful decode errors."""
    raw = None
    for _ in range(LOAD_SAVE_RETRIES):
        try:
            with open(path, "r", encoding="utf-8-sig") as f:
                raw = f.read()
            if not raw or not raw.strip():
                return {}
            text = raw.strip()
            if text.startswith("\ufeff"):
                text = text[1:]
            data = json.loads(text)
            return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, IOError, OSError):
            continue
    return None


def load_unified_sites() -> Dict[str, List[Dict]]:
    """
    Load all sites from unified storage.
    If unified storage doesn't exist or is corrupt, migrate from legacy storage.
    Robust against JSON parse errors and partial writes.
    """
    ensure_data_directory()

    if os.path.exists(UNIFIED_SITES_PATH):
        data = _robust_json_load(UNIFIED_SITES_PATH)
        if data is not None and isinstance(data, dict):
            return data

    unified_data: Dict[str, List[Dict]] = {}

    if os.path.exists(LEGACY_SITES_PATH):
        leg = _robust_json_load(LEGACY_SITES_PATH)
        if isinstance(leg, dict):
            for user_id, site_info in leg.items():
                if isinstance(site_info, dict) and site_info.get("site"):
                    if user_id not in unified_data:
                        unified_data[user_id] = []
                    unified_data[user_id].insert(0, {
                        "url": site_info.get("site", ""),
                        "gateway": site_info.get("gate", "Unknown"),
                        "price": "N/A",
                        "active": True,
                        "fail_count": 0,
                        "is_primary": True,
                    })

    if os.path.exists(LEGACY_TXT_SITES_PATH):
        leg = _robust_json_load(LEGACY_TXT_SITES_PATH)
        if isinstance(leg, dict):
            for user_id, sites_list in leg.items():
                if not isinstance(sites_list, list):
                    continue
                if user_id not in unified_data:
                    unified_data[user_id] = []
                existing = {s.get("url", "").lower().rstrip("/") for s in unified_data[user_id]}
                for site_info in sites_list:
                    if not isinstance(site_info, dict):
                        continue
                    site_url = site_info.get("site", "")
                    if site_url and site_url.lower().rstrip("/") not in existing:
                        is_first = len(unified_data[user_id]) == 0
                        unified_data[user_id].append({
                            "url": site_url,
                            "gateway": site_info.get("gate", "Unknown"),
                            "price": "N/A",
                            "active": True,
                            "fail_count": 0,
                            "is_primary": is_first,
                        })
                        existing.add(site_url.lower().rstrip("/"))

    if unified_data:
        save_unified_sites(unified_data)
    return unified_data


def save_unified_sites(data: Dict[str, List[Dict]]) -> None:
    """Save all sites to unified storage and legacy files. Atomic write + retries."""
    ensure_data_directory()
    if not isinstance(data, dict):
        return

    legacy_sites: Dict[str, Dict[str, str]] = {}
    legacy_txt: Dict[str, List[Dict[str, str]]] = {}
    for user_id, sites in data.items():
        if sites:
            primary = next((s for s in sites if s.get("is_primary")), sites[0])
            legacy_sites[user_id] = {"site": primary["url"], "gate": primary["gateway"]}
            legacy_txt[user_id] = [{"site": s["url"], "gate": s["gateway"]} for s in sites]

    def _dump(obj: Any) -> str:
        return json.dumps(obj, indent=4, ensure_ascii=False)

    def _atomic_write(path: str, content: str) -> bool:
        d = os.path.dirname(path)
        fd, tmp = tempfile.mkstemp(dir=d or ".", prefix=".site_tmp_", suffix=".json")
        try:
            os.write(fd, content.encode("utf-8"))
            os.close(fd)
            shutil.move(tmp, path)
            return True
        except Exception:
            try:
                os.close(fd)
            except Exception:
                pass
            try:
                os.remove(tmp)
            except Exception:
                pass
            return False

    for _ in range(LOAD_SAVE_RETRIES):
        try:
            if _atomic_write(UNIFIED_SITES_PATH, _dump(data)):
                _atomic_write(LEGACY_SITES_PATH, _dump(legacy_sites))
                _atomic_write(LEGACY_TXT_SITES_PATH, _dump(legacy_txt))
                return
        except Exception:
            continue


def get_user_sites(user_id: str) -> List[Dict]:
    """Get all sites for a user."""
    data = load_unified_sites()
    return data.get(str(user_id), [])


def get_user_active_sites(user_id: str) -> List[Dict]:
    """Get all active sites for a user."""
    sites = get_user_sites(user_id)
    return [s for s in sites if s.get("active", True)]


def get_primary_site(user_id: str) -> Optional[Dict]:
    """Get user's primary site (first added or marked primary)."""
    sites = get_user_sites(user_id)
    if not sites:
        return None
    
    # Find explicitly marked primary
    for site in sites:
        if site.get("is_primary"):
            return site
    
    # Return first site as primary
    return sites[0] if sites else None


def add_site_for_user(user_id: str, url: str, gateway: str, price: str = "N/A", set_primary: bool = False) -> bool:
    """
    Add a site for a user to unified storage.
    If set_primary is True, this becomes the user's primary site.
    """
    try:
        data = load_unified_sites()
        user_id = str(user_id)
        
        if user_id not in data:
            data[user_id] = []
        
        # Check for duplicate
        existing_urls = {s.get("url", "").lower().rstrip("/") for s in data[user_id]}
        url_normalized = url.lower().rstrip("/")

        if url_normalized in existing_urls:
            if set_primary:
                for s in data[user_id]:
                    s["is_primary"] = (s.get("url", "").lower().rstrip("/") == url_normalized)
                save_unified_sites(data)
            return True  # Already exists

        # Create new site entry
        is_first = len(data[user_id]) == 0
        site_entry = {
            "url": url,
            "gateway": gateway,
            "price": price,
            "active": True,
            "fail_count": 0,
            "is_primary": set_primary or is_first  # First site is primary
        }
        
        if set_primary:
            # Remove primary flag from other sites
            for site in data[user_id]:
                site["is_primary"] = False
            # Insert at beginning
            data[user_id].insert(0, site_entry)
        else:
            data[user_id].append(site_entry)
        
        save_unified_sites(data)
        return True
    except Exception as e:
        print(f"Error adding site: {e}")
        return False


def add_sites_batch(user_id: str, sites: List[Dict]) -> int:
    """
    Add multiple sites for a user.
    
    Args:
        user_id: User ID
        sites: List of dicts with 'url', 'gateway', 'price' keys
        
    Returns:
        Number of sites added
    """
    try:
        data = load_unified_sites()
        user_id = str(user_id)
        
        if user_id not in data:
            data[user_id] = []
        
        existing_urls = {s.get("url", "").lower().rstrip("/") for s in data[user_id]}
        added_count = 0
        
        for site_info in sites:
            url = site_info.get("url", "").rstrip("/")
            if url and url.lower() not in existing_urls:
                is_first = len(data[user_id]) == 0
                site_entry = {
                    "url": url,
                    "gateway": site_info.get("gateway", "Unknown"),
                    "price": site_info.get("price", "N/A"),
                    "active": True,
                    "fail_count": 0,
                    "is_primary": is_first  # First site is primary
                }
                data[user_id].append(site_entry)
                existing_urls.add(url.lower())
                added_count += 1
        
        if added_count > 0:
            save_unified_sites(data)
        
        return added_count
    except Exception as e:
        print(f"Error adding sites batch: {e}")
        return 0


def remove_site_for_user(user_id: str, url: str) -> bool:
    """Remove a site from user's list."""
    try:
        data = load_unified_sites()
        user_id = str(user_id)
        
        if user_id not in data:
            return False
        
        url_lower = url.lower().rstrip("/")
        original_count = len(data[user_id])
        
        data[user_id] = [
            s for s in data[user_id]
            if s.get("url", "").lower().rstrip("/") != url_lower
        ]
        
        if len(data[user_id]) < original_count:
            # If we removed the primary, mark the first remaining as primary
            if data[user_id] and not any(s.get("is_primary") for s in data[user_id]):
                data[user_id][0]["is_primary"] = True
            save_unified_sites(data)
            return True
        
        return False
    except Exception:
        return False


def clear_user_sites(user_id: str) -> int:
    """Clear all sites for a user. Returns count of removed sites."""
    try:
        data = load_unified_sites()
        user_id = str(user_id)
        
        if user_id not in data:
            return 0
        
        count = len(data[user_id])
        del data[user_id]
        save_unified_sites(data)
        return count
    except Exception:
        return 0


def mark_site_failed(user_id: str, url: str):
    """Increment fail count for a site (for adaptive rotation)."""
    try:
        data = load_unified_sites()
        user_id = str(user_id)
        
        if user_id not in data:
            return
        
        url_lower = url.lower().rstrip("/")
        for site in data[user_id]:
            if site.get("url", "").lower().rstrip("/") == url_lower:
                site["fail_count"] = site.get("fail_count", 0) + 1
                # Deactivate after too many failures
                if site["fail_count"] >= 5:
                    site["active"] = False
                break
        
        save_unified_sites(data)
    except Exception:
        pass


def reset_site_fail_count(user_id: str, url: str):
    """Reset fail count for a site after successful check."""
    try:
        data = load_unified_sites()
        user_id = str(user_id)
        
        if user_id not in data:
            return
        
        url_lower = url.lower().rstrip("/")
        for site in data[user_id]:
            if site.get("url", "").lower().rstrip("/") == url_lower:
                site["fail_count"] = 0
                site["active"] = True
                break
        
        save_unified_sites(data)
    except Exception:
        pass


class SiteRotator:
    """
    Handles site rotation for retry logic on captcha/errors.
    Rotates through user's sites until a real response is obtained.
    """
    
    def __init__(self, user_id: str, max_retries: int = 3):
        self.user_id = str(user_id)
        self.max_retries = max_retries
        self.sites = get_user_active_sites(self.user_id)
        self.current_index = 0
        self.tried_sites = set()
        self.retry_count = 0
    
    def has_sites(self) -> bool:
        """Check if user has any sites."""
        return len(self.sites) > 0
    
    def get_current_site(self) -> Optional[Dict]:
        """Get current site in rotation."""
        if not self.sites:
            return None
        return self.sites[self.current_index % len(self.sites)]
    
    def get_next_site(self) -> Optional[Dict]:
        """Get next site in rotation, returns None if all tried."""
        if not self.sites:
            return None
        
        # Mark current as tried
        current = self.get_current_site()
        if current:
            self.tried_sites.add(current.get("url", "").lower())
        
        # Find next untried site
        for _ in range(len(self.sites)):
            self.current_index = (self.current_index + 1) % len(self.sites)
            next_site = self.sites[self.current_index]
            if next_site.get("url", "").lower() not in self.tried_sites:
                return next_site
        
        # All sites tried, but we can still retry with rotation
        if self.retry_count < self.max_retries:
            self.retry_count += 1
            self.tried_sites.clear()
            self.current_index = (self.current_index + 1) % len(self.sites)
            return self.sites[self.current_index]
        
        return None
    
    def get_random_site(self) -> Optional[Dict]:
        """Get a random site from the list."""
        if not self.sites:
            return None
        return random.choice(self.sites)
    
    def should_retry(self, response: str) -> bool:
        """
        Check if we should retry with another site based on response.
        Returns True for captcha/site errors that warrant retry.
        """
        if not response:
            return True
        
        response_upper = response.upper()
        
        # Retry on captcha and site-related errors
        retry_keywords = [
            "CAPTCHA", "HCAPTCHA", "RECAPTCHA", "CHALLENGE", "VERIFY",
            "SITE_EMPTY", "SITE_HTML", "SITE_CAPTCHA", "SITE_HTTP", "SITE_CONNECTION",
            "SITE_DEAD", "SITE DEAD", "SITE_NO_PRODUCTS", "SITE_PRODUCTS_EMPTY", "SITE_INVALID_JSON",
            "CART_ERROR", "CART_HTML", "CART_INVALID", "CART_CREATION",
            "SESSION_ERROR", "SESSION_ID", "SESSION_INVALID",
            "NO_AVAILABLE_PRODUCTS", "BUILD", "NEGOTIATE", "DELIVERY_ERROR",
            "CHECKOUT_HTML", "CHECKOUT_TOKENS", "CHECKOUT_HTTP",
            "TIMEOUT", "CONNECTION", "RATE_LIMIT", "BLOCKED", "PROXY_ERROR",
            "429", "502", "503", "504",
            "RECEIPT_EMPTY", "SUBMIT_INVALID_JSON", "SUBMIT_HTTP",
        ]
        
        return any(keyword in response_upper for keyword in retry_keywords)
    
    def is_real_response(self, response: str) -> bool:
        """
        Check if this is a real card response (not site/captcha error).
        Real responses are: charged, declined, CCN, CVV issues, etc.
        """
        if not response:
            return False
        
        response_upper = response.upper()
        
        # Real card responses (success or failure)
        real_keywords = [
            # Success
            "CHARGED", "ORDER_PLACED", "THANK_YOU", "SUCCESS", "COMPLETE",
            # CCN/Live (CVV issues = card is valid)
            "3DS", "3D_SECURE", "AUTHENTICATION", "INCORRECT_CVC", "INVALID_CVC",
            "INCORRECT_ZIP", "INCORRECT_ADDRESS", "MISMATCHED", "INSUFFICIENT_FUNDS",
            # Declined (card issues)
            "CARD_DECLINED", "DECLINED", "GENERIC_DECLINE", "DO_NOT_HONOR",
            "EXPIRED", "INVALID_NUMBER", "LOST", "STOLEN", "PICKUP", "FRAUD",
            "RESTRICTED", "REVOKED", "INVALID_ACCOUNT", "NOT_SUPPORTED",
            "RISKY"
        ]
        
        return any(keyword in response_upper for keyword in real_keywords)
    
    def mark_current_failed(self):
        """Mark current site as failed (for adaptive rotation)."""
        current = self.get_current_site()
        if current:
            mark_site_failed(self.user_id, current.get("url", ""))
    
    def mark_current_success(self):
        """Mark current site as successful (reset fail count)."""
        current = self.get_current_site()
        if current:
            reset_site_fail_count(self.user_id, current.get("url", ""))
    
    def get_site_count(self) -> int:
        """Get total number of active sites."""
        return len(self.sites)
    
    def get_sites_tried_count(self) -> int:
        """Get number of sites tried so far."""
        return len(self.tried_sites)


def get_site_and_gateway(user_id: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Get user's primary site and gateway.
    Returns (site_url, gateway) tuple.
    """
    site = get_primary_site(user_id)
    if site:
        return site.get("url"), site.get("gateway", "Unknown")
    return None, None
