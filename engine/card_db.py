"""カードデータベース - 3デッキの全カードを定義"""
from __future__ import annotations
import json
from pathlib import Path
from .card import (
    PokemonCard, TrainerCard, EnergyCard, Attack, Ability, Card,
    _parse_cost, _parse_damage,
)

# Set code → raw data filename
SET_MAP = {
    'OBF': 'sv3', 'TWM': 'sv6', 'TEF': 'sv5', 'SCR': 'sv7',
    'PAF': 'sv4pt5', 'PAR': 'sv4', 'PAL': 'sv2', 'SVI': 'sv1',
    'MEW': 'sv3pt5', 'PRE': 'sv8pt5', 'SSP': 'sv8',
    'SVE': 'sve', 'MEE': 'sve',
    'MEG': 'me1', 'PFL': 'me2', 'ASC': 'me2pt5',
}

# Effect ID mappings for special cards
ATTACK_EFFECTS = {
    "Burning Darkness": "burning_darkness",
    "Bellowing Thunder": "bellowing_thunder",
    "Phantom Dive": "phantom_dive",
    "Myriad Leaf Shower": "myriad_leaf_shower",
    "Burst Roar": "burst_roar",
    "Unified Beatdown": "unified_beatdown",
    "Crown Opal": "crown_opal",
    "Cruel Arrow": "cruel_arrow",
    "Thunderburst Storm": "thunderburst_storm",
    "Genome Hacking": "genome_hacking",
    "Eon Blade": "eon_blade",
    "Rapid-Fire Combo": "rapid_fire_combo",
    "Megafire of Envy": "megafire_of_envy",
    "Flare Bringer": "flare_bringer",
    "Shadow Bind": "shadow_bind",
    "Blustery Wind": "blustery_wind",
    "Evolution": "tm_evolution",
    "Assault Landing": "assault_landing",
    "Blazing Destruction": "blazing_destruction",
    "Come and Get You": "come_and_get_you",
    "Call for Family": "call_for_family",
    "Triple Stab": "triple_stab",
}

ABILITY_EFFECTS = {
    "Infernal Reign": "infernal_reign",
    "Quick Search": "quick_search",
    "Teal Dance": "teal_dance",
    "Fan Call": "fan_call",
    "Jewel Seeker": "jewel_seeker",
    "Flip the Script": "flip_the_script",
    "Adrena-Brain": "adrena_brain",
    "Transformative Start": "transformative_start",
    "Mischievous Lock": "mischievous_lock",
    "Cursed Blast": "cursed_blast",
    "Flying Entry": "flying_entry",
    "Restart": "restart",
    "Run Errand": "run_errand",
    "Skyliner": "skyliner",
    "Damp": "damp",
    "Recon Directive": "recon_directive",
    "Insomnia": "insomnia",
    "Agile": "agile",
}

TRAINER_EFFECTS = {
    "Boss's Orders": "boss_orders",
    "Iono": "iono",
    "Dawn": "dawn",
    "Lillie's Determination": "lillies_determination",
    "Crispin": "crispin",
    "Professor Sada's Vitality": "sada_vitality",
    "Briar": "briar",
    "Acerola's Mischief": "acerola_mischief",
    "Professor Turo's Scenario": "turo_scenario",
    "Rare Candy": "rare_candy",
    "Buddy-Buddy Poffin": "buddy_buddy_poffin",
    "Nest Ball": "nest_ball",
    "Ultra Ball": "ultra_ball",
    "Night Stretcher": "night_stretcher",
    "Super Rod": "super_rod",
    "Prime Catcher": "prime_catcher",
    "Counter Catcher": "counter_catcher",
    "Unfair Stamp": "unfair_stamp",
    "Earthen Vessel": "earthen_vessel",
    "Energy Switch": "energy_switch",
    "Glass Trumpet": "glass_trumpet",
    "Technical Machine: Evolution": "tm_evolution_tool",
    "Air Balloon": "air_balloon",
    "Vitality Band": "vitality_band",
    "Area Zero Underdepths": "area_zero_underdepths",
    "Artazon": "artazon",
}

ENERGY_EFFECTS = {
    "Jet Energy": "jet_energy",
    "Luminous Energy": "luminous_energy",
}


