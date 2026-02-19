#!/Users/molt/.openclaw/workspace/pokemon-tcg-ai/venv/bin/python
"""
Japanese Cards CLI - Comprehensive tool for Japanese Pokémon card data

Provides unified interface for:
- Scraping Japanese cards from pokemon-card.com
- Integrating with English data
- Creating mappings
- Running tests
"""

import argparse
import json
import sys
from pathlib import Path
from datetime import datetime

def setup_logging(verbose: bool = False):
    """Setup logging configuration."""
    import logging
    level = logging.INFO if verbose else logging.WARNING
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%H:%M:%S'
    )

def cmd_scrape(args):
    """Scrape Japanese card data."""
    from scrape_cards_ja import JapaneseCardScraper
    
    print(f"🔍 Starting Japanese card scraping...")
    print(f"   Rate limit: {args.rate_limit}s per request")
    print(f"   Output: {args.output}")
    
    scraper = JapaneseCardScraper(rate_limit=args.rate_limit, verbose=args.verbose)
    
    try:
        if args.regulation:
            # Scrape all cards for regulation
            results = scraper.scrape_regulation_cards(
                regulation=args.regulation,
                output_file=args.output,
                limit=args.limit
            )
            
            print(f"\n📊 Scraping Results:")
            print(f"   Regulation: {results['regulation']}")
            print(f"   Total found: {results['total_found']}")
            print(f"   Successfully scraped: {results['scraped_count']}")
            print(f"   Failed: {results['failed_count']}")
            print(f"   Success rate: {results['success_rate']:.1f}%")
            
            if results['failed_count'] > 0 and args.verbose:
                print(f"\n⚠️  Failed requests:")
                for failure in results['failed_requests'][:10]:
                    print(f"     Card {failure['card_id']}: {failure['reason']}")
                if len(results['failed_requests']) > 10:
                    print(f"     ... and {len(results['failed_requests']) - 10} more")
            
        elif args.card_id:
            # Scrape specific card
            card_data = scraper.fetch_card_details(args.card_id, args.regulation or 'XY')
            
            if card_data:
                if args.output:
                    with open(args.output, 'w', encoding='utf-8') as f:
                        json.dump(card_data, f, ensure_ascii=False, indent=2)
                    print(f"✅ Card data saved to {args.output}")
                else:
                    print(json.dumps(card_data, ensure_ascii=False, indent=2))
            else:
                print(f"❌ Failed to scrape card {args.card_id}")
                return False
        
        else:
            print("❌ Must specify either --regulation or --card-id")
            return False
    
    except KeyboardInterrupt:
        print("\n🛑 Scraping interrupted by user")
        return False
    except Exception as e:
        print(f"❌ Scraping failed: {e}")
        return False
    
    return True

def cmd_integrate(args):
    """Integrate Japanese data with English cards."""
    from integrate_japanese_data import JapaneseDataIntegrator
    
    print(f"🔗 Starting data integration...")
    print(f"   Japanese data: {args.japanese_data}")
    print(f"   English data: {args.english_data}")
    print(f"   Similarity threshold: {args.similarity_threshold}")
    
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
        
        print(f"\n📊 Integration Results:")
        print(f"   Total English cards: {len(integrator.english_cards)}")
        print(f"   Total Japanese cards: {len(integrator.japanese_cards)}")
        print(f"   Created mappings: {len(integrator.mappings)}")
        print(f"   Final integrated cards: {len(integrated_cards)}")
        print(f"   Cards with Japanese names: {len([c for c in integrated_cards if 'name_ja' in c])}")
        print(f"   Japan-exclusive cards: {len([c for c in integrated_cards if c.get('japanese_exclusive')])}")
        
        print(f"\n📄 Files created:")
        print(f"   Integrated cards: {args.output}")
        print(f"   Mappings: {args.mapping_output}")
        
    except Exception as e:
        print(f"❌ Integration failed: {e}")
        return False
    
    return True

def cmd_test(args):
    """Run test suite for Japanese scraper."""
    print(f"🧪 Running Japanese scraper test suite...")
    
    # Import and run tests
    try:
        from test_japanese_scraper import main as run_tests
        setup_logging(args.verbose)
        return run_tests()
    except ImportError as e:
        print(f"❌ Could not import test module: {e}")
        return False

