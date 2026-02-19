"""カードクラス定義 - Phase 2: 進化・トレーナーズ・特殊エネルギー対応"""
from __future__ import annotations
import json
import copy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class Attack:
    name: str
    cost: dict[str, int]       # {"Fire": 1, "Colorless": 2}
    damage: int                 # base damage (0 if variable)
    text: str = ""              # effect text
    effect_id: str = ""         # effect handler key

@dataclass
class Ability:
    name: str
    text: str = ""
    effect_id: str = ""         # ability handler key
    ability_type: str = "Ability"  # "Ability"

@dataclass
class PokemonCard:
    id: str                     # unique id like "OBF-125"
    name: str
    hp: int
    types: list[str]            # ["Fire"], ["Darkness"], etc.
    weakness: str               # type name or ""
    weakness_mult: int = 2
    resistance: str = ""
    resistance_val: int = 0
    retreat_cost: int = 0
    attacks: list[Attack] = field(default_factory=list)
    abilities: list[Ability] = field(default_factory=list)
    stage: str = "Basic"        # "Basic", "Stage 1", "Stage 2"
    evolves_from: str = ""      # name of pre-evolution
    subtypes: list[str] = field(default_factory=list)  # ["ex", "Tera", "Ancient", "MEGA"]
    
    @property
    def is_ex(self) -> bool:
        return "ex" in self.subtypes
    
    @property
    def is_tera(self) -> bool:
        return "Tera" in self.subtypes
    
    @property
    def is_ancient(self) -> bool:
        return "Ancient" in self.subtypes
    
    @property
    def is_mega(self) -> bool:
        return "MEGA" in self.subtypes
    
    @property
    def is_basic(self) -> bool:
        return self.stage == "Basic"
    
    @property
    def prize_value(self) -> int:
        """KO時に相手が取るサイド枚数"""
        if self.is_mega:
            return 3
        if self.is_ex:
            return 2
        return 1
    
    @property
    def has_rule_box(self) -> bool:
        return self.is_ex or self.is_mega


@dataclass
class TrainerCard:
    id: str
    name: str
    trainer_type: str           # "Item", "Supporter", "Stadium", "Pokemon Tool"
    text: str = ""
    effect_id: str = ""
    subtypes: list[str] = field(default_factory=list)  # ["ACE SPEC", "Ancient", etc.]
    
    @property
    def is_ace_spec(self) -> bool:
        return "ACE SPEC" in self.subtypes


@dataclass
class EnergyCard:
    id: str = ""
    name: str = ""
    energy_type: str = ""       # "Fire", "Water", etc. or "Special"
    is_special: bool = False
    provides: list[str] = field(default_factory=list)  # what types it can provide
    text: str = ""
    effect_id: str = ""


# Union type
Card = PokemonCard | TrainerCard | EnergyCard


