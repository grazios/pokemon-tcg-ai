#!/Users/molt/.openclaw/workspace/pokemon-tcg-ai/venv/bin/python
"""
Simple test for the card scraper functionality.
"""

import requests
from bs4 import BeautifulSoup
import re

def test_fetch_cards(set_code):
    """Test fetching cards from a set."""
    url = f"https://limitlesstcg.com/cards/{set_code}"
    print(f"Testing URL: {url}")
    
    try:
        # Create session with user agent
        session = requests.Session()
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        })
        
        response = session.get(url, timeout=10)
        response.raise_for_status()
        print(f"Status: {response.status_code}")
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Look for card links
        card_links = soup.find_all('a', href=re.compile(rf'/cards/{set_code}/\d+[a-z]?'))
        print(f"Found {len(card_links)} card links")
        
        card_numbers = []
        for link in card_links[:10]:  # First 10 for testing
            href = link.get('href')
            match = re.search(rf'/cards/{set_code}/(\d+[a-z]?)', href)
            if match:
                card_numbers.append(match.group(1))
                
        card_numbers = sorted(list(set(card_numbers)), key=lambda x: (int(re.search(r'\d+', x).group()), x))
        print(f"First 10 card numbers: {card_numbers[:10]}")
        
        # Test individual card fetch
        if card_numbers:
            test_card = card_numbers[0]
            card_url = f"https://limitlesstcg.com/cards/{set_code}/{test_card}"
            print(f"Testing individual card: {card_url}")
            
            card_response = session.get(card_url, timeout=10)
            card_response.raise_for_status()
            print(f"Individual card status: {card_response.status_code}")
            
            card_soup = BeautifulSoup(card_response.text, 'html.parser')
            title_elem = card_soup.find('h1') or card_soup.find('title')
            if title_elem:
                print(f"Card title: {title_elem.get_text().strip()}")
        
        return True
        
    except Exception as e:
        print(f"Error: {e}")
        return False

if __name__ == '__main__':
    print("Testing scraper functionality...")
    test_fetch_cards("SVI")