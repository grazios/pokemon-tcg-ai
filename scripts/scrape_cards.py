#!/Users/molt/.openclaw/workspace/pokemon-tcg-ai/venv/bin/python
"""
Pokémon TCG Card Scraper

Scrapes card data from Limitless TCG and other sources.
Supports incremental updates and various input formats.
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Union
import requests
from bs4 import BeautifulSoup


class CardScraper:
    def __init__(self, rate_limit: float = 1.0, verbose: bool = False):
        self.rate_limit = rate_limit
        self.verbose = verbose
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        })
    
    def log(self, message: str) -> None:
        """Log message if verbose mode is enabled."""
        if self.verbose:
            print(f"[INFO] {message}")
    
    def parse_card_id(self, card_input: str) -> Optional[tuple]:
        """Parse card input into (set, number) tuple."""
        # Handle formats like "OBF-125", "OBF 125", "Charizard ex (OBF 125)"
        patterns = [
            r'([A-Z]{2,4})[-\s](\d+[a-z]?)',  # Direct format: OBF-125, OBF 125
            r'\(([A-Z]{2,4})\s+(\d+[a-z]?)\)',  # Parentheses format: (OBF 125)
        ]
        
        for pattern in patterns:
            match = re.search(pattern, card_input)
            if match:
                return (match.group(1), match.group(2))
        
        return None
    
    def fetch_limitless_card(self, set_code: str, number: str) -> Optional[Dict]:
        """Fetch card data from Limitless TCG."""
        url = f"https://limitlesstcg.com/cards/{set_code}/{number}"
        self.log(f"Fetching {url}")
        
        try:
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            return self.parse_limitless_html(soup, set_code, number)
            
        except Exception as e:
            self.log(f"Failed to fetch {set_code}-{number}: {e}")
            return None
    
    def parse_limitless_html(self, soup: BeautifulSoup, set_code: str, number: str) -> Dict:
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
        
        # Check for ex rule
        if re.search(r'\bex\b', card_data.get("name", ""), re.IGNORECASE):
            card_data["isEx"] = True
    
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
        
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(cards_list, f, indent=2, ensure_ascii=False)
        
        self.log(f"Saved {len(cards_list)} cards to {file_path}")
    
    def scrape_cards(self, card_inputs: List[str], output_path: Path) -> Dict[str, Dict]:
        """Main scraping function."""
        # Load existing cards
        existing_cards = self.load_existing_cards(output_path)
        self.log(f"Loaded {len(existing_cards)} existing cards")
        
        # Parse card inputs
        cards_to_scrape = []
        for card_input in card_inputs:
            parsed = self.parse_card_id(card_input)
            if parsed:
                set_code, number = parsed
                card_id = f"{set_code}-{number}"
                
                if card_id in existing_cards:
                    self.log(f"Skipping {card_id} (already exists)")
                    continue
                
                cards_to_scrape.append((set_code, number, card_id))
            else:
                print(f"WARNING: Could not parse card input: {card_input}")
        
        self.log(f"Will scrape {len(cards_to_scrape)} new cards")
        
        # Scrape new cards
        new_cards = {}
        for i, (set_code, number, card_id) in enumerate(cards_to_scrape):
            print(f"[{i+1}/{len(cards_to_scrape)}] Scraping {card_id}...")
            
            card_data = self.fetch_limitless_card(set_code, number)
            if card_data:
                new_cards[card_id] = card_data
                print(f"  ✓ Success: {card_data.get('name', 'Unknown')}")
            else:
                print(f"  ✗ Failed to scrape {card_id}")
            
            # Rate limiting
            if i < len(cards_to_scrape) - 1:
                time.sleep(self.rate_limit)
        
        # Merge with existing cards
        all_cards = {**existing_cards, **new_cards}
        
        # Save updated data
        self.save_cards(all_cards, output_path)
        
        print(f"\nCompleted: {len(new_cards)} new cards scraped, {len(all_cards)} total cards")
        return all_cards


def parse_deck_list_url(url: str) -> List[str]:
    """Parse deck list URL and extract card identifiers."""
    # This would be implemented to parse deck lists from various sites
    # For now, return empty list
    return []


def main():
    parser = argparse.ArgumentParser(description='Scrape Pokémon TCG card data')
    
    # Input options
    parser.add_argument('--cards', nargs='*', help='Card IDs in "SET NUMBER" format')
    parser.add_argument('--deck-url', help='URL to deck list to scrape cards from')
    parser.add_argument('--file', help='File containing card IDs (one per line)')
    
    # Output options
    parser.add_argument('-o', '--output', 
                       default='/Users/molt/.openclaw/workspace/pokemon-tcg-ai/data/cards_detailed.json',
                       help='Output JSON file path')
    
    # Behavior options
    parser.add_argument('--rate-limit', type=float, default=1.0,
                       help='Seconds between requests (default: 1.0)')
    parser.add_argument('-v', '--verbose', action='store_true',
                       help='Verbose logging')
    parser.add_argument('--force', action='store_true',
                       help='Re-scrape existing cards')
    
    args = parser.parse_args()
    
    # Collect card inputs
    card_inputs = []
    
    if args.cards:
        card_inputs.extend(args.cards)
    
    if args.deck_url:
        deck_cards = parse_deck_list_url(args.deck_url)
        card_inputs.extend(deck_cards)
    
    if args.file:
        try:
            with open(args.file, 'r') as f:
                file_cards = [line.strip() for line in f if line.strip()]
                card_inputs.extend(file_cards)
        except FileNotFoundError:
            print(f"ERROR: File not found: {args.file}")
            sys.exit(1)
    
    if not card_inputs:
        print("ERROR: No cards specified. Use --cards, --deck-url, or --file")
        sys.exit(1)
    
    # Create output directory
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Initialize scraper
    scraper = CardScraper(rate_limit=args.rate_limit, verbose=args.verbose)
    
    # If force mode, clear existing cards for the ones we're scraping
    if args.force:
        existing_cards = scraper.load_existing_cards(output_path)
        cards_to_remove = []
        for card_input in card_inputs:
            parsed = scraper.parse_card_id(card_input)
            if parsed:
                set_code, number = parsed
                card_id = f"{set_code}-{number}"
                if card_id in existing_cards:
                    cards_to_remove.append(card_id)
        
        for card_id in cards_to_remove:
            del existing_cards[card_id]
        
        scraper.save_cards(existing_cards, output_path)
        scraper.log(f"Removed {len(cards_to_remove)} existing cards for re-scraping")
    
    # Run scraper
    try:
        scraper.scrape_cards(card_inputs, output_path)
    except KeyboardInterrupt:
        print("\nInterrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()