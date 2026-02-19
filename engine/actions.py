"""アクション定義 - Gymnasium環境用の離散アクション空間"""
from __future__ import annotations
from enum import IntEnum

# アクションタイプ
class ActionType(IntEnum):
    # ポケモンをベンチに出す (手札index 0-6 → 7アクション)
    BENCH_POKEMON_0 = 0
    BENCH_POKEMON_1 = 1
    BENCH_POKEMON_2 = 2
    BENCH_POKEMON_3 = 3
    BENCH_POKEMON_4 = 4
    BENCH_POKEMON_5 = 5
    BENCH_POKEMON_6 = 6
    # エネルギーをアクティブに付ける (手札index 0-6 → 7アクション)
    ENERGY_ACTIVE_0 = 7
    ENERGY_ACTIVE_1 = 8
    ENERGY_ACTIVE_2 = 9
    ENERGY_ACTIVE_3 = 10
    ENERGY_ACTIVE_4 = 11
    ENERGY_ACTIVE_5 = 12
    ENERGY_ACTIVE_6 = 13
    # 技を使う (技index 0-1 → 2アクション)
    ATTACK_0 = 14
    ATTACK_1 = 15
    # にげる (ベンチindex 0-4 → 5アクション)
    RETREAT_0 = 16
    RETREAT_1 = 17
    RETREAT_2 = 18
    RETREAT_3 = 19
    RETREAT_4 = 20
    # ターン終了
    END_TURN = 21

NUM_ACTIONS = 22


def get_valid_actions(player, has_attacked: bool) -> list[int]:
    """現在のプレイヤーの有効なアクションリストを返す"""
    valid = []
    
    # 技を使った後はターン終了のみ
    if has_attacked:
        return [ActionType.END_TURN]
    
    # ベンチにポケモンを出す
    if len(player.bench) < 5 and player.active is not None:
        for i in player.get_pokemon_in_hand():
            if i < 7:
                valid.append(ActionType.BENCH_POKEMON_0 + i)
    
    # アクティブがいない場合はポケモンを出すのみ
    if player.active is None:
        for i in player.get_pokemon_in_hand():
            if i < 7:
                valid.append(ActionType.BENCH_POKEMON_0 + i)  # 特別扱い: activeに出す
        if not valid:
            valid.append(ActionType.END_TURN)
        return valid
    
    # エネルギーをアクティブに付ける
    if not player.energy_attached_this_turn:
        for i in player.get_energy_in_hand():
            if i < 7:
                valid.append(ActionType.ENERGY_ACTIVE_0 + i)
    
    # 技を使う
    if player.active:
        for j, attack in enumerate(player.active.card.attacks):
            if j < 2 and player.active.can_use_attack(attack):
                valid.append(ActionType.ATTACK_0 + j)
    
    # にげる
    if player.active and len(player.bench) > 0:
        if player.active.total_energy() >= player.active.card.retreat_cost:
            for i in range(min(len(player.bench), 5)):
                valid.append(ActionType.RETREAT_0 + i)
    
    # ターン終了は常に可能
    valid.append(ActionType.END_TURN)
    
    return valid
