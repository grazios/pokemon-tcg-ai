"""カードクラス定義"""
from __future__ import annotations
import json
import copy
from dataclasses import dataclass, field
from pathlib import Path

@dataclass
class Attack:
    name: str
    cost: dict[str, int]  # {"Fire": 1, "Colorless": 2}
    damage: int

@dataclass
class PokemonCard:
    id: str
    name: str
    hp: int
    type: str
    weakness: str
    retreat_cost: int
    attacks: list[Attack]

@dataclass 
class EnergyCard:
    type: str  # "Fire", "Water", etc.

# カードのユニオン型
Card = PokemonCard | EnergyCard

@dataclass
class PokemonInPlay:
    """場に出ているポケモン"""
    card: PokemonCard
    current_hp: int
    attached_energy: dict[str, int] = field(default_factory=dict)
    
    def total_energy(self) -> int:
        return sum(self.attached_energy.values())
    
    def can_use_attack(self, attack: Attack) -> bool:
        """技を使えるかチェック（エネルギーコスト）"""
        remaining = dict(self.attached_energy)
        # まず色指定のコストを消費
        for etype, count in attack.cost.items():
            if etype == "Colorless":
                continue
            if remaining.get(etype, 0) < count:
                return False
            remaining[etype] = remaining.get(etype, 0) - count
        # 残りの無色コスト
        colorless_needed = attack.cost.get("Colorless", 0)
        total_remaining = sum(remaining.values())
        return total_remaining >= colorless_needed
    
    def attach_energy(self, energy_type: str):
        self.attached_energy[energy_type] = self.attached_energy.get(energy_type, 0) + 1
    
    def take_damage(self, damage: int, attacker_type: str) -> bool:
        """ダメージを受ける。弱点計算込み。きぜつしたらTrue"""
        if self.card.weakness == attacker_type:
            damage *= 2  # 弱点: ×2
        self.current_hp -= damage
        return self.current_hp <= 0
    
    @property
    def is_knocked_out(self) -> bool:
        return self.current_hp <= 0


def load_card_db(path: str | None = None) -> dict:
    """カードDBをJSONから読み込み"""
    if path is None:
        path = str(Path(__file__).parent.parent / "data" / "cards.json")
    with open(path) as f:
        data = json.load(f)
    
    pokemon_db = {}
    for p in data["pokemon"]:
        attacks = [Attack(a["name"], a["cost"], a["damage"]) for a in p["attacks"]]
        pokemon_db[p["id"]] = PokemonCard(
            id=p["id"], name=p["name"], hp=p["hp"],
            type=p["type"], weakness=p["weakness"],
            retreat_cost=p["retreat_cost"], attacks=attacks
        )
    return {
        "pokemon": pokemon_db,
        "energy_types": data["energy_types"],
        "deck_template": data["deck_template"]
    }


def build_deck(card_db: dict) -> list[Card]:
    """デッキテンプレートからデッキを構築"""
    deck = []
    template = card_db["deck_template"]
    for pid, count in template["pokemon_counts"].items():
        for _ in range(count):
            deck.append(copy.deepcopy(card_db["pokemon"][pid]))
    for etype, count in template["energy_counts"].items():
        for _ in range(count):
            deck.append(EnergyCard(type=etype))
    return deck
