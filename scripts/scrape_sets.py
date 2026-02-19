#!/Users/molt/.openclaw/workspace/pokemon-tcg-ai/venv/bin/python
"""
Pokémon TCG Set Scraper

Scrapes all cards from specific sets from Limitless TCG.
Supports GHI regulation sets (SVI and later).
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Dict, List, Set as SetType
import requests
from bs4 import BeautifulSoup


class SetScraper:
    def __init__(self, rate_limit: float = 0.5, verbose: bool = False):
        self.rate_limit = rate_limit
        self.verbose = verbose
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        })
        
        # GHI regulation sets (SVI and later)
        self.GHI_SETS = {
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
    
    def log(self, message: str) -> None:
        """Log message if verbose mode is enabled."""
        if self.verbose:
            print(f"[INFO] {message}")
        else:
            print(message)
    
    def fetch_set_cards(self, set_code: str) -> List[str]:
        """Fetch all card numbers from a set page."""
        url = f"https://limitlesstcg.com/cards/{set_code}"
        self.log(f"Fetching card list from {url}")
        
        try:
            response = self.session.get(url, timeout=15)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            card_numbers = []
            
            # Look for card links in the format /cards/SET/NUMBER
            # They appear as <a href="/cards/SVI/1"><img ...></a>
            card_links = soup.find_all('a', href=re.compile(rf'/cards/{set_code}/\d+[a-z]?'))
            
            for link in card_links:
                href = link.get('href')
                # Extract card number from URL
                match = re.search(rf'/cards/{set_code}/(\d+[a-z]?)', href)
                if match:
                    card_numbers.append(match.group(1))
            
            # Remove duplicates and sort properly (numeric then alphabetic)
            card_numbers = sorted(list(set(card_numbers)), key=lambda x: (int(re.search(r'\d+', x).group()), x))
            
            self.log(f"Found {len(card_numbers)} cards in {set_code}")
            return card_numbers
            
        except Exception as e:
            self.log(f"Failed to fetch {set_code} card list: {e}")
            return []
    
    def parse_card_data(self, soup: BeautifulSoup, set_code: str, number: str) -> Dict:
        """Parse card data from Limitless TCG HTML."""
        card_data = {
            "id": f"{set_code}-{number}",
            "set": set_code,
            "number": number
        }
        
        # Card name (usually in h1 or title)
        title_elem = soup.find('h1') or soup.find('title')
        if title_elem:
            title_text = title_elem.get_text().strip()
            # Extract name before set info
            name_match = re.match(r'^(.+?)\s*\(', title_text)
            if name_match:
                card_data["name"] = name_match.group(1).strip()
            else:
                card_data["name"] = title_text.split(' - ')[0].strip()
        
        # Look for card details in various containers
        self._extract_pokemon_data(soup, card_data)
        self._extract_trainer_data(soup, card_data)
        self._extract_energy_data(soup, card_data)
        
        return card_data
    
    def _extract_pokemon_data(self, soup: BeautifulSoup, card_data: Dict) -> None:
        """Extract Pokémon-specific data."""
        # Look for card details section
        card_text_title = soup.find('p', class_='card-text-title')
        card_text_type = soup.find('p', class_='card-text-type')
        
        if card_text_title:
            title_text = card_text_title.get_text()
            
            # Extract HP
            hp_match = re.search(r'(\d+)\s*HP', title_text)
            if hp_match:
                card_data["hp"] = int(hp_match.group(1))
                card_data["category"] = "pokemon"
            
            # Extract type
            type_match = re.search(r'-\s*(Fire|Water|Grass|Electric|Psychic|Fighting|Darkness|Metal|Fairy|Dragon|Colorless)', title_text)
            if type_match:
                type_name = type_match.group(1)
                # Convert Darkness to Dark for consistency
                if type_name == "Darkness":
                    type_name = "Dark"
                card_data["type"] = type_name
        
        if card_text_type:
            type_text = card_text_type.get_text()
            
            # Extract stage
            stage_match = re.search(r'(Basic|Stage\s*[12])', type_text)
            if stage_match:
                card_data["stage"] = stage_match.group(1)
            
            # Extract evolution info
            evolves_match = re.search(r'Evolves from\s+(.+)', type_text)
            if evolves_match:
                card_data["evolvesFrom"] = evolves_match.group(1).strip()
        
        # Extract abilities
        abilities = []
        ability_divs = soup.find_all('div', class_='card-text-ability')
        for ability_div in ability_divs:
            ability_info = ability_div.find('p', class_='card-text-ability-info')
            ability_effect = ability_div.find('p', class_='card-text-ability-effect')
            
            if ability_info and ability_effect:
                info_text = ability_info.get_text().strip()
                effect_text = ability_effect.get_text().strip()
                
                # Parse ability name
                if "Ability:" in info_text:
                    ability_name = info_text.replace("Ability:", "").strip()
                    abilities.append({
                        "name": ability_name,
                        "text": effect_text
                    })
                elif info_text == "Tera":
                    abilities.append({
                        "name": "Tera",
                        "text": effect_text
                    })
        
        if abilities:
            if len(abilities) == 1:
                card_data["ability"] = abilities[0]
            else:
                card_data["abilities"] = abilities
        
        # Extract attacks
        attacks = []
        attack_divs = soup.find_all('div', class_='card-text-attack')
        for attack_div in attack_divs:
            attack_info = attack_div.find('p', class_='card-text-attack-info')
            attack_effect = attack_div.find('p', class_='card-text-attack-effect')
            
            if attack_info:
                info_text = attack_info.get_text().strip()
                effect_text = attack_effect.get_text().strip() if attack_effect else ""
                
                # Parse attack name and damage
                attack_match = re.search(r'(.+?)\s+(\d+[+]?)$', info_text.split('\n')[-1])
                if attack_match:
                    attack_name = attack_match.group(1).strip()
                    damage_str = attack_match.group(2)
                    
                    attack_data = {
                        "name": attack_name,
                        "damage": damage_str,
                        "text": effect_text
                    }
                    
                    # Extract energy cost from symbols
                    cost_symbols = attack_info.find_all('span', class_='ptcg-symbol')
                    if cost_symbols:
                        cost = []
                        for symbol in cost_symbols:
                            symbol_text = symbol.get_text()
                            # Convert symbols to energy types
                            energy_map = {
                                'R': 'Fire', 'W': 'Water', 'G': 'Grass', 'L': 'Electric',
                                'P': 'Psychic', 'F': 'Fighting', 'D': 'Dark', 'M': 'Metal',
                                'Y': 'Fairy', 'N': 'Dragon', 'C': 'Colorless'
                            }
                            for i in range(len(symbol_text)):
                                char = symbol_text[i]
                                if char in energy_map:
                                    cost.append(energy_map[char])
                        attack_data["cost"] = cost
                    
                    attacks.append(attack_data)
        
        if attacks:
            card_data["attacks"] = attacks
        
        # Extract weakness/resistance/retreat
        card_wrr = soup.find('p', class_='card-text-wrr')
        if card_wrr:
            wrr_text = card_wrr.get_text()
            
            weakness_match = re.search(r'Weakness:\s*([^\n\r]+)', wrr_text)
            if weakness_match and "none" not in weakness_match.group(1).lower():
                card_data["weakness"] = weakness_match.group(1).strip()
            
            retreat_match = re.search(r'Retreat:\s*(\d+)', wrr_text)
            if retreat_match:
                card_data["retreatCost"] = int(retreat_match.group(1))
        
        # Check for ex/GX/V rule
        name = card_data.get("name", "")
        if re.search(r'\bex\b', name, re.IGNORECASE):
            card_data["isEx"] = True
        if re.search(r'\bGX\b', name):
            card_data["isGX"] = True
        if re.search(r'\bV\b', name) and not re.search(r'VMAX|VSTAR', name):
            card_data["isV"] = True
        if re.search(r'\bVMAX\b', name):
            card_data["isVMAX"] = True
        if re.search(r'\bVSTAR\b', name):
            card_data["isVSTAR"] = True
    
    def _extract_trainer_data(self, soup: BeautifulSoup, card_data: Dict) -> None:
        """Extract Trainer card data."""
        card_text_type = soup.find('p', class_='card-text-type')
        
        if card_text_type:
            type_text = card_text_type.get_text()
            
            # Check for trainer types
            trainer_types = ["Supporter", "Item", "Stadium", "Tool"]
            for trainer_type in trainer_types:
                if trainer_type in type_text:
                    card_data["category"] = "trainer"
                    card_data["trainerType"] = trainer_type
                    break
        
        # Extract card text/effect
        card_text_sections = soup.find_all('div', class_='card-text-section')
        for section in card_text_sections:
            # Skip sections with title, type info, or artist info
            if (section.find('p', class_='card-text-title') or 
                section.find('p', class_='card-text-type') or 
                'card-text-artist' in section.get('class', [])):
                continue
            
            # Look for direct text content in the section
            section_text = section.get_text().strip()
            if section_text and len(section_text) > 10 and not section_text.startswith('Illustrated by'):
                card_data["text"] = section_text
                break
    
    def _extract_energy_data(self, soup: BeautifulSoup, card_data: Dict) -> None:
        """Extract Energy card data."""
        name = card_data.get("name", "").lower()
        card_text_type = soup.find('p', class_='card-text-type')
        
        if "energy" in name:
            card_data["category"] = "energy"
            
            # Determine energy type
            basic_types = ["fire", "water", "grass", "electric", "psychic", "fighting", "dark", "metal", "fairy", "dragon"]
            if any(t in name for t in basic_types):
                card_data["energyType"] = "basic"
            else:
                card_data["energyType"] = "special"
            
            # Extract effect text for special energy
            if card_data.get("energyType") == "special":
                card_text_sections = soup.find_all('div', class_='card-text-section')
                for section in card_text_sections:
                    # Skip sections with title, type info, or artist info
                    if (section.find('p', class_='card-text-title') or 
                        section.find('p', class_='card-text-type') or 
                        'card-text-artist' in section.get('class', [])):
                        continue
                    
                    # Look for direct text content in the section
                    section_text = section.get_text().strip()
                    if section_text and len(section_text) > 10 and not section_text.startswith('Illustrated by'):
                        card_data["text"] = section_text
                        break
    
    def fetch_card_data(self, set_code: str, number: str) -> Dict:
        """Fetch single card data from Limitless TCG."""
        url = f"https://limitlesstcg.com/cards/{set_code}/{number}"
        
        try:
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            return self.parse_card_data(soup, set_code, number)
            
        except Exception as e:
            if self.verbose:
                print(f"  ✗ Failed to fetch {set_code}-{number}: {e}")
            return None
    
    def load_existing_cards(self, file_path: Path) -> Dict[str, Dict]:
        """Load existing card data from JSON file."""
        if not file_path.exists():
            return {}
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, list):
                    # Convert list to dict keyed by id
                    return {card["id"]: card for card in data if "id" in card}
                return data
        except Exception as e:
            self.log(f"Failed to load existing cards: {e}")
            return {}
    
    def save_cards(self, cards: Dict[str, Dict], file_path: Path) -> None:
        """Save card data to JSON file."""
        # Convert back to list format for consistency
        cards_list = list(cards.values())
        
        # Sort by set then number for cleaner output
        def sort_key(card):
            set_code = card.get("set", "")
            number_str = card.get("number", "0")
            # Extract numeric part for proper sorting
            number_match = re.search(r'(\d+)', number_str)
            number = int(number_match.group(1)) if number_match else 0
            return (set_code, number, number_str)
        
        cards_list.sort(key=sort_key)
        
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(cards_list, f, indent=2, ensure_ascii=False)
        
        self.log(f"Saved {len(cards_list)} cards to {file_path}")
    
    def scrape_sets(self, set_codes: List[str], output_path: Path) -> Dict[str, int]:
        """Main scraping function for multiple sets."""
        # Load existing cards
        existing_cards = self.load_existing_cards(output_path)
        self.log(f"Loaded {len(existing_cards)} existing cards")
        
        set_stats = {}
        total_new = 0
        total_skipped = 0
        
        for set_code in set_codes:
            self.log(f"\n=== Processing set: {set_code} ({self.GHI_SETS.get(set_code, 'Unknown')}) ===")
            
            # Get card list for this set
            card_numbers = self.fetch_set_cards(set_code)
            if not card_numbers:
                self.log(f"No cards found for {set_code}, skipping...")
                set_stats[set_code] = 0
                continue
            
            # Filter out existing cards
            cards_to_scrape = []
            for number in card_numbers:
                card_id = f"{set_code}-{number}"
                if card_id in existing_cards:
                    if self.verbose:
                        print(f"  Skipping {card_id} (already exists)")
                    total_skipped += 1
                else:
                    cards_to_scrape.append(number)
            
            self.log(f"Found {len(card_numbers)} cards, {len(cards_to_scrape)} new cards to scrape")
            
            # Scrape new cards
            set_new = 0
            for i, number in enumerate(cards_to_scrape):
                card_id = f"{set_code}-{number}"
                print(f"  [{i+1}/{len(cards_to_scrape)}] {card_id}...", end=" ")
                
                card_data = self.fetch_card_data(set_code, number)
                if card_data:
                    existing_cards[card_id] = card_data
                    print(f"✓ {card_data.get('name', 'Unknown')}")
                    set_new += 1
                else:
                    print("✗ Failed")
                
                # Rate limiting
                if i < len(cards_to_scrape) - 1:
                    time.sleep(self.rate_limit)
            
            total_new += set_new
            set_stats[set_code] = set_new
            self.log(f"Set {set_code} completed: {set_new} new cards")
        
        # Save all cards
        self.save_cards(existing_cards, output_path)
        
        # Print final summary
        print(f"\n=== SCRAPING COMPLETED ===")
        print(f"Total new cards scraped: {total_new}")
        print(f"Total existing cards skipped: {total_skipped}")
        print(f"Total cards in database: {len(existing_cards)}")
        print(f"\nBreakdown by set:")
        for set_code, count in set_stats.items():
            set_name = self.GHI_SETS.get(set_code, 'Unknown')
            print(f"  {set_code} ({set_name}): {count} new cards")
        
        return set_stats


def main():
    parser = argparse.ArgumentParser(description='Scrape all cards from Pokémon TCG sets')
    
    # Set selection
    parser.add_argument('--sets', nargs='*', 
                       help='Specific set codes to scrape (e.g., SVI PAL OBF)')
    parser.add_argument('--ghi-all', action='store_true',
                       help='Scrape all GHI regulation sets (SVI and later)')
    
    # Output options
    parser.add_argument('-o', '--output', 
                       default='/Users/molt/.openclaw/workspace/pokemon-tcg-ai/data/cards_detailed.json',
                       help='Output JSON file path')
    
    # Behavior options
    parser.add_argument('--rate-limit', type=float, default=0.5,
                       help='Seconds between requests (default: 0.5)')
    parser.add_argument('-v', '--verbose', action='store_true',
                       help='Verbose logging')
    
    args = parser.parse_args()
    
    scraper = SetScraper(rate_limit=args.rate_limit, verbose=args.verbose)
    
    # Determine which sets to scrape
    if args.ghi_all:
        set_codes = list(scraper.GHI_SETS.keys())
    elif args.sets:
        set_codes = args.sets
    else:
        print("ERROR: Specify --sets or --ghi-all")
        sys.exit(1)
    
    # Validate set codes
    invalid_sets = [s for s in set_codes if s not in scraper.GHI_SETS]
    if invalid_sets:
        print(f"ERROR: Invalid set codes: {invalid_sets}")
        print(f"Valid sets: {list(scraper.GHI_SETS.keys())}")
        sys.exit(1)
    
    # Create output directory
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Run scraper
    try:
        scraper.scrape_sets(set_codes, output_path)
    except KeyboardInterrupt:
        print("\nInterrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()