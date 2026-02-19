"""アクション定義 - Phase 2: 拡張アクション空間

アクション空間の設計:
- 手札は最大20枚まで追跡 (MAX_HAND)
- ベンチは最大8体 (Area Zero Underdepths)
- 各アクションは固定オフセットで管理

アクションレイアウト:
  0-19:   PLAY_CARD_0..19     手札のカードをプレイ（たねポケモン→ベンチ、トレーナーズ使用）
  20-27:  EVOLVE_ACTIVE_0..7  手札iでアクティブを進化
  28-55:  EVOLVE_BENCH_0_0..  手札iでベンチjを進化 (手札8枠×ベンチ8枠は多すぎるので簡略化)
  56-63:  ENERGY_ACTIVE_0..7  手札iのエネルギーをアクティブに付ける
  64-127: ENERGY_BENCH_i_j    手札iのエネルギーをベンチjに (手札8×ベンチ8)
  128-129: ATTACK_0, ATTACK_1  技を使う
  130-137: RETREAT_0..7        ベンチjと入れ替え（にげる）
  138:    END_TURN            ターン終了
  
  --- Rare Candy系（簡略化: 場のポケモンに対してStage2を重ねる） ---
  139-146: RARE_CANDY_ACTIVE_0..7  手札iのStage2でアクティブにふしぎなアメ
  147-210: RARE_CANDY_BENCH_i_j    手札iのStage2でベンチjにふしぎなアメ (8×8)
  
  --- 能力使用 ---
  211:    USE_ABILITY_ACTIVE   アクティブの特性を使用
  212-219: USE_ABILITY_BENCH_0..7 ベンチjの特性を使用
  
  220:    PASS (何もしない、ゲーム内部用)

合計: 221アクション
"""
from __future__ import annotations
from .card import PokemonCard, TrainerCard, EnergyCard, PokemonInPlay

MAX_HAND = 20
MAX_BENCH = 8

# Action offsets
PLAY_CARD_BASE = 0           # 0-19
EVOLVE_ACTIVE_BASE = 20      # 20-27 (hand idx 0-7)
EVOLVE_BENCH_BASE = 28       # 28-91 (hand 0-7 × bench 0-7)
ENERGY_ACTIVE_BASE = 92      # 92-99
ENERGY_BENCH_BASE = 100      # 100-163 (hand 0-7 × bench 0-7)
ATTACK_BASE = 164            # 164-165
RETREAT_BASE = 166            # 166-173
END_TURN = 174
RARE_CANDY_ACTIVE_BASE = 175  # 175-182
RARE_CANDY_BENCH_BASE = 183   # 183-246
USE_ABILITY_ACTIVE = 247
USE_ABILITY_BENCH_BASE = 248  # 248-255

# 技コピー系サブアクション: 相手の技を1つ選んでコピー（Genome Hacking, メトロノーム等）
COPY_ATTACK_BASE = 256   # 256-257 (opponent's attack 0 or 1)

NUM_ACTIONS = 258


def _hand_idx_valid(hand_idx: int) -> bool:
    return 0 <= hand_idx < MAX_HAND


