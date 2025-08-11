import requests
from bs4 import BeautifulSoup
import time
import json
from datetime import datetime
import re
from urllib.parse import urljoin
import os
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

class LabubbuMonitor:
    def __init__(self, check_interval=300, save_state=True):
        """
        Initialize the Labubu monitor
        
        Args:
            check_interval: Time between checks in seconds (default 5 minutes)
            save_state: Whether to save state between runs
        """
        self.base_url = "https://www.popmart.com"
        # Using direct search URL with LABUBU brand ID filter
        self.search_url = "https://www.popmart.com/us/search/LABUBU?categoryIds=73&brandIds=15"
        self.check_interval = check_interval
        self.save_state = save_state
        self.driver = None
        self.product_states = self.load_state() if save_state else {}
        
    def load_state(self):
        """Load previous product states from file"""
        if os.path.exists('labubu_state.json'):
            try:
                with open('labubu_state.json', 'r') as f:
                    return json.load(f)
            except:
                return {}
        return {}
    
    def save_state_to_file(self):
        """Save current product states to file"""
        if self.save_state:
            with open('labubu_state.json', 'w') as f:
                json.dump(self.product_states, f, indent=2)
                
    def initialize_driver(self):
        """Initialize Chrome driver with optimized settings"""
        if not self.driver:
            options = Options()
            options.add_argument('--headless')
            options.add_argument('--disable-gpu')
            options.add_argument('--no-sandbox')
            options.add_argument('--disable-dev-shm-usage')
            options.add_argument('--window-size=1920,1080')
            # Modern browser UA to avoid detection
            options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
            
            # Additional performance optimizations
            options.add_argument('--disable-extensions')
            options.add_argument('--disable-infobars')
            options.add_argument('--disable-notifications')
            options.page_load_strategy = 'eager'  # Don't wait for all resources to load
            
            self.driver = webdriver.Chrome(options=options)
            self.driver.implicitly_wait(10)

    def wait_for_element(self, selector, timeout=15, by=By.CSS_SELECTOR):
        """Wait for an element to be present and visible"""
        try:
            element = WebDriverWait(self.driver, timeout).until(
                EC.presence_of_element_located((by, selector))
            )
            return element
        except TimeoutException:
            print(f"Timeout waiting for element: {selector}")
            return None

    def parse_product_card(self, card):
        """Parse a product card element and extract details"""
        product = {
            'id': '',
            'name': '',
            'url': '',
            'price': '',
            'available': False,
            'image': ''
        }

        try:
            # Get product URL and ID
            link = card.find('a', href=True)
            if link:
                product['url'] = urljoin(self.base_url, link.get('href'))
                # Extract product ID from URL
                product['id'] = link.get('href').split('/')[-1]

            # Get product name (title)
            # First try to get the subtitle (series name)
            subtitle_elem = card.find('div', class_='index_itemSubTitle__mX6v_')
            title_elem = card.find('div', class_='index_itemTitle__WaT6_')
            
            if subtitle_elem and title_elem:
                product['name'] = f"{subtitle_elem.text.strip()} - {title_elem.text.strip()}"
            elif title_elem:
                product['name'] = title_elem.text.strip()

            # Get price
            price_elem = card.find('div', class_='index_itemPrice__AQoMy')
            if price_elem:
                product['price'] = price_elem.text.strip()

            # Check availability (product is unavailable if it has the out of stock tag)
            out_of_stock_tag = card.find('span', class_='index_tagStyle__7EhOx')
            product['available'] = not bool(out_of_stock_tag)

            # Get product image
            img_elem = card.find('img', class_='ant-image-img')
            if img_elem:
                product['image'] = img_elem.get('src', '')

        except Exception as e:
            print(f"Error parsing product card: {e}")

        return product

    def get_products(self):
        """Get all Labubu products from search results"""
        products = []
        page = 1
        max_retries = 3
        
        try:
            self.initialize_driver()
            
            while True:
                url = f"{self.search_url}&page={page}"
                print(f"Checking page {page}...")
                
                retry_count = 0
                while retry_count < max_retries:
                    try:
                        self.driver.get(url)
                        print("Waiting 10 seconds for page to fully load...")
                        time.sleep(10)  # Wait for full page load
                        # Wait for product cards to load
                        self.wait_for_element('.index_productItemContainer__rDwtr')
                        break
                    except Exception as e:
                        retry_count += 1
                        print(f"Error loading page {page} (attempt {retry_count}): {e}")
                        if retry_count == max_retries:
                            return products
                        time.sleep(5)

                # Parse the page
                soup = BeautifulSoup(self.driver.page_source, 'html.parser')
                
                # Find all product cards
                product_cards = soup.find_all('div', class_='index_productItemContainer__rDwtr')
                
                if not product_cards:
                    print(f"No products found on page {page}")
                    break

                # Parse each product card
                for card in product_cards:
                    product = self.parse_product_card(card)
                    if product['name']:  # Only add if we got a valid product
                        products.append(product)

                print(f"Found {len(product_cards)} products on page {page}")

                # Check for next page
                if not self.has_next_page(soup):
                    break

                page += 1
                time.sleep(2)  # Respectful delay between pages

        except Exception as e:
            print(f"Error fetching products: {e}")
        
        return products

    def has_next_page(self, soup):
        """Check if there's a next page in search results"""
        # Look for pagination element
        pagination = soup.find('div', class_='index_pagination__RPTOo')
        if not pagination:
            return False
            
        # If we have pagination, check if current page is the last one
        current_page = pagination.find('span', class_=re.compile('active|current'))
        next_page = current_page.find_next('a') if current_page else None
        
        return bool(next_page)
    
    def notify_available(self, product):
        """Send notification for available product"""
        print("\n" + "="*60)
        print("🎉 LABUBU AVAILABLE! 🎉")
        print(f"Product: {product['name']}")
        print(f"Price: {product['price']}")
        print(f"URL: {product['url']}")
        print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("="*60 + "\n")
        
        # Log to file
        with open('labubu_available.log', 'a') as f:
            f.write(f"\n{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - AVAILABLE\n")
            f.write(f"Product: {product['name']}\n")
            f.write(f"Price: {product['price']}\n")
            f.write(f"URL: {product['url']}\n")
            f.write("-"*40 + "\n")

    def run(self):
        """Main monitoring loop"""
        print("Starting Labubu Monitor")
        print(f"Monitoring: {self.search_url}")
        print(f"Check interval: {self.check_interval} seconds")
        print("-"*60)
        
        while True:
            try:
                print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Starting scan...")
                
                # Get all products
                products = self.get_products()
                print(f"Found {len(products)} total Labubu products")
                
                # Track availability changes
                available_count = 0
                for product in products:
                    product_id = product['id']
                    was_available = self.product_states.get(product_id, {}).get('available', False)
                    
                    if product['available']:
                        available_count += 1
                        print(f"✓ Available: {product['name'][:50]}")
                        
                        # Notify if newly available
                        if not was_available:
                            self.notify_available(product)
                    else:
                        print(f"✗ Not available: {product['name'][:50]}")
                    
                    # Update state
                    self.product_states[product_id] = {
                        'name': product['name'],
                        'url': product['url'],
                        'price': product['price'],
                        'available': product['available'],
                        'last_checked': datetime.now().isoformat()
                    }
                
                # Save state
                self.save_state_to_file()
                
                # Summary
                print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Scan complete")
                print(f"Available: {available_count}/{len(products)} products")
                print(f"Next check in {self.check_interval} seconds...")
                print("-"*60)
                
            except KeyboardInterrupt:
                print("\nMonitoring stopped by user")
                break
            except Exception as e:
                print(f"Error during monitoring: {e}")
                print(f"Retrying in {self.check_interval} seconds...")
                
                # Reset the driver on error
                if self.driver:
                    try:
                        self.driver.quit()
                    except:
                        pass
                    self.driver = None
            
            time.sleep(self.check_interval)
        
        # Clean up
        if self.driver:
            try:
                self.driver.quit()
            except:
                pass

def quick_check():
    """Do a single check of all Labubu products"""
    monitor = LabubbuMonitor()
    
    print("Performing quick check of all Labubu products...")
    products = monitor.get_products()
    
    available = [p for p in products if p['available']]
    unavailable = [p for p in products if not p['available']]
    
    print("\n" + "="*60)
    print(f"SUMMARY: {len(available)} available, {len(unavailable)} unavailable")
    print("="*60)
    
    if available:
        print("\n✅ AVAILABLE PRODUCTS:")
        for p in available:
            print(f"  - {p['name']}")
            print(f"    URL: {p['url']}")
            print(f"    Price: {p['price']}")
    else:
        print("\n❌ No products currently available")
    
    return available

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == 'quick':
        # Run a single check
        quick_check()
    else:
        # Run continuous monitoring
        monitor = LabubbuMonitor(
            check_interval=5  # Check every 5 minutes
        )
        
        try:
            monitor.run()
        except KeyboardInterrupt:
            print("\nMonitoring stopped")
            monitor.save_state_to_file()