def cmd_quick_sample(args):
    """Quick sample scraping for testing."""
    from scrape_cards_ja import JapaneseCardScraper
    
    print(f"🚀 Quick sample scraping...")
    
    scraper = JapaneseCardScraper(rate_limit=0.5, verbose=True)
    
    # Try to scrape a few sample cards
    sample_ids = ['14890', '15001', '15100', '16000', '16500']
    regulation = args.regulation or 'XY'
    
    scraped_cards = []
    
    for card_id in sample_ids:
        print(f"\n📋 Trying card ID: {card_id}")
        card_data = scraper.fetch_card_details(card_id, regulation)
        
        if card_data:
            scraped_cards.append(card_data)
            print(f"✅ Success: {card_data.get('name_ja', 'Unknown')}")
            
            if len(scraped_cards) >= (args.limit or 3):
                break
        else:
            print(f"❌ Failed to scrape {card_id}")
    
    if scraped_cards:
        # Save sample results
        output_file = args.output or f"data/sample_ja_cards_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        output_path = Path(output_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(scraped_cards, f, ensure_ascii=False, indent=2)
        
        print(f"\n📄 Sample results saved to: {output_file}")
        print(f"   Scraped {len(scraped_cards)} cards successfully")
        
        # Show brief summary
        for card in scraped_cards:
            print(f"   - {card.get('name_ja', 'Unknown')} ({card.get('type', 'Unknown type')})")
    else:
        print(f"❌ No cards could be scraped. Check your internet connection or the site structure.")
        return False
    
    return True

def cmd_workflow(args):
    """Run complete workflow: scrape -> integrate -> report."""
    print(f"🔄 Running complete Japanese card workflow...")
    
    # Step 1: Scrape Japanese cards
    print(f"\n1️⃣ Scraping Japanese cards...")
    scrape_args = type('Args', (), {
        'regulation': args.regulation,
        'card_id': None,
        'output': args.japanese_output,
        'rate_limit': args.rate_limit,
        'limit': args.limit,
        'verbose': args.verbose
    })()
    
    if not cmd_scrape(scrape_args):
        return False
    
    # Step 2: Integrate with English data
    print(f"\n2️⃣ Integrating with English data...")
    integrate_args = type('Args', (), {
        'japanese_data': args.japanese_output,
        'english_data': args.english_data,
        'output': args.output,
        'mapping_output': args.mapping_output,
        'similarity_threshold': args.similarity_threshold,
        'verbose': args.verbose
    })()
    
    if not cmd_integrate(integrate_args):
        return False
    
    # Step 3: Generate report
    print(f"\n3️⃣ Generating workflow report...")
    
    try:
        # Load final results
        with open(args.output, 'r', encoding='utf-8') as f:
            final_cards = json.load(f)
        
        with open(args.mapping_output, 'r', encoding='utf-8') as f:
            mappings = json.load(f)
        
        # Generate report
        report = {
            'workflow_completed': datetime.now().isoformat(),
            'parameters': {
                'regulation': args.regulation,
                'rate_limit': args.rate_limit,
                'limit': args.limit,
                'similarity_threshold': args.similarity_threshold
            },
            'results': {
                'total_final_cards': len(final_cards),
                'cards_with_japanese': len([c for c in final_cards if 'name_ja' in c]),
                'japanese_exclusive': len([c for c in final_cards if c.get('japanese_exclusive')]),
                'mappings_created': len(mappings.get('mappings', [])),
                'average_similarity': mappings.get('metadata', {}).get('average_similarity', 0)
            },
            'files_created': [
                args.japanese_output,
                args.output,
                args.mapping_output
            ]
        }
        
        # Save report
        report_file = f"data/workflow_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(report_file, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        
        print(f"\n📊 Workflow Complete!")
        print(f"   Final cards: {report['results']['total_final_cards']}")
        print(f"   With Japanese names: {report['results']['cards_with_japanese']}")
        print(f"   Japan-exclusive: {report['results']['japanese_exclusive']}")
        print(f"   Report saved to: {report_file}")
        
    except Exception as e:
        print(f"⚠️ Workflow completed but report generation failed: {e}")
    
    return True

