#!/opt/homebrew/bin/python3.12
"""
Japanese Pokémon TCG Card Scraper

Scrapes card data from pokemon-card.com (official Japanese site).
Supports multiple card types with HTML caching for efficient development.
"""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Union
import subprocess
from bs4 import BeautifulSoup
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class JapaneseCardScraper:
    def __init__(self, rate_limit: float = 1.0, verbose: bool = False, cache_dir: str = "data/html_cache"):
        self.rate_limit = rate_limit
        self.verbose = verbose
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        # Japanese type mapping based on icon classes
        self.type_icon_map = {
            'icon-electric': '雷',
            'icon-fire': '炎', 
            'icon-water': '水',
            'icon-grass': '草',
            'icon-psychic': '超',
            'icon-fighting': '闘',
            'icon-dark': '悪',
            'icon-steel': '鋼',
            'icon-dragon': '竜',
            'icon-none': '無色',
            'icon-fairy': 'フェアリー'
        }
        
        # Reverse mapping for energy cost parsing
        self.icon_to_type = {}
        for icon, type_ja in self.type_icon_map.items():
            self.icon_to_type[icon] = type_ja
        
        # Keep track of stats
        self.failed_requests = []
        self.successful_requests = 0
    
    def log(self, message: str, level: str = 'INFO') -> None:
        """Log message if verbose mode is enabled."""
        if self.verbose:
            if level == 'ERROR':
                logger.error(message)
            elif level == 'WARNING':
                logger.warning(message)
            else:
                logger.info(message)
    
    def get_cached_html(self, card_id: str, regulation: str, use_cache: bool = True) -> Optional[str]:
        """Get HTML from cache or fetch from web."""
        cache_file = self.cache_dir / f"{card_id}_{regulation}.html"
        
        # Try cache first
        if use_cache and cache_file.exists():
            self.log(f"Using cached HTML for {card_id}_{regulation}")
            return cache_file.read_text(encoding='utf-8')
        
        # Fetch from web
        url = f"https://www.pokemon-card.com/card-search/details.php/card/{card_id}/regu/{regulation}"
        self.log(f"Fetching: {url}")
        
        try:
            # Rate limiting
            time.sleep(self.rate_limit)
            
            # Use curl to fetch HTML
            result = subprocess.run([
                'curl', '-s', url,
                '-H', 'User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
            ], capture_output=True, text=True, timeout=30)
            
            if result.returncode != 0:
                raise Exception(f"curl failed with code {result.returncode}")
            
            html = result.stdout
            
            # Check if we got a valid card page
            if 'card-search/index.php' in html or 'カード検索' in html:
                self.log(f"Card {card_id} not found or redirected", 'WARNING')
                return None
            
            # Cache the HTML
            cache_file.write_text(html, encoding='utf-8')
            self.log(f"Cached HTML for {card_id}_{regulation}")
            
            return html
            
        except Exception as e:
            self.log(f"Failed to fetch card {card_id}: {e}", 'ERROR')
            self.failed_requests.append({
                'card_id': card_id,
                'regulation': regulation,
                'reason': str(e)
            })
            return None
    
    def parse_energy_cost(self, element) -> List[str]:
        """Parse energy cost from icon elements."""
        cost = []
        icon_elements = element.find_all('span', class_=['icon'])
        
        for icon_elem in icon_elements:
            classes = icon_elem.get('class', [])
            for class_name in classes:
                if class_name in self.icon_to_type:
                    cost.append(self.icon_to_type[class_name])
                    break
        
        return cost
    
    def parse_pokemon_card(self, soup: BeautifulSoup, card_id: str, regulation: str) -> Dict:
        """Parse Pokemon card details."""
        card_data = {
            'japanese_id': card_id,
            'regulation': regulation,
            'category': 'pokemon'
        }
        
        # Card name
        h1_element = soup.find('h1', class_='Heading1')
        if h1_element:
            card_data['name_ja'] = h1_element.get_text(strip=True)
        
        # HP
        hp_element = soup.find('span', class_='hp-num')
        if hp_element:
            card_data['hp'] = int(hp_element.get_text(strip=True))
        
        # Type
        type_icon = soup.find('span', class_='hp-type') 
        if type_icon:
            next_span = type_icon.find_next_sibling('span')
            if next_span:
                classes = next_span.get('class', [])
                for class_name in classes:
                    if class_name in self.icon_to_type:
                        card_data['type'] = self.icon_to_type[class_name]
                        break
        
        # Stage (たね, 1進化, 2進化)
        type_span = soup.find('span', class_='type')
        if type_span:
            stage = type_span.get_text(strip=True)
            if stage == 'たね':
                card_data['stage'] = 'basic'
            elif '進化' in stage:
                card_data['stage'] = 'evolution'
            card_data['stage_ja'] = stage
        
        # Attacks (ワザ)
        attacks = []
        waza_section = soup.find('h2', string='ワザ')
        if waza_section:
            current = waza_section.find_next_sibling()
            while current and current.name != 'h2':
                if current.name == 'h4':
                    attack = self.parse_attack(current)
                    if attack:
                        attacks.append(attack)
                current = current.find_next_sibling()
        
        if attacks:
            card_data['attacks'] = attacks
        
        # Ability (特性)
        ability_section = soup.find('h2', string='特性')
        if ability_section:
            ability = self.parse_ability(ability_section)
            if ability:
                card_data['ability'] = ability
        
        # Weakness, Resistance, Retreat Cost
        table = soup.find('table')
        if table:
            self.parse_pokemon_stats(table, card_data)
        
        # Special rules (ex, GX, etc.)
        special_rules = soup.find('h2', string='特別なルール')
        if special_rules:
            rules_p = special_rules.find_next_sibling('p')
            if rules_p:
                rule_text = rules_p.get_text(strip=True)
                card_data['special_rule'] = rule_text
                
                # Determine Pokemon type
                name_ja = card_data.get('name_ja', '')
                if 'ex' in name_ja.lower():
                    card_data['pokemon_type'] = 'ex'
                elif 'vmax' in name_ja.upper():
                    card_data['pokemon_type'] = 'vmax'
                elif 'vstar' in name_ja.upper():
                    card_data['pokemon_type'] = 'vstar'
                elif 'v' in name_ja.upper():
                    card_data['pokemon_type'] = 'v'
                elif 'gx' in name_ja.upper():
                    card_data['pokemon_type'] = 'gx'
        
        # Get image URL
        img_element = soup.find('img', class_='fit')
        if img_element:
            card_data['image_url'] = img_element.get('src')
        
        return card_data
    
    def parse_attack(self, h4_element) -> Optional[Dict]:
        """Parse attack information from h4 element."""
        attack = {}
        
        # Energy cost (icon spans)
        cost = self.parse_energy_cost(h4_element)
        if cost:
            attack['cost'] = cost
        
        # Attack name and damage
        text = h4_element.get_text()
        damage_span = h4_element.find('span', class_='f_right')
        
        if damage_span:
            damage_text = damage_span.get_text(strip=True)
            attack['damage'] = damage_text
            # Remove damage from text to get attack name
            name_text = text.replace(damage_text, '').strip()
        else:
            name_text = text
        
        # Clean up attack name (remove icons)
        # Find spans with icon class and remove their text
        icon_spans = h4_element.find_all('span', class_=['icon'])
        for span in icon_spans:
            name_text = name_text.replace(span.get_text(), '').strip()
        
        attack['name_ja'] = name_text
        
        # Attack effect (next p element)
        effect_p = h4_element.find_next_sibling('p')
        if effect_p:
            attack['text_ja'] = effect_p.get_text(strip=True)
        
        return attack if attack.get('name_ja') else None
    
    def parse_ability(self, h2_element) -> Optional[Dict]:
        """Parse ability information."""
        ability = {}
        
        # Ability name (next h4)
        h4 = h2_element.find_next_sibling('h4')
        if h4:
            ability['name_ja'] = h4.get_text(strip=True)
            
            # Ability effect (next p)
            effect_p = h4.find_next_sibling('p')
            if effect_p:
                ability['text_ja'] = effect_p.get_text(strip=True)
        
        return ability if ability.get('name_ja') else None
    
    def parse_pokemon_stats(self, table, card_data: Dict) -> None:
        """Parse weakness, resistance, and retreat cost from table."""
        tds = table.find_all('td')
        if len(tds) >= 3:
            # Weakness
            weakness_td = tds[0]
            weakness_icon = weakness_td.find('span', class_=['icon'])
            if weakness_icon:
                classes = weakness_icon.get('class', [])
                for class_name in classes:
                    if class_name in self.icon_to_type:
                        card_data['weakness'] = self.icon_to_type[class_name]
                        break
            
            # Resistance
            resistance_td = tds[1]
            if resistance_td.get_text(strip=True) != '--':
                resistance_icon = resistance_td.find('span', class_=['icon'])
                if resistance_icon:
                    classes = resistance_icon.get('class', [])
                    for class_name in classes:
                        if class_name in self.icon_to_type:
                            card_data['resistance'] = self.icon_to_type[class_name]
                            break
            
            # Retreat cost
            retreat_td = tds[2]
            retreat_icons = retreat_td.find_all('span', class_=['icon'])
            card_data['retreatCost'] = len(retreat_icons)
    
    def parse_trainer_card(self, soup: BeautifulSoup, card_id: str, regulation: str) -> Dict:
        """Parse Trainer card details."""
        card_data = {
            'japanese_id': card_id,
            'regulation': regulation,
            'category': 'trainer'
        }
        
        # Card name
        h1_element = soup.find('h1', class_='Heading1')
        if h1_element:
            card_data['name_ja'] = h1_element.get_text(strip=True)
        
        # Determine trainer type
        trainer_types = ['サポート', 'グッズ', 'スタジアム', 'ポケモンのどうぐ']
        for trainer_type in trainer_types:
            h2 = soup.find('h2', string=trainer_type)
            if h2:
                card_data['trainer_type'] = trainer_type
                
                # Get effect text (following p elements)
                effects = []
                current = h2.find_next_sibling()
                while current and current.name != 'h2':
                    if current.name == 'p':
                        effect_text = current.get_text(strip=True)
                        if effect_text and len(effect_text) > 5:  # Filter short texts
                            effects.append(effect_text)
                    current = current.find_next_sibling()
                
                if effects:
                    card_data['text_ja'] = '\\n\\n'.join(effects)
                break
        
        # Get image URL
        img_element = soup.find('img', class_='fit')
        if img_element:
            card_data['image_url'] = img_element.get('src')
        
        return card_data
    
    def parse_energy_card(self, soup: BeautifulSoup, card_id: str, regulation: str) -> Dict:
        """Parse Energy card details."""
        card_data = {
            'japanese_id': card_id,
            'regulation': regulation,
            'category': 'energy'
        }
        
        # Card name
        h1_element = soup.find('h1', class_='Heading1')
        if h1_element:
            card_data['name_ja'] = h1_element.get_text(strip=True)
        
        # Determine if basic or special energy
        name_ja = card_data.get('name_ja', '')
        if 'エネルギー' in name_ja:
            if any(basic in name_ja for basic in ['炎', '水', '草', '雷', '超', '闘', '悪', '鋼']):
                card_data['energy_type'] = 'basic'
            else:
                card_data['energy_type'] = 'special'
                
                # Get effect text for special energy
                effects = []
                for p in soup.find_all('p'):
                    text = p.get_text(strip=True)
                    if len(text) > 10 and 'エネルギー' not in text:
                        effects.append(text)
                
                if effects:
                    card_data['text_ja'] = '\\n\\n'.join(effects[:3])  # Limit to first 3 effects
        
        # Get image URL
        img_element = soup.find('img', class_='fit')
        if img_element:
            card_data['image_url'] = img_element.get('src')
        
        return card_data
    
    def determine_card_type(self, soup: BeautifulSoup) -> str:
        """Determine card type based on HTML content."""
        text = soup.get_text()
        
        # Check for trainer types
        if soup.find('h2', string='サポート'):
            return 'trainer'
        if soup.find('h2', string='グッズ'):
            return 'trainer'
        if soup.find('h2', string='スタジアム'):
            return 'trainer'
        if soup.find('h2', string='ポケモンのどうぐ'):
            return 'trainer'
        
        # Check for energy
        h1_text = soup.find('h1', class_='Heading1')
        if h1_text and 'エネルギー' in h1_text.get_text():
            return 'energy'
        
        # Check for Pokemon (has HP)
        if soup.find('span', class_='hp-num'):
            return 'pokemon'
        
        # Default to pokemon if unclear
        return 'pokemon'
    
    def fetch_card_details(self, card_id: str, regulation: str = 'J', use_cache: bool = True) -> Optional[Dict]:
        """
        Fetch detailed card information from individual card page.
        
        Args:
            card_id: Japanese card ID
            regulation: Regulation (H, I, J)
            use_cache: Whether to use HTML cache
            
        Returns:
            Dictionary with detailed card information
        """
        html = self.get_cached_html(card_id, regulation, use_cache)
        if not html:
            return None
        
        try:
            soup = BeautifulSoup(html, 'html.parser')
            
            # Determine card type
            card_type = self.determine_card_type(soup)
            
            # Parse based on card type
            if card_type == 'pokemon':
                card_data = self.parse_pokemon_card(soup, card_id, regulation)
            elif card_type == 'trainer':
                card_data = self.parse_trainer_card(soup, card_id, regulation)
            elif card_type == 'energy':
                card_data = self.parse_energy_card(soup, card_id, regulation)
            else:
                self.log(f"Unknown card type for {card_id}", 'WARNING')
                return None
            
            self.successful_requests += 1
            self.log(f"Successfully parsed: {card_data.get('name_ja', card_id)}")
            
            return card_data
            
        except Exception as e:
            self.log(f"Failed to parse card {card_id}: {e}", 'ERROR')
            self.failed_requests.append({
                'card_id': card_id,
                'regulation': regulation,
                'reason': f"Parse error: {e}"
            })
            return None