def get_valid_actions(player, opponent, game_state) -> list[int]:
    """有効なアクションリストを返す"""
    valid = []
    has_attacked = game_state.get("has_attacked", False)
    is_first_turn = game_state.get("is_first_turn", False)
    turn_count = game_state.get("turn_count", 1)
    stadium_in_play = game_state.get("stadium", None)
    
    # 技コピー系: 相手の技を選ぶサブアクション
    if game_state.get("pending_copy_attack", False):
        if opponent.active and opponent.active.card.attacks:
            for k, atk in enumerate(opponent.active.card.attacks):
                if k >= 2:
                    break
                # コピー技の無限ループ防止
                if atk.effect_id not in ("genome_hacking", "metronome", "copy_attack"):
                    valid.append(COPY_ATTACK_BASE + k)
        if not valid:
            valid.append(END_TURN)  # 相手に技がない場合
        return valid
    
    # 技を使った後はターン終了のみ
    if has_attacked:
        return [END_TURN]
    
    # アクティブがいない→ベンチからプロモート必須
    if player.active is None:
        if player.bench:
            for i in range(len(player.bench)):
                valid.append(RETREAT_BASE + i)  # Reuse retreat slot for promote
        if not valid:
            valid.append(END_TURN)
        return valid
    
    # === たねポケモンをベンチに出す (PLAY_CARD) ===
    if len(player.bench) < player.max_bench:
        for i, card in enumerate(player.hand):
            if i >= MAX_HAND:
                break
            if isinstance(card, PokemonCard) and card.is_basic:
                valid.append(PLAY_CARD_BASE + i)
    
    # === トレーナーズをプレイ ===
    for i, card in enumerate(player.hand):
        if i >= MAX_HAND:
            break
        if not isinstance(card, TrainerCard):
            continue
        if _can_play_trainer(player, opponent, card, i, game_state):
            valid.append(PLAY_CARD_BASE + i)
    
    # === 進化 (手札のポケモンで場のポケモンを進化) ===
    if not is_first_turn:
        for i, card in enumerate(player.hand):
            if i >= 8:
                break
            if not isinstance(card, PokemonCard):
                continue
            if card.stage not in ("Stage 1", "Stage 2"):
                continue
            # Check active
            if player.active and not player.active.played_this_turn and not player.active.evolved_this_turn:
                if card.evolves_from == player.active.card.name:
                    valid.append(EVOLVE_ACTIVE_BASE + i)
            # Check bench
            for j, bp in enumerate(player.bench):
                if j >= 8:
                    break
                if not bp.played_this_turn and not bp.evolved_this_turn:
                    if card.evolves_from == bp.card.name:
                        valid.append(EVOLVE_BENCH_BASE + i * 8 + j)
    
    # === Rare Candy ===
    if not is_first_turn and _has_rare_candy(player):
        for i, card in enumerate(player.hand):
            if i >= 8:
                break
            if not isinstance(card, PokemonCard) or card.stage != "Stage 2":
                continue
            # Check active (must be Basic, not played this turn)
            if player.active and player.active.card.is_basic and not player.active.played_this_turn:
                # Check if this Stage 2 can evolve from this Basic (via intermediate)
                if _rare_candy_compatible(player.active.card, card):
                    valid.append(RARE_CANDY_ACTIVE_BASE + i)
            # Check bench
            for j, bp in enumerate(player.bench):
                if j >= 8:
                    break
                if bp.card.is_basic and not bp.played_this_turn:
                    if _rare_candy_compatible(bp.card, card):
                        valid.append(RARE_CANDY_BENCH_BASE + i * 8 + j)
    
    # === エネルギーを付ける ===
    if not player.energy_attached_this_turn:
        for i, card in enumerate(player.hand):
            if i >= 8:
                break
            if not isinstance(card, EnergyCard):
                continue
            # Active
            if player.active:
                valid.append(ENERGY_ACTIVE_BASE + i)
            # Bench
            for j in range(min(len(player.bench), 8)):
                valid.append(ENERGY_BENCH_BASE + i * 8 + j)
    
    # === 技を使う ===
    if player.active and not player.active.cant_attack_next:
        # First turn going first: can't attack
        if not (is_first_turn and turn_count == 1):
            for k, attack in enumerate(player.active.card.attacks):
                if k >= 2:
                    break
                if player.active.can_use_attack(attack):
                    # Check attack-specific conditions
                    if attack.effect_id == "assault_landing" and stadium_in_play is None:
                        continue
                    if attack.effect_id == "unified_beatdown" and is_first_turn and turn_count <= 2:
                        continue  # going second, first turn
                    valid.append(ATTACK_BASE + k)
    
    # === にげる ===
    if player.active and len(player.bench) > 0 and not player.active.cant_retreat_next:
        if player.active.total_energy() >= player.active.effective_retreat_cost:
            for i in range(min(len(player.bench), 8)):
                valid.append(RETREAT_BASE + i)
    
    # === 特性を使う ===
    if player.active:
        for ab in player.active.card.abilities:
            if _can_use_ability(player, opponent, player.active, ab, game_state):
                valid.append(USE_ABILITY_ACTIVE)
                break
    for j, bp in enumerate(player.bench):
        if j >= 8:
            break
        for ab in bp.card.abilities:
            if _can_use_ability(player, opponent, bp, ab, game_state):
                valid.append(USE_ABILITY_BENCH_BASE + j)
                break
    
    # ターン終了は常に可能
    valid.append(END_TURN)
    return list(set(valid))