def _load_raw_card(set_code: str, number: str) -> dict | None:
    """Load a single card from raw data"""
    raw_file = SET_MAP.get(set_code)
    if not raw_file:
        return None
    path = Path(__file__).parent.parent / "data" / "raw" / "cards" / "en" / f"{raw_file}.json"
    if not path.exists():
        return None
    with open(path) as f:
        cards = json.load(f)
    for c in cards:
        if c.get("number") == number:
            return c
    return None


def _build_pokemon(raw: dict, card_id: str) -> PokemonCard:
    """Raw JSON → PokemonCard"""
    attacks = []
    for a in raw.get("attacks", []):
        atk = Attack(
            name=a["name"],
            cost=_parse_cost(a.get("cost", [])),
            damage=_parse_damage(a.get("damage", "")),
            text=a.get("text", ""),
            effect_id=ATTACK_EFFECTS.get(a["name"], ""),
        )
        attacks.append(atk)
    
    abilities = []
    for a in raw.get("abilities", []):
        ab = Ability(
            name=a["name"],
            text=a.get("text", ""),
            effect_id=ABILITY_EFFECTS.get(a["name"], ""),
            ability_type=a.get("type", "Ability"),
        )
        abilities.append(ab)
    
    weakness = ""
    weakness_mult = 2
    for w in raw.get("weaknesses", []):
        weakness = w["type"]
        weakness_mult = int(w.get("value", "×2").replace("×", ""))
    
    resistance = ""
    resistance_val = 0
    for r in raw.get("resistances", []):
        resistance = r["type"]
        resistance_val = abs(int(r.get("value", "-30")))
    
    retreat = raw.get("convertedRetreatCost", 0)
    
    subtypes = raw.get("subtypes", [])
    stage = "Basic"
    if "Stage 1" in subtypes:
        stage = "Stage 1"
    elif "Stage 2" in subtypes:
        stage = "Stage 2"
    
    clean_subtypes = [s for s in subtypes if s not in ("Basic", "Stage 1", "Stage 2")]
    
    return PokemonCard(
        id=card_id,
        name=raw["name"],
        hp=int(raw.get("hp", 0)),
        types=raw.get("types", ["Colorless"]),
        weakness=weakness,
        weakness_mult=weakness_mult,
        resistance=resistance,
        resistance_val=resistance_val,
        retreat_cost=retreat,
        attacks=attacks,
        abilities=abilities,
        stage=stage,
        evolves_from=raw.get("evolvesFrom", ""),
        subtypes=clean_subtypes,
    )


def _build_trainer(raw: dict, card_id: str) -> TrainerCard:
    """Raw JSON → TrainerCard"""
    subtypes = raw.get("subtypes", [])
    trainer_type = "Item"
    if "Supporter" in subtypes:
        trainer_type = "Supporter"
    elif "Stadium" in subtypes:
        trainer_type = "Stadium"
    elif "Pokémon Tool" in subtypes:
        trainer_type = "Pokemon Tool"
    
    name = raw["name"]
    text = ""
    for r in raw.get("rules", []):
        if "You may play" not in r and "ACE SPEC" not in r and "Attach a Pokémon Tool" not in r:
            text = r
            break
    
    clean_subtypes = [s for s in subtypes if s not in ("Item", "Supporter", "Stadium", "Pokémon Tool")]
    
    return TrainerCard(
        id=card_id,
        name=name,
        trainer_type=trainer_type,
        text=text,
        effect_id=TRAINER_EFFECTS.get(name, ""),
        subtypes=clean_subtypes,
    )


def _build_energy(raw: dict, card_id: str) -> EnergyCard:
    """Raw JSON → EnergyCard"""
    name = raw["name"]
    subtypes = raw.get("subtypes", [])
    is_special = "Special" in subtypes
    text = ""
    for r in raw.get("rules", []):
        text = r
        break
    
    return EnergyCard(
        id=card_id,
        name=name,
        energy_type="Special" if is_special else name.replace(" Energy", ""),
        is_special=is_special,
        provides=[],
        text=text,
        effect_id=ENERGY_EFFECTS.get(name, ""),
    )


def make_basic_energy(etype: str) -> EnergyCard:
    """基本エネルギーを生成"""
    return EnergyCard(
        id=f"energy-{etype.lower()}",
        name=f"{etype} Energy",
        energy_type=etype,
        is_special=False,
    )


