"""Gymnasium環境 - Phase 2.5: 汎化Observation Space（転移学習対応）"""
from __future__ import annotations
import numpy as np
import random
import gymnasium as gym
from gymnasium import spaces
from engine.game import Game
from engine.actions import NUM_ACTIONS
from engine.card import PokemonCard, TrainerCard, EnergyCard, PokemonInPlay


# タイプエンコーディング
TYPE_MAP = {
    "Fire": 1, "Water": 2, "Lightning": 3, "Psychic": 4,
    "Fighting": 5, "Darkness": 6, "Grass": 7, "Metal": 8,
    "Dragon": 9, "Colorless": 10, "": 0,
}

NUM_TYPES = 11  # 0~10


class PTCGEnv(gym.Env):
    """
    ポケカTCG Gymnasium環境 - Phase 2.5 (汎化obs)
    
    Per pokemon (9 slots × 2 players) = 25 features:
      current_hp/400, max_hp/400, hp_ratio,
      type_id (int 0-10),
      stage (0/1/2), is_ex, is_tera,
      retreat_cost/5,
      total_energy_attached/10,
      energy×6 (Fire/Water/Grass/Lightning/Fighting/Darkness),
      attack1_damage/300, attack2_damage/300,
      attack1_cost, attack2_cost,
      attack1_usable, attack2_usable,
      has_ability, has_tool,
      weakness_match (相手バトル場タイプが自分の弱点か),
      can_evolve_from_hand
    
    Global features = 21:
      my_hand_size, my_hand_pokemon, my_hand_energy, my_hand_trainers,
      my_hand_supporters, my_hand_evolvable,
      my_prizes, my_deck_size, my_supporter_played, my_energy_attached,
      opp_hand_size, opp_prizes, opp_deck_size,
      turn_count/100, has_stadium, has_attacked, is_first_turn,
      prize_diff (my - opp, /6), bench_free_slots/5,
      my_bench_count/5, opp_bench_count/5
    
    Total: 9×25×2 + 21 = 471
    """
    metadata = {"render_modes": ["human"]}
    
    POKEMON_FEATURES = 25
    POKEMON_SLOTS = 9  # active + 8 bench
    GLOBAL_FEATURES = 21
    OBS_SIZE = POKEMON_SLOTS * POKEMON_FEATURES * 2 + GLOBAL_FEATURES  # 471
    
    def __init__(self, deck_id_0: int = 0, deck_id_1: int = 1,
                 opponent_policy=None, randomize_decks: bool = True):
        super().__init__()
        self.action_space = spaces.Discrete(NUM_ACTIONS)
        self.observation_space = spaces.Box(
            low=-2, high=100, shape=(self.OBS_SIZE,), dtype=np.float32
        )
        self.deck_id_0 = deck_id_0
        self.deck_id_1 = deck_id_1
        self.randomize_decks = randomize_decks
        self.game = Game(deck_id_0, deck_id_1)
        self.agent_id = 0
        self.opponent_policy = opponent_policy
    
    def reset(self, seed=None, options=None):
        super().reset(seed=seed)
        
        if self.randomize_decks:
            decks = [0, 1, 2]
            d0 = self.np_random.choice(decks)
            d1 = self.np_random.choice(decks)
            self.game = Game(d0, d1)
        else:
            self.game = Game(self.deck_id_0, self.deck_id_1)
        
        self.game.reset()
        
        # Randomly assign agent
        self.agent_id = self.game.first_player
        
        # Play opponent turns if needed
        self._play_opponent_turns()
        
        return self._get_obs(), {}
    
    def step(self, action: int):
        if self.game.done:
            return self._get_obs(), 0.0, True, False, {}
        
        reward, done = self.game.step(action)
        
        if done:
            return self._get_obs(), self._final_reward(), True, False, {}
        
        self._play_opponent_turns()
        
        if self.game.done:
            return self._get_obs(), self._final_reward(), True, False, {}
        
        return self._get_obs(), reward, False, False, {}
    
    def _final_reward(self) -> float:
        if self.game.winner == self.agent_id:
            return 1.0
        elif self.game.winner is None:
            return 0.0
        else:
            return -1.0
    
    def _play_opponent_turns(self):
        max_actions = 50  # Safety limit per turn
        while not self.game.done and self.game.current_player != self.agent_id:
            for _ in range(max_actions):
                if self.game.done or self.game.current_player == self.agent_id:
                    break
                valid = self.game.get_valid_actions()
                if self.opponent_policy:
                    action = self.opponent_policy(self.game, 1 - self.agent_id)
                else:
                    action = self.np_random.choice(valid)
                self.game.step(action)
    
    def _encode_pokemon(self, p: PokemonInPlay | None,
                        opp_active_type: str = "",
                        my_hand: list | None = None) -> np.ndarray:
        """ポケモンを能力ベースの特徴ベクトルに変換（25次元）"""
        feat = np.zeros(self.POKEMON_FEATURES, dtype=np.float32)
        if p is None:
            return feat
        
        card = p.card
        # HP features (normalized)
        feat[0] = p.current_hp / 400.0
        feat[1] = card.hp / 400.0
        feat[2] = p.current_hp / max(card.hp, 1)  # hp_ratio
        
        # Type
        feat[3] = TYPE_MAP.get(card.types[0] if card.types else "", 0)
        
        # Stage / subtypes
        feat[4] = {"Basic": 0, "Stage 1": 1, "Stage 2": 2}.get(card.stage, 0)
        feat[5] = 1.0 if card.is_ex else 0.0
        feat[6] = 1.0 if card.is_tera else 0.0
        
        # Retreat cost
        feat[7] = p.effective_retreat_cost / 5.0
        
        # Energy
        feat[8] = p.total_energy() / 10.0
        counts = p.energy_count_by_type()
        feat[9] = counts.get("Fire", 0)
        feat[10] = counts.get("Water", 0)
        feat[11] = counts.get("Grass", 0)
        feat[12] = counts.get("Lightning", 0)
        feat[13] = counts.get("Fighting", 0)
        feat[14] = counts.get("Darkness", 0)
        
        # Attack features
        attacks = card.attacks
        if len(attacks) >= 1:
            feat[15] = attacks[0].damage / 300.0
            feat[16] = 0.0  # placeholder for attack2
            feat[17] = sum(attacks[0].cost.values())
            feat[18] = 0.0
            feat[19] = 1.0 if p.can_use_attack(attacks[0]) else 0.0
            feat[20] = 0.0
        if len(attacks) >= 2:
            feat[16] = attacks[1].damage / 300.0
            feat[18] = sum(attacks[1].cost.values())
            feat[20] = 1.0 if p.can_use_attack(attacks[1]) else 0.0
        
        # Ability & tool
        feat[21] = 1.0 if card.abilities else 0.0
        feat[22] = 1.0 if p.tool else 0.0
        
        # Weakness match (opponent's active type matches my weakness)
        feat[23] = 1.0 if (card.weakness and card.weakness == opp_active_type) else 0.0
        
        # Can evolve from hand
        feat[24] = 0.0
        if my_hand is not None:
            for c in my_hand:
                if isinstance(c, PokemonCard) and c.evolves_from == card.name:
                    feat[24] = 1.0
                    break
        
        return feat
    
    def _get_obs(self) -> np.ndarray:
        obs = np.zeros(self.OBS_SIZE, dtype=np.float32)
        me = self.game.players[self.agent_id]
        opp = self.game.players[1 - self.agent_id]
        
        # Derive opponent active type for weakness check
        opp_active_type = ""
        if opp.active and opp.active.card.types:
            opp_active_type = opp.active.card.types[0]
        my_active_type = ""
        if me.active and me.active.card.types:
            my_active_type = me.active.card.types[0]
        
        offset = 0
        
        # My pokemon
        obs[offset:offset+self.POKEMON_FEATURES] = self._encode_pokemon(
            me.active, opp_active_type, me.hand)
        offset += self.POKEMON_FEATURES
        for i in range(8):
            p = me.bench[i] if i < len(me.bench) else None
            obs[offset:offset+self.POKEMON_FEATURES] = self._encode_pokemon(
                p, opp_active_type, me.hand)
            offset += self.POKEMON_FEATURES
        
        # Opponent pokemon (no hand info for opponent)
        obs[offset:offset+self.POKEMON_FEATURES] = self._encode_pokemon(
            opp.active, my_active_type)
        offset += self.POKEMON_FEATURES
        for i in range(8):
            p = opp.bench[i] if i < len(opp.bench) else None
            obs[offset:offset+self.POKEMON_FEATURES] = self._encode_pokemon(
                p, my_active_type)
            offset += self.POKEMON_FEATURES
        
        # Global features (21)
        g = offset
        obs[g] = len(me.hand)
        obs[g+1] = sum(1 for c in me.hand if isinstance(c, PokemonCard))
        obs[g+2] = sum(1 for c in me.hand if isinstance(c, EnergyCard))
        obs[g+3] = sum(1 for c in me.hand if isinstance(c, TrainerCard))
        obs[g+4] = sum(1 for c in me.hand if isinstance(c, TrainerCard) and c.trainer_type == "Supporter")
        # Evolvable cards in hand: count pokemon in hand that can evolve something in play
        in_play_names = set()
        for p in me.get_all_pokemon_in_play():
            in_play_names.add(p.card.name)
        obs[g+5] = sum(1 for c in me.hand if isinstance(c, PokemonCard) and c.evolves_from in in_play_names)
        obs[g+6] = len(me.prizes)
        obs[g+7] = len(me.deck)
        obs[g+8] = 1.0 if me.supporter_played_this_turn else 0.0
        obs[g+9] = 1.0 if me.energy_attached_this_turn else 0.0
        obs[g+10] = len(opp.hand)
        obs[g+11] = len(opp.prizes)
        obs[g+12] = len(opp.deck)
        obs[g+13] = self.game.turn_count / 100.0
        obs[g+14] = 1.0 if self.game.stadium else 0.0
        obs[g+15] = 1.0 if self.game.has_attacked else 0.0
        obs[g+16] = 1.0 if self.game.turn_count <= 2 else 0.0
        obs[g+17] = (len(me.prizes) - len(opp.prizes)) / 6.0  # prize diff
        obs[g+18] = (me.max_bench - len(me.bench)) / 5.0  # bench free slots
        obs[g+19] = len(me.bench) / 5.0
        obs[g+20] = len(opp.bench) / 5.0
        
        return obs
    
    def action_masks(self) -> np.ndarray:
        mask = np.zeros(NUM_ACTIONS, dtype=bool)
        if not self.game.done and self.game.current_player == self.agent_id:
            for a in self.game.get_valid_actions():
                if 0 <= a < NUM_ACTIONS:
                    mask[a] = True
        else:
            from engine.actions import END_TURN
            mask[END_TURN] = True
        return mask
    
    def render(self):
        me = self.game.players[self.agent_id]
        opp = self.game.players[1 - self.agent_id]
        print(f"=== Turn {self.game.turn_count} | Player {self.game.current_player} ===")
        print(f"  My active: {me.active.card.name if me.active else 'None'}"
              f" HP={me.active.current_hp if me.active else 0}"
              f" Energy={me.active.total_energy() if me.active else 0}")
        print(f"  My bench: {[f'{p.card.name}({p.current_hp})' for p in me.bench]}")
        print(f"  My hand: {len(me.hand)} cards | Deck: {len(me.deck)} | Prizes: {len(me.prizes)}")
        print(f"  Opp active: {opp.active.card.name if opp.active else 'None'}"
              f" HP={opp.active.current_hp if opp.active else 0}")
        print(f"  Opp bench: {len(opp.bench)} | Hand: {len(opp.hand)} | Prizes: {len(opp.prizes)}")
        if self.game.stadium:
            print(f"  Stadium: {self.game.stadium.name}")