def _can_play_trainer(player, opponent, card: TrainerCard, hand_idx: int, game_state) -> bool:
    """トレーナーカードをプレイできるか"""
    if card.trainer_type == "Supporter":
        if player.supporter_played_this_turn:
            return False
    if card.trainer_type == "Stadium":
        if player.stadium_played_this_turn:
            return False
        # Can't play same stadium already in play
        if game_state.get("stadium") and game_state["stadium"].name == card.name:
            return False
    if card.trainer_type == "Pokemon Tool":
        # Need a pokemon without a tool
        if not any(p.tool is None for p in player.get_all_pokemon_in_play()):
            return False
    
    eid = card.effect_id
    
    # Specific conditions
    if eid == "boss_orders":
        return len(opponent.bench) > 0
    if eid == "briar":
        return opponent.prizes_taken == (opponent.PRIZE_COUNT - 2)  # opponent has exactly 2 prizes remaining
        # Actually: "your opponent has exactly 2 Prize cards remaining"
        # = len(opponent.prizes) == 2
        return len(opponent.prizes) == 2
    if eid == "acerola_mischief":
        return len(opponent.prizes) <= 2
    if eid == "counter_catcher":
        return len(player.prizes) > len(opponent.prizes) and len(opponent.bench) > 0
    if eid == "unfair_stamp":
        return player.pokemon_knocked_out_last_turn
    if eid == "ultra_ball":
        return len(player.hand) >= 3  # need to discard 2 other cards
    if eid == "earthen_vessel":
        return len(player.hand) >= 2  # need to discard 1 other card
    if eid == "sada_vitality":
        return player.has_ancient_in_play() and any(
            isinstance(c, EnergyCard) and not c.is_special for c in player.discard
        )
    if eid == "glass_trumpet":
        return player.has_tera_in_play()
    if eid == "night_stretcher":
        return any(isinstance(c, (PokemonCard, EnergyCard)) for c in player.discard)
    if eid == "energy_switch":
        # Need at least 2 pokemon with energy on one
        all_p = player.get_all_pokemon_in_play()
        return len(all_p) >= 2 and any(p.total_energy() > 0 for p in all_p)
    if eid == "prime_catcher":
        return len(opponent.bench) > 0 and len(player.bench) > 0
    if eid == "turo_scenario":
        return len(player.get_all_pokemon_in_play()) > 0
    if eid == "rare_candy":
        return False  # Handled separately via RARE_CANDY actions
    if eid == "tm_evolution_tool":
        return any(p.tool is None for p in player.get_all_pokemon_in_play())
    
    return True


def _can_use_ability(player, opponent, pokemon: PokemonInPlay, ability, game_state) -> bool:
    """特性を使えるか"""
    eid = ability.effect_id
    
    # Mischievous Lock check: if opponent's active Klefki is active, basic pokemon abilities blocked
    # (simplified - check if any active has mischievous_lock)
    for p_check in [player, opponent]:
        if p_check.active:
            for ab in p_check.active.card.abilities:
                if ab.effect_id == "mischievous_lock" and p_check.active is not pokemon:
                    if pokemon.card.is_basic:
                        return False
    
    if eid == "infernal_reign":
        return False  # Triggered on evolution, not manually
    if eid == "jewel_seeker":
        return False  # Triggered on evolution
    if eid == "flying_entry":
        return False  # Triggered on bench placement
    if eid == "transformative_start":
        return False  # Special: first turn only, handled elsewhere
    if eid == "teal_dance":
        # Once per turn, attach Grass energy from hand
        return any(isinstance(c, EnergyCard) and c.energy_type == "Grass" and not c.is_special
                   for c in player.hand)
    if eid == "fan_call":
        return not player.fan_call_used_this_turn and game_state.get("is_first_turn_of_game", False)
    if eid == "flip_the_script":
        return not player.flip_the_script_used_this_turn and player.pokemon_knocked_out_last_turn
    if eid == "quick_search":
        return not player.quick_search_used_this_turn and len(player.deck) > 0
    if eid == "run_errand":
        return (not player.run_errand_used_this_turn 
                and pokemon is player.active 
                and len(player.deck) > 0)
    if eid == "restart":
        return len(player.hand) < 3 and len(player.deck) > 0
    if eid == "cursed_blast":
        return True  # Can always use (KOs self)
    if eid == "adrena_brain":
        return any(not e.is_special and e.energy_type == "Darkness"
                   for e in pokemon.attached_energy) or any(
                       e.effect_id == "luminous_energy" for e in pokemon.attached_energy)
    if eid == "skyliner":
        return False  # Passive ability
    if eid == "damp":
        return False  # Passive ability
    if eid == "insomnia":
        return False  # Passive ability
    if eid == "agile":
        return False  # Passive ability
    if eid == "mischievous_lock":
        return False  # Passive ability
    if eid == "recon_directive":
        return False  # Triggered on evolution
    
    return False


