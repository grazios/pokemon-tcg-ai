"""ゲームエンジン - ポケカTCGのコアロジック"""
from __future__ import annotations
import random
from .card import PokemonCard, EnergyCard, PokemonInPlay, load_card_db, build_deck
from .player import Player
from .actions import ActionType, get_valid_actions, NUM_ACTIONS


class Game:
    """ポケカTCGゲーム（2プレイヤー）"""
    
    MAX_TURNS = 100  # 無限ループ防止
    PRIZE_TARGET = 4  # ミニデッキなので4枚
    
    def __init__(self, card_db: dict | None = None):
        if card_db is None:
            card_db = load_card_db()
        self.card_db = card_db
        self.players: list[Player] = []
        self.current_player: int = 0  # 0 or 1
        self.turn_count: int = 0
        self.done: bool = False
        self.winner: int | None = None  # 0, 1, or None(draw)
        self.has_attacked: bool = False
        self._setup_phase: bool = True
    
    def reset(self):
        """ゲームをリセット"""
        deck0 = build_deck(self.card_db)
        deck1 = build_deck(self.card_db)
        self.players = [Player(deck0, 0), Player(deck1, 1)]
        self.current_player = 0
        self.turn_count = 0
        self.done = False
        self.winner = None
        self.has_attacked = False
        
        # 初期セットアップ
        for p in self.players:
            p.setup()
        
        # 各プレイヤーのアクティブポケモンを自動設定
        self._setup_phase = True
        for p in self.players:
            pokemon_indices = p.get_pokemon_in_hand()
            if pokemon_indices:
                p.place_active(pokemon_indices[0])
        self._setup_phase = False
        
        # 先攻プレイヤーはドローしない（ルール通り）
        self.turn_count = 1
    
    def get_current_player(self) -> Player:
        return self.players[self.current_player]
    
    def get_opponent(self) -> Player:
        return self.players[1 - self.current_player]
    
    def get_valid_actions(self) -> list[int]:
        return get_valid_actions(self.get_current_player(), self.has_attacked)
    
    def step(self, action: int) -> tuple[float, bool]:
        """
        アクションを実行。
        Returns: (reward, done) - 現在のプレイヤー視点のreward
        """
        if self.done:
            return 0.0, True
        
        player = self.get_current_player()
        opponent = self.get_opponent()
        reward = 0.0
        
        valid = self.get_valid_actions()
        if action not in valid:
            # 無効なアクション→ターン終了扱い
            action = ActionType.END_TURN
        
        if ActionType.BENCH_POKEMON_0 <= action <= ActionType.BENCH_POKEMON_6:
            hand_idx = action - ActionType.BENCH_POKEMON_0
            if player.active is None:
                player.place_active(hand_idx)
            else:
                player.place_bench(hand_idx)
        
        elif ActionType.ENERGY_ACTIVE_0 <= action <= ActionType.ENERGY_ACTIVE_6:
            hand_idx = action - ActionType.ENERGY_ACTIVE_0
            player.attach_energy(hand_idx, "active")
        
        elif action in (ActionType.ATTACK_0, ActionType.ATTACK_1):
            attack_idx = action - ActionType.ATTACK_0
            if player.active and attack_idx < len(player.active.card.attacks):
                attack = player.active.card.attacks[attack_idx]
                if opponent.active:
                    ko = opponent.active.take_damage(attack.damage, player.active.card.type)
                    if ko:
                        # きぜつ処理
                        opponent.discard.append(opponent.active.card)
                        opponent.active = None
                        player.take_prize()
                        reward += 0.1  # サイド取得報酬
                        
                        # 勝利チェック: サイド全取り
                        if player.prizes_taken >= self.PRIZE_TARGET:
                            self.done = True
                            self.winner = self.current_player
                            reward = 1.0
                            return reward, True
                        
                        # 相手がベンチからポケモンを出す（自動: 先頭）
                        if opponent.bench:
                            opponent.active = opponent.bench.pop(0)
                        else:
                            # 相手にポケモンがいない→勝利
                            self.done = True
                            self.winner = self.current_player
                            reward = 1.0
                            return reward, True
                
                self.has_attacked = True
        
        elif ActionType.RETREAT_0 <= action <= ActionType.RETREAT_4:
            bench_idx = action - ActionType.RETREAT_0
            player.retreat(bench_idx)
        
        elif action == ActionType.END_TURN:
            self._end_turn()
        
        return reward, self.done
    
    def _end_turn(self):
        """ターン終了処理"""
        player = self.get_current_player()
        player.energy_attached_this_turn = False
        self.has_attacked = False
        
        # プレイヤー交代
        self.current_player = 1 - self.current_player
        self.turn_count += 1
        
        # ターン上限チェック
        if self.turn_count > self.MAX_TURNS:
            self.done = True
            # サイド取得数で判定
            if self.players[0].prizes_taken > self.players[1].prizes_taken:
                self.winner = 0
            elif self.players[1].prizes_taken > self.players[0].prizes_taken:
                self.winner = 1
            else:
                self.winner = None  # 引き分け
            return
        
        # 新しいプレイヤーのドロー
        new_player = self.get_current_player()
        if not new_player.draw(1):
            # 山札切れ→負け
            self.done = True
            self.winner = 1 - self.current_player
            return
    
    def get_observation(self, player_id: int) -> dict:
        """観測情報を返す（player_id視点）"""
        me = self.players[player_id]
        opp = self.players[1 - player_id]
        
        return {
            "my_hand_size": len(me.hand),
            "my_hand_pokemon": len(me.get_pokemon_in_hand()),
            "my_hand_energy": len(me.get_energy_in_hand()),
            "my_active": self._pokemon_obs(me.active),
            "my_bench": [self._pokemon_obs(p) for p in me.bench],
            "my_prizes_remaining": len(me.prizes),
            "my_deck_size": len(me.deck),
            "opp_active": self._pokemon_obs(opp.active),
            "opp_bench_count": len(opp.bench),
            "opp_prizes_remaining": len(opp.prizes),
            "opp_hand_size": len(opp.hand),
            "opp_deck_size": len(opp.deck),
            "is_my_turn": self.current_player == player_id,
        }
    
    def _pokemon_obs(self, p: PokemonInPlay | None) -> dict | None:
        if p is None:
            return None
        return {
            "name": p.card.name,
            "hp": p.current_hp,
            "max_hp": p.card.hp,
            "type": p.card.type,
            "energy": dict(p.attached_energy),
            "total_energy": p.total_energy(),
        }
