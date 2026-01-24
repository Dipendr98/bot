#!/usr/bin/env python3
"""
Test script for debugging /txturl functionality.
Tests lowest product parsing with the provided sites.
"""

import asyncio
import json
import time
import sys
import re

# Add workspace to path
sys.path.insert(0, '/workspace')

from BOT.Charge.Shopify.tls_session import TLSAsyncSession

# Test sites from user
TEST_SITES = """
omiwoods.com
sequoiatrees.com
tworiverstreads.com
mineralmystic.com
soulsent.co
selkiecollection.com
smrtft.com
renardscheese.com
proteinbakery.com
potatoparcel.com
shopalliebess.com
epjewels.co
shopsorce.com
loungewagon.com
tacomoto.co
saniderm.com
owlvenice.com
reanimatorcoffee.com
youmatter.com
vault206.com
gloriousgaming.com
shop.audreyradesign.com
shopmwawoodworks.com
wallpaperyourworld.com
wakingup-store.myshopify.com
sparrow-sleeps.myshopify.com
tommygun-video.myshopify.com
quiltingwithlatinas.com
coton-colors.com
hellopetitepaper.com
brickhouseinthecity.com
ferriswheelpress.com
store.johnprine.com
""".strip().split('\n')

# Constants
FAST_TIMEOUT = 20
STANDARD_TIMEOUT = 45


def normalize_url(url: str) -> str:
    """Normalize URL to standard format."""
    url = url.strip().lower()
    url = url.rstrip('/')
    
    for suffix in ['/products', '/collections', '/cart', '/checkout', '/pages']:
        if suffix in url:
            url = url.split(suffix)[0]
    
    if not url.startswith(('http://', 'https://')):
        url = f"https://{url}"
    
    from urllib.parse import urlparse
    try:
        parsed = urlparse(url)
        domain = parsed.netloc or parsed.path.split('/')[0]
        domain = domain.split(':')[0]
        return f"https://{domain}"
    except Exception:
        return url


async def fetch_products_json(session: TLSAsyncSession, base_url: str) -> list:
    """Fetch products from /products.json endpoint."""
    products_url = f"{base_url}/products.json?limit=100"
    
    try:
        response = await asyncio.wait_for(
            session.get(products_url, follow_redirects=True),
            timeout=FAST_TIMEOUT
        )
        
        if response.status_code != 200:
            return []
        
        raw = response.content.decode("utf-8", errors="ignore")
        
        # Check for HTML response (not JSON)
        if raw.lstrip().startswith("<"):
            return []
        
        data = json.loads(raw)
        products = data.get("products", [])
        
        return products if isinstance(products, list) else []
        
    except asyncio.TimeoutError:
        print(f"  [TIMEOUT] {base_url}")
        return []
    except json.JSONDecodeError:
        print(f"  [JSON ERROR] {base_url}")
        return []
    except Exception as e:
        print(f"  [ERROR] {base_url}: {e}")
        return []


def find_lowest_variant(products: list) -> dict:
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


async def validate_site(url: str, session: TLSAsyncSession) -> dict:
    """Validate a single site and find lowest product."""
    result = {
        "valid": False,
        "url": url,
        "normalized_url": "",
        "gateway": "Unknown",
        "price": "N/A",
        "product_title": None,
        "product_id": None,
        "error": None,
    }
    
    try:
        # Normalize URL
        normalized = normalize_url(url)
        result["normalized_url"] = normalized
        result["url"] = normalized
        
        # Fetch products
        products = await fetch_products_json(session, normalized)
        
        if not products:
            result["error"] = "No products found or not a Shopify store"
            return result
        
        # Find lowest variant
        lowest = find_lowest_variant(products)
        
        if not lowest:
            result["error"] = "No available products with valid price"
            return result
        
        result["valid"] = True
        result["price"] = f"{lowest['price']:.2f}"
        result["product_title"] = lowest['product'].get('title', 'N/A')[:50]
        result["product_id"] = lowest['variant'].get('id')
        result["gateway"] = "Normal"  # Default gateway
        
        return result
        
    except Exception as e:
        result["error"] = str(e)[:100]
        return result


async def test_sites():
    """Test all sites and report results."""
    print("=" * 60)
    print("TXTURL SITE VALIDATION TEST")
    print("=" * 60)
    print(f"Testing {len(TEST_SITES)} sites...\n")
    
    valid_count = 0
    invalid_count = 0
    results = []
    
    start_time = time.time()
    
    async with TLSAsyncSession(timeout_seconds=STANDARD_TIMEOUT) as session:
        for i, site in enumerate(TEST_SITES, 1):
            site = site.strip()
            if not site:
                continue
            
            print(f"[{i:2}/{len(TEST_SITES)}] Testing: {site}...", end=" ")
            
            result = await validate_site(site, session)
            results.append(result)
            
            if result["valid"]:
                valid_count += 1
                print(f"✅ ${result['price']} - {result['product_title'][:30]}...")
            else:
                invalid_count += 1
                print(f"❌ {result['error']}")
            
            # Small delay between requests
            await asyncio.sleep(0.3)
    
    elapsed = time.time() - start_time
    
    print("\n" + "=" * 60)
    print("RESULTS SUMMARY")
    print("=" * 60)
    print(f"Total Sites:   {len(TEST_SITES)}")
    print(f"Valid:         {valid_count}")
    print(f"Invalid:       {invalid_count}")
    print(f"Time:          {elapsed:.2f}s")
    print(f"Success Rate:  {valid_count/len(TEST_SITES)*100:.1f}%")
    
    print("\n" + "=" * 60)
    print("VALID SITES DETAILS")
    print("=" * 60)
    
    for r in results:
        if r["valid"]:
            print(f"  ✅ {r['url']}")
            print(f"     Price: ${r['price']} | Product: {r['product_title'][:40]}...")
            print()
    
    print("=" * 60)
    print("INVALID SITES DETAILS")
    print("=" * 60)
    
    for r in results:
        if not r["valid"]:
            print(f"  ❌ {r['url']}")
            print(f"     Error: {r['error']}")
            print()


if __name__ == "__main__":
    asyncio.run(test_sites())