# ========== Card Database ==========

_CARD_CACHE: dict[str, Card] = {}

def _get_card(set_code: str, number: str) -> Card:
    key = f"{set_code}-{number}"
    if key in _CARD_CACHE:
        return _CARD_CACHE[key]
    
    raw = _load_raw_card(set_code, number)
    if raw is None:
        raise ValueError(f"Card not found: {key}")
    
    supertype = raw.get("supertype", "")
    if supertype == "Pokémon":
        card = _build_pokemon(raw, key)
    elif supertype == "Trainer":
        card = _build_trainer(raw, key)
    elif supertype == "Energy":
        card = _build_energy(raw, key)
    else:
        raise ValueError(f"Unknown supertype: {supertype} for {key}")
    
    _CARD_CACHE[key] = card
    return card


def get_card(card_id: str) -> Card:
    """'OBF-125' format → Card"""
    parts = card_id.split("-")
    return _get_card(parts[0], parts[1])


# ========== Deck Definitions ==========

import copy

def _build_deck_from_list(deck_list: list[tuple[int, str, str]]) -> list[Card]:
    """[(count, set_code, number), ...] → デッキ(cardリスト)"""
    deck = []
    for count, set_code, number in deck_list:
        card = _get_card(set_code, number)
        for _ in range(count):
            deck.append(copy.deepcopy(card))
    return deck


# デッキ1: リザードンex / ノクタス型
DECK1_CHARIZARD_NOCTOWL = [
    (3, "SCR", "114"),   # Hoothoot
    (3, "SCR", "115"),   # Noctowl
    (2, "PAF", "7"),     # Charmander
    (1, "PFL", "11"),    # Charmander
    (1, "PFL", "12"),    # Charmeleon
    (2, "OBF", "125"),   # Charizard ex
    (2, "PRE", "35"),    # Duskull
    (1, "PRE", "36"),    # Dusclops
    (1, "PRE", "37"),    # Dusknoir
    (1, "MEW", "16"),    # Pidgey
    (1, "OBF", "162"),   # Pidgey
    (1, "MEW", "17"),    # Pidgeotto
    (2, "OBF", "164"),   # Pidgeot ex
    (2, "SCR", "118"),   # Fan Rotom
    (1, "SVI", "96"),    # Klefki
    (1, "MEW", "132"),   # Ditto
    (1, "ASC", "142"),   # Fezandipiti ex
    (1, "TWM", "64"),    # Wellspring Mask Ogerpon ex
    (1, "SCR", "128"),   # Terapagos ex
    (4, "PFL", "87"),    # Dawn
    (2, "MEG", "114"),   # Boss's Orders
    (1, "PAL", "185"),   # Iono
    (1, "SCR", "132"),   # Briar
    (4, "MEG", "125"),   # Rare Candy
    (4, "TEF", "144"),   # Buddy-Buddy Poffin
    (3, "SVI", "181"),   # Nest Ball
    (1, "MEG", "131"),   # Ultra Ball
    (1, "ASC", "196"),   # Night Stretcher
    (1, "PAL", "188"),   # Super Rod
    (1, "TEF", "157"),   # Prime Catcher
    (2, "SCR", "131"),   # Area Zero Underdepths
]

DECK1_ENERGY = [
    ("Fire", 5),
    ("Water", 1),
]
DECK1_SPECIAL_ENERGY = [
    (1, "PAL", "190"),   # Jet Energy
]

# デッキ2: ドラパルトex / リザードン型
DECK2_DRAGAPULT_CHARIZARD = [
    (4, "TWM", "128"),   # Dreepy
    (4, "TWM", "129"),   # Drakloak
    (2, "TWM", "130"),   # Dragapult ex
    (3, "PAF", "7"),     # Charmander
    (1, "PFL", "12"),    # Charmeleon
    (2, "OBF", "125"),   # Charizard ex
    (1, "ASC", "16"),    # Budew
    (1, "TWM", "95"),    # Munkidori
    (1, "SVI", "118"),   # Hawlucha
    (1, "PAR", "29"),    # Chi-Yu
    (1, "ASC", "142"),   # Fezandipiti ex
    (4, "MEG", "119"),   # Lillie's Determination
    (3, "MEG", "114"),   # Boss's Orders
    (3, "PAL", "185"),   # Iono
    (1, "MEG", "113"),   # Acerola's Mischief
    (4, "TEF", "144"),   # Buddy-Buddy Poffin
    (4, "MEG", "131"),   # Ultra Ball
    (2, "MEG", "125"),   # Rare Candy
    (1, "PAL", "188"),   # Super Rod
    (1, "ASC", "196"),   # Night Stretcher
    (1, "PAR", "160"),   # Counter Catcher
    (1, "TWM", "165"),   # Unfair Stamp
    (1, "ASC", "181"),   # Air Balloon
    (1, "PAR", "178"),   # Technical Machine: Evolution
]