def _has_rare_candy(player) -> bool:
    return any(isinstance(c, TrainerCard) and c.effect_id == "rare_candy" for c in player.hand)


def _rare_candy_compatible(basic: PokemonCard, stage2: PokemonCard) -> bool:
    """BasicとStage2がふしぎなアメで繋がるか（進化チェーンの簡易検証）"""
    # Known evolution chains
    CHAINS = {
        # Basic name → list of Stage 2 names that can evolve from it
        "Charmander": ["Charizard ex"],
        "Pidgey": ["Pidgeot ex"],
        "Duskull": ["Dusknoir"],
        "Dreepy": ["Dragapult ex"],
        "Hoothoot": [],  # Noctowl is Stage 1, not Stage 2
    }
    return stage2.name in CHAINS.get(basic.name, [])


def decode_action(action: int) -> dict:
    """アクションIDを人間可読な情報にデコード"""
    if PLAY_CARD_BASE <= action < PLAY_CARD_BASE + MAX_HAND:
        return {"type": "play_card", "hand_idx": action - PLAY_CARD_BASE}
    if EVOLVE_ACTIVE_BASE <= action < EVOLVE_ACTIVE_BASE + 8:
        return {"type": "evolve_active", "hand_idx": action - EVOLVE_ACTIVE_BASE}
    if EVOLVE_BENCH_BASE <= action < EVOLVE_BENCH_BASE + 64:
        off = action - EVOLVE_BENCH_BASE
        return {"type": "evolve_bench", "hand_idx": off // 8, "bench_idx": off % 8}
    if ENERGY_ACTIVE_BASE <= action < ENERGY_ACTIVE_BASE + 8:
        return {"type": "energy_active", "hand_idx": action - ENERGY_ACTIVE_BASE}
    if ENERGY_BENCH_BASE <= action < ENERGY_BENCH_BASE + 64:
        off = action - ENERGY_BENCH_BASE
        return {"type": "energy_bench", "hand_idx": off // 8, "bench_idx": off % 8}
    if ATTACK_BASE <= action < ATTACK_BASE + 2:
        return {"type": "attack", "attack_idx": action - ATTACK_BASE}
    if RETREAT_BASE <= action < RETREAT_BASE + 8:
        return {"type": "retreat", "bench_idx": action - RETREAT_BASE}
    if action == END_TURN:
        return {"type": "end_turn"}
    if RARE_CANDY_ACTIVE_BASE <= action < RARE_CANDY_ACTIVE_BASE + 8:
        return {"type": "rare_candy_active", "hand_idx": action - RARE_CANDY_ACTIVE_BASE}
    if RARE_CANDY_BENCH_BASE <= action < RARE_CANDY_BENCH_BASE + 64:
        off = action - RARE_CANDY_BENCH_BASE
        return {"type": "rare_candy_bench", "hand_idx": off // 8, "bench_idx": off % 8}
    if action == USE_ABILITY_ACTIVE:
        return {"type": "use_ability", "target": "active"}
    if USE_ABILITY_BENCH_BASE <= action < USE_ABILITY_BENCH_BASE + 8:
        return {"type": "use_ability", "target": "bench", "bench_idx": action - USE_ABILITY_BENCH_BASE}
    if COPY_ATTACK_BASE <= action < COPY_ATTACK_BASE + 2:
        return {"type": "copy_attack", "attack_idx": action - COPY_ATTACK_BASE}
    return {"type": "unknown", "action": action}
