#!/Users/molt/.openclaw/workspace/pokemon-tcg-ai/venv/bin/python
"""
Japanese Pokémon TCG Card Scraper

Scrapes card data from pokemon-card.com (official Japanese site).
Supports regulation filtering (H/I/J) and rate limiting for respectful scraping.
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
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class JapaneseCardScraper:
    def __init__(self, rate_limit: float = 1.0, verbose: bool = False):
        self.rate_limit = rate_limit  # Seconds between requests
        self.verbose = verbose
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'ja,en-US;q=0.7,en;q=0.3',
            'Accept-Encoding': 'gzip, deflate',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1'
        })
        
        # Set mapping for regulations
        self.regulation_map = {
            'H': 'H',
            'I': 'I', 
            'J': 'J',
            'XY': 'XY',  # Legacy regulation
        }
        
        # Japanese type mapping
        self.type_ja_to_en = {
            '炎': 'Fire',
            '水': 'Water', 
            '草': 'Grass',
            '雷': 'Electric',
            '超': 'Psychic',
            '闘': 'Fighting',
            '悪': 'Dark',
            '鋼': 'Metal',
            'フェアリー': 'Fairy',
            'ドラゴン': 'Dragon',
            '無色': 'Colorless'
        }
        
        # Keep track of failed requests for reporting
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
    
    def search_cards(self, keyword: str = "", regulation: str = None, limit: int = 100) -> List[Dict]:
        """
        Search for cards using the official search API/interface.
        
        Args:
            keyword: Search keyword (card name, type, etc.)
            regulation: Regulation filter (H, I, J, XY)
            limit: Maximum number of cards to return
        
        Returns:
            List of card dictionaries with basic info and URLs
        """
        search_url = "https://www.pokemon-card.com/card-search/index.php"
        
        params = {}
        if keyword:
            params['keyword'] = keyword
            params['se_ta'] = 'keyword'
        if regulation:
            params['regu'] = regulation
        
        self.log(f"Searching cards with params: {params}")
        
        try:
            # First, get the search page
            response = self.session.get(search_url, params=params, timeout=30)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Parse search results
            cards = self._parse_search_results(soup, limit)
            
            self.log(f"Found {len(cards)} cards in search results")
            return cards
            
        except Exception as e:
            self.log(f"Failed to search cards: {e}", 'ERROR')
            return []
    
    def _parse_search_results(self, soup: BeautifulSoup, limit: int) -> List[Dict]:
        """Parse search results page to extract card links and basic info."""
        cards = []
        
        # Look for card result elements
        # Note: This is a placeholder - actual parsing will depend on the site structure
        card_elements = soup.find_all('div', class_='card-result') or soup.find_all('a', href=re.compile(r'details\.php'))
        
        for i, element in enumerate(card_elements):
            if i >= limit:
                break
                
            try:
                card_info = self._extract_basic_card_info(element)
                if card_info:
                    cards.append(card_info)
            except Exception as e:
                self.log(f"Failed to parse card element: {e}", 'WARNING')
                continue
        
        return cards
    
    def _extract_basic_card_info(self, element) -> Optional[Dict]:
        """Extract basic card information from search result element."""
        card_info = {}
        
        # Extract card detail URL
        link = element.find('a') if element.name != 'a' else element
        if link and link.get('href'):
            href = link.get('href')
            if 'details.php' in href:
                card_info['detail_url'] = href
                
                # Extract card ID from URL
                id_match = re.search(r'card/(\d+)', href)
                if id_match:
                    card_info['japanese_id'] = id_match.group(1)
                
                # Extract regulation from URL
                regu_match = re.search(r'regu/(\w+)', href)
                if regu_match:
                    card_info['regulation'] = regu_match.group(1)
        
        # Extract card name from element text
        name_text = element.get_text(strip=True)
        if name_text:
            card_info['name_ja'] = name_text
        
        return card_info if card_info else None
    
    def fetch_card_details(self, card_id: str, regulation: str = 'XY') -> Optional[Dict]:
        """
        Fetch detailed card information from individual card page.
        
        Args:
            card_id: Japanese card ID
            regulation: Regulation (H, I, J, XY)
            
        Returns:
            Dictionary with detailed card information
        """
        url = f"https://www.pokemon-card.com/card-search/details.php/card/{card_id}/regu/{regulation}"
        
        self.log(f"Fetching card details: {url}")
        
        try:
            # Rate limiting
            time.sleep(self.rate_limit)
            
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Check if we got a valid card page (not redirected to search)
            if 'card-search/index.php' in response.url or 'カード検索' in soup.title.string:
                self.log(f"Card {card_id} not found or redirected", 'WARNING')
                self.failed_requests.append({
                    'card_id': card_id, 
                    'regulation': regulation,
                    'reason': 'Card not found or redirected'
                })
                return None
            
            card_data = self._parse_card_details(soup, card_id, regulation)
            
            if card_data:
                self.successful_requests += 1
                self.log(f"Successfully scraped: {card_data.get('name_ja', card_id)}")
            
            return card_data
            
        except Exception as e:
            self.log(f"Failed to fetch card {card_id}: {e}", 'ERROR')
            self.failed_requests.append({
                'card_id': card_id,
                'regulation': regulation, 
                'reason': str(e)
            })
            return None
    
    def _parse_card_details(self, soup: BeautifulSoup, card_id: str, regulation: str) -> Dict:
        """Parse detailed card information from card details page."""
        card_data = {
            'japanese_id': card_id,
            'regulation': regulation,
            'source_url': f"https://www.pokemon-card.com/card-search/details.php/card/{card_id}/regu/{regulation}"
        }
        
        # Extract card name from h1 tag
        h1_element = soup.find('h1')
        if h1_element:
            card_data['name_ja'] = h1_element.get_text(strip=True)
        
        # Extract card image URL
        img_element = soup.find('img', class_='card-image') or soup.find('img', src=re.compile(r'card.*\.jpg'))
        if img_element:
            card_data['image_url_ja'] = img_element.get('src')
        
        # Extract card type (look for type indicators)
        type_elements = soup.find_all('span', class_='type') or soup.find_all('div', class_='card-type')
        for type_elem in type_elements:
            type_text = type_elem.get_text(strip=True)
            if type_text in self.type_ja_to_en:
                card_data['type_ja'] = type_text
                card_data['type'] = self.type_ja_to_en[type_text]
                break
        
        # Extract HP for Pokemon cards
        hp_match = re.search(r'HP(\d+)', soup.get_text())
        if hp_match:
            card_data['hp'] = int(hp_match.group(1))
            card_data['category'] = 'pokemon'
        
        # Extract evolution info
        evolves_text = soup.get_text()
        if 'から進化' in evolves_text:
            evolves_match = re.search(r'(\w+)から進化', evolves_text)
            if evolves_match:
                card_data['evolvesFrom_ja'] = evolves_match.group(1)
        
        # Extract attacks (ワザ)
        attacks = []
        attack_sections = soup.find_all('div', class_='attack') or soup.find_all('section', class_='waza')
        
        for attack_section in attack_sections:
            attack_info = self._parse_attack_info(attack_section)
            if attack_info:
                attacks.append(attack_info)
        
        if attacks:
            card_data['attacks_ja'] = attacks
        
        # Extract abilities (特性)
        abilities = []
        ability_sections = soup.find_all('div', class_='ability') or soup.find_all('section', class_='tokusei')
        
        for ability_section in ability_sections:
            ability_info = self._parse_ability_info(ability_section)
            if ability_info:
                abilities.append(ability_info)
        
        if abilities:
            card_data['abilities_ja'] = abilities
        
        # Extract weakness (弱点)
        weakness_match = re.search(r'弱点[：:]\s*([炎水草雷超闘悪鋼フェアリードラゴン無色]+)', soup.get_text())
        if weakness_match:
            weakness_ja = weakness_match.group(1)
            card_data['weakness_ja'] = weakness_ja
            if weakness_ja in self.type_ja_to_en:
                card_data['weakness'] = self.type_ja_to_en[weakness_ja]
        
        # Extract retreat cost (にげる)
        retreat_match = re.search(r'にげる[：:]\s*無色?(\d+)', soup.get_text())
        if retreat_match:
            card_data['retreatCost'] = int(retreat_match.group(1))
        
        # Determine if card is ex/EX/GX/V etc.
        name_ja = card_data.get('name_ja', '')
        if 'ex' in name_ja or 'EX' in name_ja:
            card_data['isEx'] = True
        elif 'GX' in name_ja:
            card_data['isGx'] = True
        elif 'V' in name_ja and not 'VMAX' in name_ja:
            card_data['isV'] = True
        elif 'VMAX' in name_ja:
            card_data['isVmax'] = True
        
        # Trainer cards
        if '特性' not in soup.get_text() and 'ワザ' not in soup.get_text() and 'HP' not in soup.get_text():
            card_data['category'] = 'trainer'
            
            # Determine trainer type
            trainer_text = soup.get_text()
            if 'サポート' in trainer_text:
                card_data['trainerType'] = 'Supporter'
            elif 'グッズ' in trainer_text:
                card_data['trainerType'] = 'Item'
            elif 'スタジアム' in trainer_text:
                card_data['trainerType'] = 'Stadium'
        
        # Extract card text/effect
        text_sections = soup.find_all('div', class_='card-text') or soup.find_all('p', class_='effect')
        card_text = []
        for text_section in text_sections:
            text = text_section.get_text(strip=True)
            if text and len(text) > 10:  # Filter out short/empty texts
                card_text.append(text)
        
        if card_text:
            card_data['text_ja'] = '\n\n'.join(card_text)
        
        return card_data
    
    def _parse_attack_info(self, attack_section) -> Optional[Dict]:
        """Parse attack information from attack section."""
        attack_info = {}
        
        # Extract attack name
        name_element = attack_section.find('h3') or attack_section.find('strong') or attack_section.find('span', class_='name')
        if name_element:
            attack_info['name_ja'] = name_element.get_text(strip=True)
        
        # Extract damage
        damage_match = re.search(r'(\d+[+]?)\s*ダメージ', attack_section.get_text())
        if damage_match:
            attack_info['damage'] = damage_match.group(1)
        
        # Extract attack text/effect
        text_element = attack_section.find('p', class_='effect') or attack_section.find('div', class_='description')
        if text_element:
            attack_info['text_ja'] = text_element.get_text(strip=True)
        
        # Extract energy cost (エネルギー)
        cost_elements = attack_section.find_all('span', class_='energy') or attack_section.find_all('img', src=re.compile(r'energy'))
        cost = []
        for cost_element in cost_elements:
            if cost_element.name == 'img':
                src = cost_element.get('src', '')
                # Parse energy type from image filename
                for ja_type, en_type in self.type_ja_to_en.items():
                    if ja_type in src or en_type.lower() in src:
                        cost.append(en_type)
                        break
            else:
                cost_text = cost_element.get_text(strip=True)
                if cost_text in self.type_ja_to_en:
                    cost.append(self.type_ja_to_en[cost_text])
        
        if cost:
            attack_info['cost'] = cost
        
        return attack_info if attack_info else None
    
    def _parse_ability_info(self, ability_section) -> Optional[Dict]:
        """Parse ability information from ability section."""
        ability_info = {}
        
        # Extract ability name
        name_element = ability_section.find('h3') or ability_section.find('strong') or ability_section.find('span', class_='name')
        if name_element:
            ability_info['name_ja'] = name_element.get_text(strip=True)
        
        # Extract ability text/effect
        text_element = ability_section.find('p', class_='effect') or ability_section.find('div', class_='description')
        if text_element:
            ability_info['text_ja'] = text_element.get_text(strip=True)
        
        return ability_info if ability_info else None
    
    def scrape_regulation_cards(self, regulation: str, output_file: str = None, limit: int = None) -> Dict:
        """
        Scrape all cards for a specific regulation.
        
        Args:
            regulation: Regulation code (H, I, J, XY)
            output_file: Output JSON file path
            limit: Maximum number of cards to scrape
        
        Returns:
            Dictionary with scraped cards and statistics
        """
        self.log(f"Starting scrape for regulation: {regulation}")
        
        # Search for all cards in this regulation
        search_results = self.search_cards(regulation=regulation, limit=limit or 10000)
        
        scraped_cards = []
        total_cards = len(search_results)
        
        self.log(f"Found {total_cards} cards to scrape")
        
        for i, card_info in enumerate(search_results):
            if limit and i >= limit:
                break
                
            self.log(f"Progress: {i+1}/{total_cards} - {card_info.get('name_ja', 'Unknown')}")
            
            # Extract card ID and regulation from URL or use provided info
            card_id = card_info.get('japanese_id')
            if card_id:
                detailed_card = self.fetch_card_details(card_id, regulation)
                if detailed_card:
                    # Merge search info with detailed info
                    detailed_card.update(card_info)
                    scraped_cards.append(detailed_card)
        
        # Prepare results
        results = {
            'regulation': regulation,
            'total_found': total_cards,
            'scraped_count': len(scraped_cards),
            'success_rate': len(scraped_cards) / max(total_cards, 1) * 100,
            'failed_count': len(self.failed_requests),
            'cards': scraped_cards,
            'failed_requests': self.failed_requests
        }
        
        # Save to file if specified
        if output_file:
            output_path = Path(output_file)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(results, f, ensure_ascii=False, indent=2)
            
            self.log(f"Results saved to {output_file}")
        
        return results


def main():
    """Main CLI interface."""
    parser = argparse.ArgumentParser(description='Japanese Pokémon TCG Card Scraper')
    parser.add_argument('--regulation', '-r', choices=['H', 'I', 'J', 'XY'], 
                        help='Regulation to scrape (H, I, J, XY)')
    parser.add_argument('--card-id', '-c', help='Specific card ID to scrape')
    parser.add_argument('--keyword', '-k', help='Search keyword')
    parser.add_argument('--output', '-o', help='Output JSON file')
    parser.add_argument('--limit', '-l', type=int, help='Maximum number of cards to scrape')
    parser.add_argument('--rate-limit', type=float, default=1.0, 
                        help='Rate limit in seconds between requests (default: 1.0)')
    parser.add_argument('--verbose', '-v', action='store_true', help='Enable verbose logging')
    
    args = parser.parse_args()
    
    if not any([args.regulation, args.card_id, args.keyword]):
        parser.error("Must specify either --regulation, --card-id, or --keyword")
    
    # Initialize scraper
    scraper = JapaneseCardScraper(rate_limit=args.rate_limit, verbose=args.verbose)
    
    try:
        if args.card_id:
            # Scrape specific card
            regulation = args.regulation or 'XY'
            card_data = scraper.fetch_card_details(args.card_id, regulation)
            
            if card_data:
                print(json.dumps(card_data, ensure_ascii=False, indent=2))
            else:
                print(f"Failed to scrape card {args.card_id}")
                sys.exit(1)
        
        elif args.regulation:
            # Scrape all cards for regulation
            output_file = args.output or f'data/cards_ja_{args.regulation.lower()}.json'
            results = scraper.scrape_regulation_cards(args.regulation, output_file, args.limit)
            
            # Print summary
            print(f"\nScraping Summary:")
            print(f"Regulation: {results['regulation']}")
            print(f"Total found: {results['total_found']}")
            print(f"Successfully scraped: {results['scraped_count']}")
            print(f"Failed: {results['failed_count']}")
            print(f"Success rate: {results['success_rate']:.1f}%")
            
            if results['failed_count'] > 0:
                print(f"\nFirst few failures:")
                for failure in results['failed_requests'][:5]:
                    print(f"  - Card {failure['card_id']}: {failure['reason']}")
        
        elif args.keyword:
            # Search for cards by keyword
            cards = scraper.search_cards(args.keyword, args.regulation, args.limit or 50)
            print(json.dumps(cards, ensure_ascii=False, indent=2))
    
    except KeyboardInterrupt:
        print("\nScraping interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"Scraping failed: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()