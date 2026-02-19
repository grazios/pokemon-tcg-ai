#!/Users/molt/.openclaw/workspace/pokemon-tcg-ai/venv/bin/python
"""
Japanese Data Integration Script

Integrates Japanese card data with existing English cards_detailed.json.
Creates English-Japanese mappings and adds name_ja fields.
"""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import difflib
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class JapaneseDataIntegrator:
    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        
        # Common English-Japanese name patterns for better matching
        self.name_patterns = {
            # Pokemon name patterns
            'ex': ['ex', 'EX'],
            'GX': ['GX'],
            'V': ['V'],
            'VMAX': ['VMAX', 'Vmax'],
            'VSTAR': ['VSTAR', 'Vstar'],
            'Prime': ['プライム', 'Prime'],
            'BREAK': ['BREAK', 'ブレイク'],
            'TAG TEAM': ['TAG TEAM', 'タッグチーム'],
            
            # Trainer patterns
            "Professor's Research": ["博士の研究", "Professor's Research"],
            "Boss's Orders": ["ボスの指令", "Boss's Orders"],
            "Quick Ball": ["クイックボール", "Quick Ball"],
            "Ultra Ball": ["ハイパーボール", "Ultra Ball"],
            "Professor Oak": ["オーキド博士", "Professor Oak"],
            
            # Energy patterns
            "Basic Energy": ["基本エネルギー", "Basic Energy"],
            "Double Colorless Energy": ["ダブル無色エネルギー", "Double Colorless Energy"],
        }
        
        # Set code mappings between English and Japanese
        self.set_mappings = {
            # Recent sets
            'PAL': 'sv1S',  # Paldea Evolved → スカーレット
            'OBF': 'sv3',   # Obsidian Flames → 黒炎の支配者
            'MEW': 'sv2D',  # 151 → ポケモンカード151 
            'PAR': 'sv1V',  # Paradox Rift → バイオレット
            'TEF': 'sv2P',  # Temporal Forces → スノーハザード
            
            # Sword & Shield era
            'BST': 'S6',    # Battle Styles → 連撃マスター/一撃マスター
            'CRE': 'S7',    # Chilling Reign → 白銀のランス/漆黒のガイスト
            'EVS': 'S7',    # Evolving Skies → 摩天パーフェクト/蒼空ストリーム
            'CEL': 'S8',    # Celebrations → 25th ANNIVERSARY
            'BRS': 'S9',    # Brilliant Stars → スターバース
            'ASR': 'S10',   # Astral Radiance → ダークファンタズマ
            'PGO': 'S-P',   # Pokémon GO → Pokémon GO
            'LOR': 'S11',   # Lost Origin → ロストアビス
            'SIT': 'S12',   # Silver Tempest → パラダイムトリガー
            'CRZ': 'S12a',  # Crown Zenith → VSTARユニバース
            
            # Add more mappings as needed
        }
        
        self.japanese_cards = []
        self.english_cards = []
        self.mappings = []
        
    def log(self, message: str, level: str = 'INFO') -> None:
        """Log message if verbose mode is enabled."""
        if self.verbose:
            if level == 'ERROR':
                logger.error(message)
            elif level == 'WARNING':
                logger.warning(message)
            else:
                logger.info(message)
    
    def load_japanese_data(self, file_path: str) -> None:
        """Load Japanese card data from file."""
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        if isinstance(data, dict) and 'cards' in data:
            self.japanese_cards = data['cards']
        elif isinstance(data, list):
            self.japanese_cards = data
        else:
            raise ValueError("Invalid Japanese data format")
        
        self.log(f"Loaded {len(self.japanese_cards)} Japanese cards")
    
    def load_english_data(self, file_path: str) -> None:
        """Load English card data from cards_detailed.json."""
        with open(file_path, 'r', encoding='utf-8') as f:
            self.english_cards = json.load(f)
        
        self.log(f"Loaded {len(self.english_cards)} English cards")
    
    def create_name_similarity_mapping(self, similarity_threshold: float = 0.6) -> None:
        """Create mappings based on name similarity and set matching."""
        self.log("Creating name similarity mappings...")
        
        mapped_count = 0
        
        for ja_card in self.japanese_cards:
            name_ja = ja_card.get('name_ja', '')
            if not name_ja:
                continue
            
            best_match = None
            best_similarity = 0
            
            for en_card in self.english_cards:
                name_en = en_card.get('name', '')
                if not name_en:
                    continue
                
                # Calculate similarity
                similarity = self._calculate_similarity(name_en, name_ja, en_card, ja_card)
                
                if similarity > best_similarity and similarity >= similarity_threshold:
                    best_similarity = similarity
                    best_match = en_card
            
            if best_match:
                mapping = {
                    'english_card': best_match,
                    'japanese_card': ja_card,
                    'similarity_score': best_similarity,
                    'mapping_type': 'name_similarity'
                }
                self.mappings.append(mapping)
                mapped_count += 1
                
                self.log(f"Mapped: {best_match['name']} ↔ {name_ja} (score: {best_similarity:.3f})")
        
        self.log(f"Created {mapped_count} similarity-based mappings")
    
    def _calculate_similarity(self, name_en: str, name_ja: str, en_card: Dict, ja_card: Dict) -> float:
        """Calculate similarity score between English and Japanese cards."""
        # Base similarity using sequence matching
        base_score = difflib.SequenceMatcher(None, name_en.lower(), name_ja.lower()).ratio()
        
        # Boost score for exact pattern matches
        pattern_boost = 0
        for en_pattern, ja_patterns in self.name_patterns.items():
            if en_pattern.lower() in name_en.lower():
                for ja_pattern in ja_patterns:
                    if ja_pattern in name_ja:
                        pattern_boost += 0.3
                        break
        
        # Boost score for set matching
        set_boost = 0
        en_set = en_card.get('set', '')
        ja_regulation = ja_card.get('regulation', '')
        
        if en_set and ja_regulation:
            if en_set in self.set_mappings and self.set_mappings[en_set] == ja_regulation:
                set_boost = 0.2
        
        # Boost score for card number matching
        number_boost = 0
        en_number = en_card.get('number', '')
        ja_id = ja_card.get('japanese_id', '')
        
        if en_number and ja_id and en_number in ja_id:
            number_boost = 0.1
        
        # Boost for type matching
        type_boost = 0
        if en_card.get('type') == ja_card.get('type'):
            type_boost = 0.1
        
        # Boost for HP matching (Pokemon cards)
        hp_boost = 0
        if (en_card.get('hp') and ja_card.get('hp') and 
            en_card['hp'] == ja_card['hp']):
            hp_boost = 0.2
        
        total_score = base_score + pattern_boost + set_boost + number_boost + type_boost + hp_boost
        return min(total_score, 1.0)  # Cap at 1.0
    
    def create_exact_matching(self) -> None:
        """Create mappings for cards that can be matched exactly by number/set."""
        self.log("Creating exact number/set mappings...")
        
        mapped_count = 0
        
        for ja_card in self.japanese_cards:
            ja_regulation = ja_card.get('regulation', '')
            ja_id = ja_card.get('japanese_id', '')
            
            # Look for English set that matches this regulation
            target_en_set = None
            for en_set, ja_set in self.set_mappings.items():
                if ja_set == ja_regulation:
                    target_en_set = en_set
                    break
            
            if not target_en_set:
                continue
            
            # Find English card with matching set and similar number
            for en_card in self.english_cards:
                if (en_card.get('set') == target_en_set and 
                    self._numbers_match(en_card.get('number', ''), ja_id)):
                    
                    # Check if already mapped
                    if not self._is_already_mapped(en_card, ja_card):
                        mapping = {
                            'english_card': en_card,
                            'japanese_card': ja_card,
                            'similarity_score': 1.0,
                            'mapping_type': 'exact_match'
                        }
                        self.mappings.append(mapping)
                        mapped_count += 1
                        
                        self.log(f"Exact match: {en_card['name']} ↔ {ja_card.get('name_ja', 'Unknown')}")
                    break
        
        self.log(f"Created {mapped_count} exact mappings")
    
    def _numbers_match(self, en_number: str, ja_id: str) -> bool:
        """Check if card numbers match (allowing for format differences)."""
        if not en_number or not ja_id:
            return False
        
        # Extract just the numeric parts
        en_nums = re.findall(r'\d+', en_number)
        ja_nums = re.findall(r'\d+', ja_id)
        
        return len(en_nums) > 0 and len(ja_nums) > 0 and en_nums[0] == ja_nums[0]
    
    def _is_already_mapped(self, en_card: Dict, ja_card: Dict) -> bool:
        """Check if this card pair is already mapped."""
        for mapping in self.mappings:
            if (mapping['english_card']['id'] == en_card['id'] or
                mapping['japanese_card'].get('japanese_id') == ja_card.get('japanese_id')):
                return True
        return False
    
    def integrate_data(self) -> List[Dict]:
        """Integrate Japanese data into English cards."""
        self.log("Integrating Japanese data...")
        
        # Create a copy of English cards for modification
        integrated_cards = [card.copy() for card in self.english_cards]
        
        # Apply mappings
        updated_count = 0
        for mapping in self.mappings:
            en_card = mapping['english_card']
            ja_card = mapping['japanese_card']
            
            # Find the card in integrated_cards and add Japanese fields
            for i, card in enumerate(integrated_cards):
                if card['id'] == en_card['id']:
                    # Add Japanese name
                    card['name_ja'] = ja_card.get('name_ja')
                    
                    # Add other Japanese fields if available
                    if ja_card.get('image_url_ja'):
                        card['image_url_ja'] = ja_card['image_url_ja']
                    
                    if ja_card.get('text_ja'):
                        card['text_ja'] = ja_card['text_ja']
                    
                    if ja_card.get('attacks_ja'):
                        card['attacks_ja'] = ja_card['attacks_ja']
                    
                    if ja_card.get('abilities_ja'):
                        card['abilities_ja'] = ja_card['abilities_ja']
                    
                    if ja_card.get('weakness_ja'):
                        card['weakness_ja'] = ja_card['weakness_ja']
                    
                    if ja_card.get('evolvesFrom_ja'):
                        card['evolvesFrom_ja'] = ja_card['evolvesFrom_ja']
                    
                    # Add source info
                    card['japanese_source'] = {
                        'japanese_id': ja_card.get('japanese_id'),
                        'regulation': ja_card.get('regulation'),
                        'source_url': ja_card.get('source_url'),
                        'mapping_type': mapping['mapping_type'],
                        'similarity_score': mapping['similarity_score']
                    }
                    
                    updated_count += 1
                    break
        
        # Add Japan-exclusive cards (not mapped to any English card)
        exclusive_cards = []
        mapped_ja_ids = {m['japanese_card'].get('japanese_id') for m in self.mappings}
        
        for ja_card in self.japanese_cards:
            if ja_card.get('japanese_id') not in mapped_ja_ids:
                # Convert Japanese-only card to English format
                converted_card = self._convert_japanese_card(ja_card)
                if converted_card:
                    exclusive_cards.append(converted_card)
        
        integrated_cards.extend(exclusive_cards)
        
        self.log(f"Updated {updated_count} existing cards with Japanese data")
        self.log(f"Added {len(exclusive_cards)} Japan-exclusive cards")
        
        return integrated_cards
    
    def _convert_japanese_card(self, ja_card: Dict) -> Optional[Dict]:
        """Convert Japanese card to English format for Japan-exclusive cards."""
        converted = {
            'id': f"JA-{ja_card.get('japanese_id', 'unknown')}",
            'name': ja_card.get('name_ja', 'Unknown'),
            'name_ja': ja_card.get('name_ja'),
            'set': f"JA-{ja_card.get('regulation', 'unknown')}",
            'number': ja_card.get('japanese_id', ''),
            'category': ja_card.get('category', 'pokemon'),
            'japanese_exclusive': True,
            'regulation': ja_card.get('regulation'),
            'source_url': ja_card.get('source_url')
        }
        
        # Copy other available fields
        fields_to_copy = [
            'hp', 'type', 'stage', 'evolvesFrom', 'weakness', 'retreatCost',
            'trainerType', 'isEx', 'isGx', 'isV', 'isVmax'
        ]
        
        for field in fields_to_copy:
            if field in ja_card:
                converted[field] = ja_card[field]
        
        # Copy Japanese-specific fields
        ja_fields_to_copy = [
            'type_ja', 'text_ja', 'attacks_ja', 'abilities_ja',
            'weakness_ja', 'evolvesFrom_ja', 'image_url_ja'
        ]
        
        for field in ja_fields_to_copy:
            if field in ja_card:
                converted[field] = ja_card[field]
        
        return converted
    
    def create_mapping_file(self, output_path: str) -> None:
        """Create English-Japanese mapping file."""
        mapping_data = {
            'metadata': {
                'total_mappings': len(self.mappings),
                'exact_matches': len([m for m in self.mappings if m['mapping_type'] == 'exact_match']),
                'similarity_matches': len([m for m in self.mappings if m['mapping_type'] == 'name_similarity']),
                'average_similarity': sum(m['similarity_score'] for m in self.mappings) / len(self.mappings) if self.mappings else 0
            },
            'set_mappings': self.set_mappings,
            'name_patterns': self.name_patterns,
            'mappings': []
        }
        
        for mapping in self.mappings:
            mapping_entry = {
                'english_id': mapping['english_card']['id'],
                'english_name': mapping['english_card']['name'],
                'japanese_id': mapping['japanese_card'].get('japanese_id'),
                'japanese_name': mapping['japanese_card'].get('name_ja'),
                'similarity_score': mapping['similarity_score'],
                'mapping_type': mapping['mapping_type'],
                'regulation': mapping['japanese_card'].get('regulation'),
                'set': mapping['english_card'].get('set')
            }
            mapping_data['mappings'].append(mapping_entry)
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(mapping_data, f, ensure_ascii=False, indent=2)
        
        self.log(f"Mapping file saved to {output_path}")


