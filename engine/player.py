"""プレイヤークラス"""
from __future__ import annotations
import random
from .card import Card, PokemonCard, EnergyCard, PokemonInPlay


class Player:
    def __init__(self, deck: list[Card], player_id: int = 0):
        self.player_id = player_id
        self.deck = list(deck)
        self.hand: list[Card] = []
        self.active: PokemonInPlay | None = None
        self.bench: list[PokemonInPlay] = []  # 最大5体
        self.prizes: list[Card] = []
        self.discard: list[Card] = []
        self.prizes_taken: int = 0
        self.energy_attached_this_turn: bool = False
    
    def shuffle_deck(self):
        random.shuffle(self.deck)
    
    def draw(self, n: int = 1) -> bool:
        """山札からn枚引く。山札切れならFalse"""
        for _ in range(n):
            if not self.deck:
                return False
            self.hand.append(self.deck.pop())
        return True
    
    def setup(self):
        """初期セットアップ: シャッフル→7枚引く→サイド4枚（ミニデッキなので4枚）"""
        self.shuffle_deck()
        self.draw(7)
        # たねポケモンが手札にない場合、引き直し（簡易: 最大5回）
        for _ in range(5):
            if any(isinstance(c, PokemonCard) for c in self.hand):
                break
            self.deck.extend(self.hand)
            self.hand.clear()
            self.shuffle_deck()
            self.draw(7)
        # サイド4枚（20枚デッキなので少なめ）
        for _ in range(4):
            if self.deck:
                self.prizes.append(self.deck.pop())
    
    def place_active(self, hand_index: int) -> bool:
        """手札からバトル場にポケモンを出す"""
        if hand_index >= len(self.hand):
            return False
        card = self.hand[hand_index]
        if not isinstance(card, PokemonCard):
            return False
        if self.active is not None:
            return False
        self.hand.pop(hand_index)
        self.active = PokemonInPlay(card=card, current_hp=card.hp)
        return True
    
    def place_bench(self, hand_index: int) -> bool:
        """手札からベンチにポケモンを出す"""
        if hand_index >= len(self.hand):
            return False
        card = self.hand[hand_index]
        if not isinstance(card, PokemonCard):
            return False
        if len(self.bench) >= 5:
            return False
        self.hand.pop(hand_index)
        self.bench.append(PokemonInPlay(card=card, current_hp=card.hp))
        return True
    
    def attach_energy(self, hand_index: int, target: str, bench_index: int = 0) -> bool:
        """エネルギーを付ける。target='active' or 'bench'"""
        if self.energy_attached_this_turn:
            return False
        if hand_index >= len(self.hand):
            return False
        card = self.hand[hand_index]
        if not isinstance(card, EnergyCard):
            return False
        
        if target == "active" and self.active:
            pokemon = self.active
        elif target == "bench" and bench_index < len(self.bench):
            pokemon = self.bench[bench_index]
        else:
            return False
        
        self.hand.pop(hand_index)
        pokemon.attach_energy(card.type)
        self.energy_attached_this_turn = True
        return True
    
    def take_prize(self) -> bool:
        """サイドを1枚取る"""
        if self.prizes:
            self.hand.append(self.prizes.pop())
            self.prizes_taken += 1
            return True
        return False
    
    def promote_from_bench(self, bench_index: int) -> bool:
        """ベンチからバトル場にポケモンを出す"""
        if self.active is not None and not self.active.is_knocked_out:
            return False
        if bench_index >= len(self.bench):
            return False
        # きぜつしたポケモンをトラッシュ
        if self.active and self.active.is_knocked_out:
            self.discard.append(self.active.card)
            self.active = None
        self.active = self.bench.pop(bench_index)
        return True
    
    def retreat(self, bench_index: int) -> bool:
        """にげる: エネルギーコスト分を捨てる"""
        if not self.active or bench_index >= len(self.bench):
            return False
        cost = self.active.card.retreat_cost
        if self.active.total_energy() < cost:
            return False
        # エネルギーを捨てる（適当に）
        remaining = cost
        new_energy = dict(self.active.attached_energy)
        for etype in list(new_energy.keys()):
            while new_energy[etype] > 0 and remaining > 0:
                new_energy[etype] -= 1
                remaining -= 1
            if new_energy[etype] == 0:
                del new_energy[etype]
            if remaining == 0:
                break
        self.active.attached_energy = new_energy
        # 入れ替え
        old_active = self.active
        self.active = self.bench.pop(bench_index)
        self.bench.append(old_active)
        return True

    def get_pokemon_in_hand(self) -> list[int]:
        """手札のポケモンカードのインデックスリスト"""
        return [i for i, c in enumerate(self.hand) if isinstance(c, PokemonCard)]

    def get_energy_in_hand(self) -> list[int]:
        """手札のエネルギーカードのインデックスリスト"""
        return [i for i, c in enumerate(self.hand) if isinstance(c, EnergyCard)]