def main():
    """Main CLI interface."""
    parser = argparse.ArgumentParser(description='Japanese Pokémon TCG Card Scraper with HTML Cache')
    parser.add_argument('--card-id', '-c', help='Specific card ID to scrape')
    parser.add_argument('--regulation', '-r', choices=['H', 'I', 'J'], default='J',
                        help='Regulation to use (default: J)')
    parser.add_argument('--search', '-s', help='Search keyword (not implemented yet)')
    parser.add_argument('--output', '-o', help='Output JSON file')
    parser.add_argument('--no-cache', action='store_true', help='Force fresh fetch (ignore cache)')
    parser.add_argument('--rate-limit', type=float, default=1.0,
                        help='Rate limit in seconds between requests (default: 1.0)')
    parser.add_argument('--verbose', '-v', action='store_true', help='Enable verbose logging')
    
    args = parser.parse_args()
    
    if not args.card_id:
        parser.error("Must specify --card-id")
    
    # Initialize scraper
    scraper = JapaneseCardScraper(rate_limit=args.rate_limit, verbose=args.verbose)
    
    try:
        card_data = scraper.fetch_card_details(
            args.card_id, 
            args.regulation, 
            use_cache=not args.no_cache
        )
        
        if card_data:
            # Output result
            output_json = json.dumps(card_data, ensure_ascii=False, indent=2)
            
            if args.output:
                Path(args.output).parent.mkdir(parents=True, exist_ok=True)
                with open(args.output, 'w', encoding='utf-8') as f:
                    f.write(output_json)
                print(f"Card data saved to {args.output}")
            else:
                print(output_json)
        else:
            print(f"Failed to scrape card {args.card_id}")
            sys.exit(1)
    
    except KeyboardInterrupt:
        print("\\nScraping interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"Scraping failed: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()