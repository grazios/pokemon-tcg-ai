#!/Users/molt/.openclaw/workspace/pokemon-tcg-ai/venv/bin/python
"""
Generate card list for GHI regulation sets.
Creates a text file with all card IDs that can be used with scrape_cards.py
"""

import requests
from bs4 import BeautifulSoup
import re
import time
from pathlib import Path

# GHI regulation sets (SVI and later)
GHI_SETS = {
    'SVI': 'Scarlet & Violet',
    'PAL': 'Paldea Evolved',
    'OBF': 'Obsidian Flames',
    'MEW': 'Pokémon 151',
    'PAR': 'Paradox Rift',
    'PAF': 'Paldean Fates',
    'TEF': 'Temporal Forces',
    'TWM': 'Twilight Masquerade',
    'SFA': 'Shrouded Fable',
    'SCR': 'Stellar Crown',
    'SSP': 'Surging Sparks',
    'PRE': 'Prismatic Evolutions',
    'JTG': 'Journey Together',
    'DRI': 'Destined Rivals',
    'ASC': 'Ascended Heroes',
    'PFL': 'Phantasmal Flames',
    'MEG': 'Mega Evolutions ex',
    'MEE': 'Mega Evolutions ex Energy',
    'SVP': 'SV Promo',
    'SVE': 'SV Energy'
}

def fetch_set_cards(session, set_code):
    """Fetch all card numbers from a set page."""
    url = f"https://limitlesstcg.com/cards/{set_code}"
    print(f"Fetching {set_code} ({GHI_SETS.get(set_code, 'Unknown')})...")
    
    try:
        response = session.get(url, timeout=15)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Look for card links
        card_links = soup.find_all('a', href=re.compile(rf'/cards/{set_code}/\d+[a-z]?'))
        
        card_numbers = []
        for link in card_links:
            href = link.get('href')
            match = re.search(rf'/cards/{set_code}/(\d+[a-z]?)', href)
            if match:
                card_numbers.append(match.group(1))
        
        # Remove duplicates and sort
        card_numbers = sorted(list(set(card_numbers)), key=lambda x: (int(re.search(r'\d+', x).group()), x))
        
        print(f"  Found {len(card_numbers)} cards")
        return card_numbers
        
    except Exception as e:
        print(f"  Error: {e}")
        return []

def main():
    # Create session
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
    })
    
    all_cards = []
    set_stats = {}
    
    print("Generating card list for GHI regulation sets...\n")
    
    for set_code in GHI_SETS.keys():
        card_numbers = fetch_set_cards(session, set_code)
        
        if card_numbers:
            set_cards = [f"{set_code} {num}" for num in card_numbers]
            all_cards.extend(set_cards)
            set_stats[set_code] = len(card_numbers)
        else:
            set_stats[set_code] = 0
        
        # Rate limiting
        time.sleep(1.0)
    
    # Save to file
    output_file = Path('/Users/molt/.openclaw/workspace/pokemon-tcg-ai/data/ghi_cards_list.txt')
    output_file.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_file, 'w') as f:
        for card in all_cards:
            f.write(f"{card}\n")
    
    print(f"\n=== CARD LIST GENERATED ===")
    print(f"Total cards: {len(all_cards)}")
    print(f"Saved to: {output_file}")
    print("\nBreakdown by set:")
    for set_code, count in set_stats.items():
        set_name = GHI_SETS.get(set_code, 'Unknown')
        print(f"  {set_code} ({set_name}): {count} cards")
    
    print(f"\nNext step: Run the following command to scrape all cards:")
    print(f"./venv/bin/python scripts/scrape_cards.py --file data/ghi_cards_list.txt --rate-limit 0.5 -v")

if __name__ == '__main__':
    main()