def main():
    """Main CLI interface."""
    parser = argparse.ArgumentParser(description='Integrate Japanese card data with English data')
    parser.add_argument('--japanese-data', '-j', required=True, 
                        help='Path to Japanese card data JSON file')
    parser.add_argument('--english-data', '-e', 
                        default='data/cards_detailed.json',
                        help='Path to English cards_detailed.json')
    parser.add_argument('--output', '-o', 
                        default='data/cards_detailed_integrated.json',
                        help='Output path for integrated data')
    parser.add_argument('--mapping-output', '-m',
                        default='data/ja_en_mapping.json',
                        help='Output path for mapping data')
    parser.add_argument('--similarity-threshold', '-t', type=float, default=0.6,
                        help='Similarity threshold for name matching (0.0-1.0)')
    parser.add_argument('--verbose', '-v', action='store_true', 
                        help='Enable verbose logging')
    
    args = parser.parse_args()
    
    try:
        integrator = JapaneseDataIntegrator(verbose=args.verbose)
        
        # Load data
        integrator.load_japanese_data(args.japanese_data)
        integrator.load_english_data(args.english_data)
        
        # Create mappings
        integrator.create_exact_matching()
        integrator.create_name_similarity_mapping(args.similarity_threshold)
        
        # Integrate data
        integrated_cards = integrator.integrate_data()
        
        # Save integrated data
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(integrated_cards, f, ensure_ascii=False, indent=2)
        
        # Save mapping data
        integrator.create_mapping_file(args.mapping_output)
        
        # Print summary
        print(f"\nIntegration Summary:")
        print(f"Total English cards: {len(integrator.english_cards)}")
        print(f"Total Japanese cards: {len(integrator.japanese_cards)}")
        print(f"Created mappings: {len(integrator.mappings)}")
        print(f"Final integrated cards: {len(integrated_cards)}")
        print(f"Japanese names added: {len([c for c in integrated_cards if 'name_ja' in c])}")
        print(f"Japan-exclusive cards: {len([c for c in integrated_cards if c.get('japanese_exclusive')])}")
        
        print(f"\nFiles created:")
        print(f"  - Integrated cards: {args.output}")
        print(f"  - Mappings: {args.mapping_output}")
        
    except Exception as e:
        print(f"Integration failed: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()