def main():
    """Main CLI interface."""
    parser = argparse.ArgumentParser(
        description='Japanese Pokémon TCG Card Data Tool',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Quick test
  %(prog)s test
  
  # Sample a few cards
  %(prog)s sample --regulation H --limit 5
  
  # Scrape all cards for regulation H
  %(prog)s scrape --regulation H --limit 100
  
  # Integrate Japanese data with English cards
  %(prog)s integrate --japanese-data data/cards_ja_h.json
  
  # Complete workflow
  %(prog)s workflow --regulation H --limit 50
        """
    )
    
    # Global options
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='Enable verbose logging')
    
    # Subcommands
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    # Test command
    test_parser = subparsers.add_parser('test', help='Run test suite')
    
    # Sample command
    sample_parser = subparsers.add_parser('sample', help='Quick sample scraping')
    sample_parser.add_argument('--regulation', '-r', default='H', 
                               choices=['H', 'I', 'J', 'XY'],
                               help='Regulation to sample from')
    sample_parser.add_argument('--limit', '-l', type=int, default=3,
                               help='Number of cards to sample')
    sample_parser.add_argument('--output', '-o', 
                               help='Output file (default: auto-generated)')
    
    # Scrape command
    scrape_parser = subparsers.add_parser('scrape', help='Scrape Japanese cards')
    scrape_parser.add_argument('--regulation', '-r', 
                               choices=['H', 'I', 'J', 'XY'],
                               help='Regulation to scrape')
    scrape_parser.add_argument('--card-id', '-c',
                               help='Specific card ID to scrape')
    scrape_parser.add_argument('--output', '-o', required=True,
                               help='Output JSON file')
    scrape_parser.add_argument('--limit', '-l', type=int,
                               help='Maximum number of cards to scrape')
    scrape_parser.add_argument('--rate-limit', type=float, default=1.0,
                               help='Rate limit in seconds (default: 1.0)')
    
    # Integrate command
    integrate_parser = subparsers.add_parser('integrate', help='Integrate Japanese with English data')
    integrate_parser.add_argument('--japanese-data', '-j', required=True,
                                  help='Japanese card data JSON file')
    integrate_parser.add_argument('--english-data', '-e', 
                                  default='data/cards_detailed.json',
                                  help='English cards_detailed.json file')
    integrate_parser.add_argument('--output', '-o',
                                  default='data/cards_detailed_integrated.json',
                                  help='Output integrated data file')
    integrate_parser.add_argument('--mapping-output', '-m',
                                  default='data/ja_en_mapping.json',
                                  help='Output mapping file')
    integrate_parser.add_argument('--similarity-threshold', '-t', type=float, 
                                  default=0.6, help='Similarity threshold (0.0-1.0)')
    
    # Workflow command (complete process)
    workflow_parser = subparsers.add_parser('workflow', help='Complete workflow: scrape -> integrate')
    workflow_parser.add_argument('--regulation', '-r', required=True,
                                 choices=['H', 'I', 'J', 'XY'],
                                 help='Regulation to scrape')
    workflow_parser.add_argument('--limit', '-l', type=int, default=100,
                                 help='Maximum cards to scrape')
    workflow_parser.add_argument('--rate-limit', type=float, default=1.0,
                                 help='Rate limit in seconds')
    workflow_parser.add_argument('--similarity-threshold', '-t', type=float, 
                                 default=0.6, help='Similarity threshold')
    workflow_parser.add_argument('--english-data', '-e', 
                                 default='data/cards_detailed.json',
                                 help='English cards file')
    workflow_parser.add_argument('--japanese-output',
                                 default='data/cards_ja_scraped.json',
                                 help='Intermediate Japanese data file')
    workflow_parser.add_argument('--output', '-o',
                                 default='data/cards_detailed_integrated.json',
                                 help='Final integrated data file')
    workflow_parser.add_argument('--mapping-output', '-m',
                                 default='data/ja_en_mapping.json',
                                 help='Mapping output file')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        sys.exit(1)
    
    # Setup logging
    setup_logging(args.verbose)
    
    # Execute command
    commands = {
        'test': cmd_test,
        'sample': cmd_quick_sample,
        'scrape': cmd_scrape,
        'integrate': cmd_integrate,
        'workflow': cmd_workflow
    }
    
    success = commands[args.command](args)
    sys.exit(0 if success else 1)

if __name__ == '__main__':
    main()