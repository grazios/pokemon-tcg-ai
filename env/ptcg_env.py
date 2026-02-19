"""Gymnasium環境 - ポケカTCGシミュレーター"""
from __future__ import annotations
import numpy as np
import gymnasium as gym
from gymnasium import spaces
from engine.game import Game
from engine.actions import NUM_ACTIONS, get_valid_actions
from engine.card import PokemonInPlay


# タイプのエンコーディング
TYPE_MAP = {"Fire": 0, "Water": 1, "Lightning": 2, "Psychic": 3, "": 4}


class PTCGEnv(gym.Env):
    """
    ポケカTCG Gymnasium環境
    
    2プレイヤーゲーム。player 0の視点で学習。
    対戦相手はランダムポリシーまたは別のエージェント。
    """
    metadata = {"render_modes": ["human"]}
    
    # 観測空間のサイズ
    # [my_hand_size, my_hand_pokemon, my_hand_energy, 
    #  my_active_hp, my_active_max_hp, my_active_type, my_active_energy,
    #  my_bench_count,
    #  my_bench_0_hp ... my_bench_4_hp (5),
    #  my_prizes_remaining, my_deck_size,
    #  opp_active_hp, opp_active_max_hp, opp_active_type, opp_active_energy,
    #  opp_bench_count, opp_prizes_remaining, opp_hand_size, opp_deck_size,
    #  is_my_turn, has_attacked, energy_attached]
    OBS_SIZE = 28
    
    def __init__(self, opponent_policy=None):
        super().__init__()
        self.action_space = spaces.Discrete(NUM_ACTIONS)
        self.observation_space = spaces.Box(
            low=0, high=200, shape=(self.OBS_SIZE,), dtype=np.float32
        )
        self.game = Game()
        self.agent_id = 0  # 学習エージェントはplayer 0
        self.opponent_policy = opponent_policy  # None=ランダム
    
    def reset(self, seed=None, options=None):
        super().reset(seed=seed)
        self.game.reset()
        # 相手のターンなら自動プレイ
        self._play_opponent_turns()
        obs = self._get_obs()
        return obs, {}
    
    def step(self, action: int):
        if self.game.done:
            return self._get_obs(), 0.0, True, False, {}
        
        # エージェントのアクション実行
        reward, done = self.game.step(action)
        
        if done:
            final_reward = 1.0 if self.game.winner == self.agent_id else -1.0
            if self.game.winner is None:
                final_reward = 0.0
            return self._get_obs(), final_reward, True, False, {}
        
        # 相手のターンを自動プレイ
        opp_reward = self._play_opponent_turns()
        
        # 相手のアクションでゲーム終了した場合
        if self.game.done:
            final_reward = 1.0 if self.game.winner == self.agent_id else -1.0
            if self.game.winner is None:
                final_reward = 0.0
            return self._get_obs(), final_reward, True, False, {}
        
        return self._get_obs(), reward, False, False, {}
    
    def _play_opponent_turns(self):
        """相手のターンを自動プレイ"""
        total_reward = 0.0
        while not self.game.done and self.game.current_player != self.agent_id:
            valid = self.game.get_valid_actions()
            if self.opponent_policy:
                action = self.opponent_policy(self.game, 1 - self.agent_id)
            else:
                action = self.np_random.choice(valid)
            reward, done = self.game.step(action)
            total_reward -= reward  # 相手の報酬はこちらのマイナス
        return total_reward
    
    def _get_obs(self) -> np.ndarray:
        """観測ベクトルを構築"""
        obs = np.zeros(self.OBS_SIZE, dtype=np.float32)
        me = self.game.players[self.agent_id]
        opp = self.game.players[1 - self.agent_id]
        
        obs[0] = len(me.hand)
        obs[1] = len(me.get_pokemon_in_hand())
        obs[2] = len(me.get_energy_in_hand())
        
        if me.active:
            obs[3] = me.active.current_hp
            obs[4] = me.active.card.hp
            obs[5] = TYPE_MAP.get(me.active.card.type, 4)
            obs[6] = me.active.total_energy()
        
        obs[7] = len(me.bench)
        for i, bp in enumerate(me.bench[:5]):
            obs[8 + i] = bp.current_hp
        
        obs[13] = len(me.prizes)
        obs[14] = len(me.deck)
        
        if opp.active:
            obs[15] = opp.active.current_hp
            obs[16] = opp.active.card.hp
            obs[17] = TYPE_MAP.get(opp.active.card.type, 4)
            obs[18] = opp.active.total_energy()
        
        obs[19] = len(opp.bench)
        obs[20] = len(opp.prizes)
        obs[21] = len(opp.hand)
        obs[22] = len(opp.deck)
        
        obs[23] = 1.0 if self.game.current_player == self.agent_id else 0.0
        obs[24] = 1.0 if self.game.has_attacked else 0.0
        obs[25] = 1.0 if me.energy_attached_this_turn else 0.0
        
        # 使える技の数
        if me.active:
            usable = sum(1 for a in me.active.card.attacks if me.active.can_use_attack(a))
            obs[26] = usable
        
        obs[27] = self.game.turn_count
        
        return obs
    
    def action_masks(self) -> np.ndarray:
        """有効なアクションのマスク（MaskablePPO用）"""
        mask = np.zeros(NUM_ACTIONS, dtype=bool)
        if not self.game.done and self.game.current_player == self.agent_id:
            for a in self.game.get_valid_actions():
                mask[a] = True
        else:
            mask[NUM_ACTIONS - 1] = True  # END_TURN
        return mask
    
    def render(self):
        obs = self.game.get_observation(self.agent_id)
        print(f"Turn {self.game.turn_count} | Player {self.game.current_player}'s turn")
        print(f"  My active: {obs['my_active']}")
        print(f"  My bench: {len(obs['my_bench'])} pokemon")
        print(f"  My hand: {obs['my_hand_size']} cards")
        print(f"  Opp active: {obs['opp_active']}")
        print(f"  Prizes: me={obs['my_prizes_remaining']} opp={obs['opp_prizes_remaining']}")