DECK2_ENERGY = [
    ("Fire", 5),
]
DECK2_SPECIAL_ENERGY = [
    (4, "PAL", "191"),   # Luminous Energy
]

# デッキ3: タケルライコex / オーガポン型
DECK3_RAGING_BOLT = [
    (2, "SCR", "114"),   # Hoothoot
    (1, "PRE", "77"),    # Hoothoot
    (3, "SCR", "115"),   # Noctowl
    (2, "TWM", "25"),    # Teal Mask Ogerpon ex
    (2, "TEF", "123"),   # Raging Bolt ex
    (2, "SCR", "118"),   # Fan Rotom
    (1, "MEW", "132"),   # Ditto
    (1, "MEW", "151"),   # Mew ex
    (1, "TWM", "64"),    # Wellspring Mask Ogerpon ex
    (1, "ASC", "142"),   # Fezandipiti ex
    (1, "SCR", "111"),   # Raging Bolt
    (1, "SSP", "76"),    # Latias ex
    (1, "MEG", "104"),   # Mega Kangaskhan ex
    (1, "ASC", "39"),    # Psyduck
    (4, "SCR", "133"),   # Crispin
    (3, "PAR", "170"),   # Professor Sada's Vitality
    (1, "MEG", "114"),   # Boss's Orders
    (1, "PAR", "171"),   # Professor Turo's Scenario
    (4, "SVI", "181"),   # Nest Ball
    (4, "MEG", "131"),   # Ultra Ball
    (2, "PAR", "163"),   # Earthen Vessel
    (2, "ASC", "196"),   # Night Stretcher
    (1, "MEG", "115"),   # Energy Switch
    (1, "TEF", "157"),   # Prime Catcher
    (1, "SCR", "135"),   # Glass Trumpet
    (1, "SVI", "197"),   # Vitality Band
    (2, "SCR", "131"),   # Area Zero Underdepths
    (1, "PAL", "171"),   # Artazon
]

DECK3_ENERGY = [
    ("Grass", 5),
    ("Fighting", 3),
    ("Lightning", 3),
    ("Water", 1),
]
DECK3_SPECIAL_ENERGY = []


def build_deck(deck_id: int) -> list[Card]:
    """デッキID (0,1,2) からデッキを構築"""
    if deck_id == 0:
        cards_def, energy_def, special_def = DECK1_CHARIZARD_NOCTOWL, DECK1_ENERGY, DECK1_SPECIAL_ENERGY
    elif deck_id == 1:
        cards_def, energy_def, special_def = DECK2_DRAGAPULT_CHARIZARD, DECK2_ENERGY, DECK2_SPECIAL_ENERGY
    elif deck_id == 2:
        cards_def, energy_def, special_def = DECK3_RAGING_BOLT, DECK3_ENERGY, DECK3_SPECIAL_ENERGY
    else:
        raise ValueError(f"Unknown deck_id: {deck_id}")
    
    deck = _build_deck_from_list(cards_def)
    
    # Basic energy
    for etype, count in energy_def:
        for _ in range(count):
            deck.append(copy.deepcopy(make_basic_energy(etype)))
    
    # Special energy
    for count, sc, num in special_def:
        card = _get_card(sc, num)
        for _ in range(count):
            deck.append(copy.deepcopy(card))
    
    return deck


def get_all_deck_ids() -> list[int]:
    return [0, 1, 2]


DECK_NAMES = {
    0: "Charizard ex / Noctowl",
    1: "Dragapult ex / Charizard ex",
    2: "Raging Bolt ex / Ogerpon",
}
