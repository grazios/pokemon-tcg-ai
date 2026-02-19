"""プレイヤークラス - Phase 2"""
from __future__ import annotations
import random
from .card import Card, PokemonCard, TrainerCard, EnergyCard, PokemonInPlay


class Player:
    PRIZE_COUNT = 6  # 60枚デッキ = サイド6枚
    MAX_BENCH = 5
    
    def __init__(self, deck: list[Card], player_id: int = 0):
        self.player_id = player_id
        self.deck = list(deck)
        self.hand: list[Card] = []
        self.active: PokemonInPlay | None = None
        self.bench: list[PokemonInPlay] = []
        self.prizes: list[Card] = []
        self.discard: list[Card] = []
        self.prizes_taken: int = 0
        self.energy_attached_this_turn: bool = False
        self.supporter_played_this_turn: bool = False
        self.stadium_played_this_turn: bool = False
        self.pokemon_knocked_out_last_turn: bool = False  # 前ターンにきぜつしたか
        self.max_bench: int = self.MAX_BENCH
        self.fan_call_used_this_turn: bool = False
        self.flip_the_script_used_this_turn: bool = False
        self.quick_search_used_this_turn: bool = False
        self.run_errand_used_this_turn: bool = False
    
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
        """初期セットアップ: シャッフル→7枚引く→サイド6枚"""
        self.shuffle_deck()
        self.draw(7)
        # たねポケモンが手札にない場合、引き直し
        for _ in range(10):
            if any(isinstance(c, PokemonCard) and c.is_basic for c in self.hand):
                break
            self.deck.extend(self.hand)
            self.hand.clear()
            self.shuffle_deck()
            self.draw(7)
        # サイド6枚
        for _ in range(self.PRIZE_COUNT):
            if self.deck:
                self.prizes.append(self.deck.pop())
    
    def place_active(self, hand_index: int) -> bool:
        """手札からバトル場にたねポケモンを出す"""
        if hand_index >= len(self.hand):
            return False
        card = self.hand[hand_index]
        if not isinstance(card, PokemonCard) or not card.is_basic:
            return False
        if self.active is not None:
            return False
        self.hand.pop(hand_index)
        pip = PokemonInPlay(card=card, current_hp=card.hp)
        pip.played_this_turn = True
        self.active = pip
        return True
    
    def place_bench(self, hand_index: int) -> bool:
        """手札からベンチにたねポケモンを出す"""
        if hand_index >= len(self.hand):
            return False
        card = self.hand[hand_index]
        if not isinstance(card, PokemonCard) or not card.is_basic:
            return False
        if len(self.bench) >= self.max_bench:
            return False
        self.hand.pop(hand_index)
        pip = PokemonInPlay(card=card, current_hp=card.hp)
        pip.played_this_turn = True
        self.bench.append(pip)
        return True
    
    def place_bench_from_deck(self, card: PokemonCard) -> bool:
        """デッキからベンチにたねポケモンを出す（Nest Ball等）"""
        if not card.is_basic:
            return False
        if len(self.bench) >= self.max_bench:
            return False
        pip = PokemonInPlay(card=card, current_hp=card.hp)
        pip.played_this_turn = True
        self.bench.append(pip)
        return True
    
    def evolve(self, pokemon: PokemonInPlay, evolution_card: PokemonCard,
               hand_index: int | None = None) -> bool:
        """ポケモンを進化させる"""
        if pokemon.played_this_turn or pokemon.evolved_this_turn:
            return False
        if evolution_card.evolves_from != pokemon.card.name:
            return False
        
        # Remove from hand if hand_index given
        if hand_index is not None and hand_index < len(self.hand):
            self.hand.pop(hand_index)
        
        # Save old card to evolution chain
        pokemon.evolution_chain.append(pokemon.card)
        pokemon.card = evolution_card
        pokemon.current_hp = min(
            pokemon.current_hp + (evolution_card.hp - pokemon.evolution_chain[-1].hp),
            evolution_card.hp
        )
        if pokemon.current_hp < pokemon.card.hp:
            # Recalculate: new max HP with same damage
            damage_taken = sum(c.hp for c in pokemon.evolution_chain[-1:]) - (pokemon.current_hp - (evolution_card.hp - pokemon.evolution_chain[-1].hp))
            # Simpler: just set HP to new max - damage already taken
            old_max = pokemon.evolution_chain[-1].hp
            old_hp = pokemon.current_hp - (evolution_card.hp - old_max)
            damage = old_max - old_hp
            pokemon.current_hp = evolution_card.hp - damage
        
        pokemon.evolved_this_turn = True
        pokemon.status = ""  # 進化で状態異常回復
        pokemon.cant_attack_next = False
        pokemon.cant_retreat_next = False
        return True
    
    def evolve_with_rare_candy(self, basic_pokemon: PokemonInPlay,
                                stage2_card: PokemonCard,
                                hand_index_candy: int,
                                hand_index_stage2: int) -> bool:
        """ふしぎなアメで一気にStage2へ進化"""
        if basic_pokemon.played_this_turn:
            return False
        if basic_pokemon.card.stage != "Basic":
            return False
        if stage2_card.stage != "Stage 2":
            return False
        # Check evolution chain validity (Stage 2 evolves from Stage 1 that evolves from this Basic)
        # Simplified: just check the name matches via evolves_from chain
        # We need the Stage 1 intermediate to validate
        # For simplicity, we trust the caller
        
        # Remove cards from hand (higher index first)
        indices = sorted([hand_index_candy, hand_index_stage2], reverse=True)
        for idx in indices:
            if idx < len(self.hand):
                self.hand.pop(idx)
        
        basic_pokemon.evolution_chain.append(basic_pokemon.card)
        damage = basic_pokemon.card.hp - basic_pokemon.current_hp
        basic_pokemon.card = stage2_card
        basic_pokemon.current_hp = stage2_card.hp - damage
        basic_pokemon.evolved_this_turn = True
        basic_pokemon.status = ""
        return True
    
    def attach_energy(self, hand_index: int, target: PokemonInPlay) -> bool:
        """手札からエネルギーを付ける"""
        if self.energy_attached_this_turn:
            return False
        if hand_index >= len(self.hand):
            return False
        card = self.hand[hand_index]
        if not isinstance(card, EnergyCard):
            return False
        
        self.hand.pop(hand_index)
        target.attach_energy(card)
        self.energy_attached_this_turn = True
        return True
    
    def attach_energy_from_hand_free(self, hand_index: int, target: PokemonInPlay) -> bool:
        """エネルギーを付ける（ターン制限なし、特性・トレーナーズ用）"""
        if hand_index >= len(self.hand):
            return False
        card = self.hand[hand_index]
        if not isinstance(card, EnergyCard):
            return False
        self.hand.pop(hand_index)
        target.attach_energy(card)
        return True
    
    def take_prize(self, n: int = 1) -> int:
        """サイドをn枚取る。実際に取った枚数を返す"""
        taken = 0
        for _ in range(n):
            if self.prizes:
                self.hand.append(self.prizes.pop())
                self.prizes_taken += 1
                taken += 1
        return taken
    
    def promote_from_bench(self, bench_index: int) -> bool:
        """ベンチからバトル場に"""
        if bench_index >= len(self.bench):
            return False
        # きぜつしたポケモンをトラッシュ
        if self.active and self.active.is_knocked_out:
            self._discard_pokemon(self.active)
            self.active = None
        if self.active is not None:
            return False
        self.active = self.bench.pop(bench_index)
        return True
    
    def retreat(self, bench_index: int) -> bool:
        """にげる"""
        if not self.active or bench_index >= len(self.bench):
            return False
        cost = self.active.effective_retreat_cost
        if self.active.total_energy() < cost:
            return False
        if self.active.cant_retreat_next:
            return False
        # エネルギーを捨てる
        remaining = cost
        while remaining > 0 and self.active.attached_energy:
            e = self.active.attached_energy.pop(0)
            self.discard.append(e)
            remaining -= 1
        # 入れ替え
        old_active = self.active
        self.active = self.bench.pop(bench_index)
        self.bench.append(old_active)
        return True
    
    def switch_active(self, bench_index: int) -> bool:
        """バトル場とベンチを入れ替え（コストなし、Boss等）"""
        if not self.active or bench_index >= len(self.bench):
            return False
        old_active = self.active
        self.active = self.bench.pop(bench_index)
        self.bench.append(old_active)
        return True
    
    def _discard_pokemon(self, pip: PokemonInPlay):
        """ポケモンをトラッシュ（全付属カード含む）"""
        for card in pip.get_all_cards():
            self.discard.append(card)
    
    def discard_active(self):
        """バトル場のポケモンをトラッシュ"""
        if self.active:
            self._discard_pokemon(self.active)
            self.active = None
    
    def get_all_pokemon_in_play(self) -> list[PokemonInPlay]:
        """場の全ポケモン"""
        result = []
        if self.active:
            result.append(self.active)
        result.extend(self.bench)
        return result
    
    def has_tera_in_play(self) -> bool:
        return any(p.card.is_tera for p in self.get_all_pokemon_in_play())
    
    def has_ancient_in_play(self) -> bool:
        return any(p.card.is_ancient for p in self.get_all_pokemon_in_play())
    
    def get_basics_in_hand(self) -> list[int]:
        """手札のたねポケモンのインデックス"""
        return [i for i, c in enumerate(self.hand) 
                if isinstance(c, PokemonCard) and c.is_basic]
    
    def get_pokemon_in_hand(self) -> list[int]:
        """手札のポケモンカードのインデックス"""
        return [i for i, c in enumerate(self.hand) if isinstance(c, PokemonCard)]
    
    def get_energy_in_hand(self) -> list[int]:
        """手札のエネルギーカードのインデックス"""
        return [i for i, c in enumerate(self.hand) if isinstance(c, EnergyCard)]
    
    def get_trainers_in_hand(self) -> list[int]:
        """手札のトレーナーズのインデックス"""
        return [i for i, c in enumerate(self.hand) if isinstance(c, TrainerCard)]
    
    def get_supporters_in_hand(self) -> list[int]:
        return [i for i, c in enumerate(self.hand) 
                if isinstance(c, TrainerCard) and c.trainer_type == "Supporter"]
    
    def get_items_in_hand(self) -> list[int]:
        return [i for i, c in enumerate(self.hand) 
                if isinstance(c, TrainerCard) and c.trainer_type == "Item"]
    
    def get_stadiums_in_hand(self) -> list[int]:
        return [i for i, c in enumerate(self.hand) 
                if isinstance(c, TrainerCard) and c.trainer_type == "Stadium"]
    
    def get_tools_in_hand(self) -> list[int]:
        return [i for i, c in enumerate(self.hand)
                if isinstance(c, TrainerCard) and c.trainer_type == "Pokemon Tool"]
    
    def find_in_deck(self, predicate) -> list[int]:
        """デッキ内でpredicateを満たすカードのインデックスリスト"""
        return [i for i, c in enumerate(self.deck) if predicate(c)]
    
    def search_deck_pokemon(self, name: str = "", basic_only: bool = False,
                            stage: str = "") -> list[int]:
        """デッキからポケモンを検索"""
        def pred(c):
            if not isinstance(c, PokemonCard):
                return False
            if name and c.name != name:
                return False
            if basic_only and not c.is_basic:
                return False
            if stage and c.stage != stage:
                return False
            return True
        return self.find_in_deck(pred)
    
    def search_deck_energy(self, etype: str = "", basic_only: bool = False) -> list[int]:
        """デッキからエネルギーを検索"""
        def pred(c):
            if not isinstance(c, EnergyCard):
                return False
            if basic_only and c.is_special:
                return False
            if etype and c.energy_type != etype:
                return False
            return True
        return self.find_in_deck(pred)
    
    def search_deck_trainer(self, name: str = "") -> list[int]:
        def pred(c):
            if not isinstance(c, TrainerCard):
                return False
            if name and c.name != name:
                return False
            return True
        return self.find_in_deck(pred)
    
    def take_from_deck(self, index: int) -> Card | None:
        if 0 <= index < len(self.deck):
            return self.deck.pop(index)
        return None
    
    def find_in_discard(self, predicate) -> list[int]:
        return [i for i, c in enumerate(self.discard) if predicate(c)]
    
    def take_from_discard(self, index: int) -> Card | None:
        if 0 <= index < len(self.discard):
            return self.discard.pop(index)
        return None
    
    def start_turn(self):
        """ターン開始時のリセット"""
        self.energy_attached_this_turn = False
        self.supporter_played_this_turn = False
        self.stadium_played_this_turn = False
        self.fan_call_used_this_turn = False
        self.flip_the_script_used_this_turn = False
        self.quick_search_used_this_turn = False
        self.run_errand_used_this_turn = False
        # Reset per-turn pokemon flags
        for p in self.get_all_pokemon_in_play():
            p.evolved_this_turn = False
            p.played_this_turn = False
            p.cant_attack_next = False
            p.protected_from_ex = False
    
    def end_turn(self):
        """ターン終了処理"""
        # Discard TM: Evolution at end of turn
        for p in self.get_all_pokemon_in_play():
            if p.tool and p.tool.effect_id == "tm_evolution_tool":
                self.discard.append(p.tool)
                p.tool = None