@dataclass
class PokemonInPlay:
    """場に出ているポケモン"""
    card: PokemonCard
    current_hp: int
    attached_energy: list[EnergyCard] = field(default_factory=list)
    damage_counters: int = 0    # for precise damage counter tracking
    tool: Optional[TrainerCard] = None
    evolved_this_turn: bool = False
    played_this_turn: bool = False  # put into play this turn
    evolution_chain: list[PokemonCard] = field(default_factory=list)  # previous stages
    status: str = ""            # "", "confused", "poisoned", etc.
    cant_attack_next: bool = False
    cant_retreat_next: bool = False
    protected_from_ex: bool = False  # Acerola's Mischief
    
    def total_energy(self) -> int:
        return len(self.attached_energy)
    
    def energy_count_by_type(self) -> dict[str, int]:
        """タイプ別エネルギー数"""
        counts: dict[str, int] = {}
        for e in self.attached_energy:
            if e.is_special:
                # Special energy - handle based on effect_id
                if e.effect_id == "luminous_energy":
                    # Provides any type if no other special energy
                    has_other_special = any(
                        oe.is_special and oe is not e for oe in self.attached_energy
                    )
                    if has_other_special:
                        counts["Colorless"] = counts.get("Colorless", 0) + 1
                    else:
                        counts["_any"] = counts.get("_any", 0) + 1
                elif e.effect_id == "jet_energy":
                    counts["Colorless"] = counts.get("Colorless", 0) + 1
                else:
                    counts["Colorless"] = counts.get("Colorless", 0) + 1
            else:
                counts[e.energy_type] = counts.get(e.energy_type, 0) + 1
        return counts
    
    def basic_energy_count(self) -> int:
        """基本エネルギーの枚数"""
        return sum(1 for e in self.attached_energy if not e.is_special)
    
    def can_use_attack(self, attack: Attack) -> bool:
        """技を使えるかチェック（エネルギーコスト）"""
        counts = self.energy_count_by_type()
        remaining = dict(counts)
        any_count = remaining.pop("_any", 0)
        
        # まず色指定のコストを消費
        for etype, needed in attack.cost.items():
            if etype == "Colorless":
                continue
            available = remaining.get(etype, 0)
            if available >= needed:
                remaining[etype] = available - needed
            else:
                shortfall = needed - available
                remaining[etype] = 0
                # Use _any energy
                if any_count >= shortfall:
                    any_count -= shortfall
                else:
                    return False
        
        # 残りの無色コスト
        colorless_needed = attack.cost.get("Colorless", 0)
        total_remaining = sum(remaining.values()) + any_count
        return total_remaining >= colorless_needed
    
    def attach_energy(self, energy: EnergyCard):
        self.attached_energy.append(energy)
    
    def remove_energy(self, index: int) -> Optional[EnergyCard]:
        if 0 <= index < len(self.attached_energy):
            return self.attached_energy.pop(index)
        return None
    
    def remove_energy_by_type(self, etype: str, count: int = 1) -> list[EnergyCard]:
        """指定タイプのエネルギーをcount枚取り除く"""
        removed = []
        for _ in range(count):
            for i, e in enumerate(self.attached_energy):
                if not e.is_special and e.energy_type == etype:
                    removed.append(self.attached_energy.pop(i))
                    break
        return removed
    
    def take_damage(self, damage: int, attacker_types: list[str] | None = None,
                    apply_weakness: bool = True) -> bool:
        """ダメージを受ける。弱点・抵抗力計算込み。きぜつしたらTrue"""
        if apply_weakness and attacker_types:
            for atype in attacker_types:
                if self.card.weakness == atype:
                    damage *= self.card.weakness_mult
                    break
            if self.card.resistance:
                for atype in attacker_types:
                    if self.card.resistance == atype:
                        damage -= self.card.resistance_val
                        break
        damage = max(0, damage)
        self.current_hp -= damage
        self.damage_counters += damage // 10 if damage > 0 else 0
        return self.current_hp <= 0
    
    def put_damage_counters(self, count: int) -> bool:
        """ダメージカウンターを乗せる（弱点・抵抗力適用なし）"""
        self.current_hp -= count * 10
        self.damage_counters += count
        return self.current_hp <= 0
    
    @property
    def is_knocked_out(self) -> bool:
        return self.current_hp <= 0
    
    @property 
    def effective_retreat_cost(self) -> int:
        cost = self.card.retreat_cost
        # Air Balloon reduces by 2
        if self.tool and self.tool.effect_id == "air_balloon":
            cost = max(0, cost - 2)
        return cost
    
    def get_top_card(self) -> PokemonCard:
        """現在の（最も進化した）カード"""
        return self.card
    
    def get_all_cards(self) -> list:
        """このポケモンに関連する全カード（進化元+エネ+ツール）"""
        cards = list(self.evolution_chain) + [self.card]
        cards.extend(self.attached_energy)
        if self.tool:
            cards.append(self.tool)
        return cards


def _parse_cost(cost_list: list[str]) -> dict[str, int]:
    """["Fire", "Fire", "Colorless"] → {"Fire": 2, "Colorless": 1}"""
    d: dict[str, int] = {}
    for c in cost_list:
        d[c] = d.get(c, 0) + 1
    return d


def _parse_damage(dmg_str: str) -> int:
    """'180+' → 180, '70×' → 70, '' → 0, '30×' → 30"""
    if not dmg_str:
        return 0
    cleaned = dmg_str.replace('+', '').replace('×', '').replace('x', '').strip()
    try:
        return int(cleaned)
    except ValueError:
        return 0
