"""エキスパートデータ生成 - ルールベースポリシーでお手本データを作る"""
from __future__ import annotations
import sys, os, json, random, time
import numpy as np
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.game import Game
from engine.card import PokemonCard, TrainerCard, EnergyCard, PokemonInPlay
from engine.actions import (
    decode_action, get_valid_actions, NUM_ACTIONS,
    PLAY_CARD_BASE, MAX_HAND, EVOLVE_ACTIVE_BASE, EVOLVE_BENCH_BASE,
    ENERGY_ACTIVE_BASE, ENERGY_BENCH_BASE, ATTACK_BASE, RETREAT_BASE,
    END_TURN, RARE_CANDY_ACTIVE_BASE, RARE_CANDY_BENCH_BASE,
    USE_ABILITY_ACTIVE, USE_ABILITY_BENCH_BASE,
)
from engine.text_state import format_game_state, format_valid_actions
from env.ptcg_env import PTCGEnv


# =====================================================
# Rule-Based Expert Policy
# =====================================================

def _attack_actions(valid: list[int]) -> list[int]:
    return [a for a in valid if ATTACK_BASE <= a < ATTACK_BASE + 2]

def _evolve_actions(valid: list[int]) -> list[int]:
    return [a for a in valid if EVOLVE_ACTIVE_BASE <= a < EVOLVE_BENCH_BASE + 64]

def _rare_candy_actions(valid: list[int]) -> list[int]:
    return [a for a in valid if RARE_CANDY_ACTIVE_BASE <= a < RARE_CANDY_BENCH_BASE + 64]

def _ability_actions(valid: list[int]) -> list[int]:
    return [a for a in valid if a == USE_ABILITY_ACTIVE or USE_ABILITY_BENCH_BASE <= a < USE_ABILITY_BENCH_BASE + 8]

def _play_card_actions(valid: list[int]) -> list[int]:
    return [a for a in valid if PLAY_CARD_BASE <= a < PLAY_CARD_BASE + MAX_HAND]

def _energy_actions(valid: list[int]) -> list[int]:
    return [a for a in valid if ENERGY_ACTIVE_BASE <= a < ENERGY_BENCH_BASE + 64]

def _retreat_actions(valid: list[int]) -> list[int]:
    return [a for a in valid if RETREAT_BASE <= a < RETREAT_BASE + 8]


def rule_based_expert(game: Game, player_id: int) -> int:
    """
    ルールベースエキスパートポリシー。
    優先度:
    1. 特性を使う（リソース獲得系）
    2. 進化する（Stage2 > Stage1、ふしぎなアメ優先）
    3. サポーターを使う（ドローサポ優先）
    4. グッズを使う（ベンチ展開系優先）
    5. エネルギーをメインアタッカーに付ける
    6. 技を使う（高ダメージ優先）
    7. にげる（攻撃できない場合のみ）
    8. ターン終了
    """
    player = game.players[player_id]
    opponent = game.players[1 - player_id]
    valid = game.get_valid_actions()
    
    if len(valid) == 1:
        return valid[0]
    
    # After attack, must end turn
    if valid == [END_TURN]:
        return END_TURN
    
    # === Promote if no active ===
    if player.active is None:
        retreats = _retreat_actions(valid)
        if retreats:
            # Pick the strongest bench pokemon
            best = retreats[0]
            best_score = -1
            for a in retreats:
                bi = decode_action(a)["bench_idx"]
                if bi < len(player.bench):
                    bp = player.bench[bi]
                    score = bp.current_hp + (100 if bp.card.stage != "Basic" else 0)
                    if score > best_score:
                        best_score = score
                        best = a
            return best
        return valid[0]
    
    # === 1. Use abilities (resource-gaining ones) ===
    abilities = _ability_actions(valid)
    if abilities:
        return abilities[0]
    
    # === 2. Rare Candy (highest priority evolution) ===
    rc = _rare_candy_actions(valid)
    if rc:
        return rc[0]
    
    # === 3. Evolve (Stage2 > Stage1) ===
    evos = _evolve_actions(valid)
    if evos:
        # Prefer Stage2 evolutions, then active over bench
        best = evos[0]
        best_score = 0
        for a in evos:
            info = decode_action(a)
            hi = info["hand_idx"]
            if hi < len(player.hand):
                card = player.hand[hi]
                if isinstance(card, PokemonCard):
                    score = 2 if card.stage == "Stage 2" else 1
                    if info["type"] == "evolve_active":
                        score += 0.5  # Prefer evolving active
                    if score > best_score:
                        best_score = score
                        best = a
        return best
    
    # === 4. Supporters (draw support first) ===
    play_cards = _play_card_actions(valid)
    supporters = []
    items = []
    basics_to_bench = []
    
    for a in play_cards:
        hi = a - PLAY_CARD_BASE
        if hi < len(player.hand):
            card = player.hand[hi]
            if isinstance(card, TrainerCard):
                if card.trainer_type == "Supporter":
                    supporters.append((a, card))
                elif card.trainer_type == "Item":
                    items.append((a, card))
                elif card.trainer_type == "Stadium":
                    items.append((a, card))  # Treat stadium like item priority
                elif card.trainer_type == "Pokemon Tool":
                    items.append((a, card))
            elif isinstance(card, PokemonCard) and card.is_basic:
                basics_to_bench.append((a, card))
    
    # Play supporter (priority: draw > search > disruption)
    if supporters and not player.supporter_played_this_turn:
        DRAW_SUPPORTERS = {"dawn", "lillies_determination", "crispin", "sada_vitality"}
        DISRUPT_SUPPORTERS = {"boss_orders", "iono", "acerola_mischief"}
        
        # Prefer draw supporters
        for a, card in supporters:
            if card.effect_id in DRAW_SUPPORTERS:
                return a
        # Then disruption (Boss's Orders when can KO)
        for a, card in supporters:
            if card.effect_id == "boss_orders" and opponent.bench:
                # Use Boss if we can KO something on bench
                if player.active and player.active.card.attacks:
                    for atk in player.active.card.attacks:
                        if player.active.can_use_attack(atk) and atk.damage > 0:
                            # Check if any bench pokemon can be KO'd
                            for bp in opponent.bench:
                                if bp.current_hp <= atk.damage:
                                    return a
                            # Or KO a low HP pokemon
                            for bp in opponent.bench:
                                if bp.current_hp <= atk.damage * 2:  # with weakness
                                    return a
        # Play Iono if opponent has many cards
        for a, card in supporters:
            if card.effect_id == "iono" and len(opponent.hand) >= 5:
                return a
        # Use any remaining supporter
        if supporters:
            return supporters[0][0]
    
    # === 5. Items (bench expansion first) ===
    BENCH_ITEMS = {"buddy_buddy_poffin", "nest_ball"}
    SEARCH_ITEMS = {"ultra_ball", "earthen_vessel", "night_stretcher", "super_rod"}
    
    for a, card in items:
        if card.effect_id in BENCH_ITEMS and len(player.bench) < player.max_bench:
            return a
    
    for a, card in items:
        if card.effect_id in SEARCH_ITEMS:
            return a
    
    # Other items (counter catcher, unfair stamp, etc.)
    for a, card in items:
        if card.effect_id not in BENCH_ITEMS:
            return a
    
    # === 6. Play basic pokemon to bench ===
    if basics_to_bench and len(player.bench) < player.max_bench:
        return basics_to_bench[0][0]
    
    # === 7. Attach energy to main attacker ===
    energy_acts = _energy_actions(valid)
    if energy_acts:
        # Prefer attaching to active evolved pokemon, then active, then bench attackers
        active_energy = [a for a in energy_acts if ENERGY_ACTIVE_BASE <= a < ENERGY_ACTIVE_BASE + 8]
        bench_energy = [a for a in energy_acts if ENERGY_BENCH_BASE <= a < ENERGY_BENCH_BASE + 64]
        
        if active_energy and player.active:
            # Attach to active if it's an attacker (has attacks with damage)
            if player.active.card.attacks and any(atk.damage > 0 for atk in player.active.card.attacks):
                return active_energy[0]
        
        # Attach to bench pokemon that needs energy for attacks
        for a in bench_energy:
            info = decode_action(a)
            bi = info["bench_idx"]
            if bi < len(player.bench):
                bp = player.bench[bi]
                if bp.card.attacks and bp.card.stage != "Basic":
                    # Prefer evolved pokemon that can benefit from energy
                    return a
        
        # Default: attach to active
        if active_energy:
            return active_energy[0]
        if bench_energy:
            return bench_energy[0]
    
    # === 8. Attack (highest damage first) ===
    attacks = _attack_actions(valid)
    if attacks:
        best = attacks[0]
        best_dmg = 0
        for a in attacks:
            ai = a - ATTACK_BASE
            if player.active and ai < len(player.active.card.attacks):
                atk = player.active.card.attacks[ai]
                dmg = atk.damage
                # Bonus for special effects
                if atk.effect_id == "burning_darkness":
                    dmg = 180 + 30 * opponent.prizes_taken
                if dmg > best_dmg:
                    best_dmg = dmg
                    best = a
        return best
    
    # === 9. Retreat if active can't attack and bench can ===
    retreats = _retreat_actions(valid)
    if retreats and player.active:
        can_attack = any(player.active.can_use_attack(atk) for atk in player.active.card.attacks)
        if not can_attack:
            # Find bench pokemon that can attack
            for a in retreats:
                bi = decode_action(a)["bench_idx"]
                if bi < len(player.bench):
                    bp = player.bench[bi]
                    if any(bp.can_use_attack(atk) for atk in bp.card.attacks):
                        return a
    
    # === 10. End turn ===
    return END_TURN


# =====================================================
# Data Generation
# =====================================================

def generate_expert_games(n_games: int = 1000, output_dir: str = "data/expert_games",
                          save_text: bool = False, verbose: bool = False) -> dict:
    """
    ルールベースエキスパートでゲームをプレイし、(obs, action, valid_mask)を保存。
    両プレイヤーともエキスパートポリシーを使用。
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    all_samples = []
    stats = {"wins": [0, 0], "draws": 0, "total_turns": 0, "total_samples": 0, "errors": 0}
    
    env = PTCGEnv(randomize_decks=True)
    
    t0 = time.time()
    
    for game_idx in range(n_games):
        try:
            obs, _ = env.reset()
            done = False
            game_samples = []
            text_log = []
            steps = 0
            
            while not done and steps < 5000:
                mask = env.action_masks()
                valid = np.where(mask)[0].tolist()
                
                if not valid:
                    break
                
                # Expert chooses action
                action = rule_based_expert(env.game, env.agent_id)
                
                # Validate action
                if action not in valid:
                    action = valid[0]
                
                # Record sample
                sample = {
                    "obs": obs.tolist(),
                    "action": int(action),
                    "valid_mask": mask.tolist(),
                }
                game_samples.append(sample)
                
                if save_text and steps < 200:
                    text_log.append(format_game_state(env.game, env.agent_id))
                    text_log.append(format_valid_actions(env.game, env.agent_id))
                    text_log.append(f"→ 選択: [{action}]")
                    text_log.append("")
                
                obs, reward, done, truncated, info = env.step(action)
                steps += 1
            
            all_samples.extend(game_samples)
            
            winner = env.game.winner
            if winner == env.agent_id:
                stats["wins"][0] += 1
            elif winner is not None:
                stats["wins"][1] += 1
            else:
                stats["draws"] += 1
            stats["total_turns"] += env.game.turn_count
            stats["total_samples"] += len(game_samples)
            
            if save_text and game_idx < 5:
                text_path = output_path / f"game_{game_idx:04d}.txt"
                with open(text_path, "w") as f:
                    f.write("\n".join(text_log))
            
            if verbose and (game_idx + 1) % 100 == 0:
                elapsed = time.time() - t0
                print(f"  Game {game_idx+1}/{n_games} | "
                      f"Samples: {len(all_samples)} | "
                      f"Time: {elapsed:.1f}s")
        
        except Exception as e:
            stats["errors"] += 1
            if stats["errors"] <= 5:
                print(f"Error in game {game_idx}: {e}")
    
    elapsed = time.time() - t0
    
    # Save as JSONL (one sample per line, more memory efficient)
    data_path = output_path / "expert_data.jsonl"
    with open(data_path, "w") as f:
        for s in all_samples:
            f.write(json.dumps(s) + "\n")
    
    # Also save as numpy arrays for fast loading
    obs_array = np.array([s["obs"] for s in all_samples], dtype=np.float32)
    action_array = np.array([s["action"] for s in all_samples], dtype=np.int64)
    mask_array = np.array([s["valid_mask"] for s in all_samples], dtype=bool)
    
    np.savez_compressed(
        output_path / "expert_data.npz",
        obs=obs_array,
        actions=action_array,
        masks=mask_array,
    )
    
    stats["elapsed"] = elapsed
    stats["avg_turns"] = stats["total_turns"] / max(n_games - stats["errors"], 1)
    stats["avg_samples_per_game"] = stats["total_samples"] / max(n_games - stats["errors"], 1)
    
    with open(output_path / "stats.json", "w") as f:
        json.dump(stats, f, indent=2)
    
    return stats


def evaluate_expert_vs_random(n_games: int = 200) -> float:
    """ルールベースエキスパート vs ランダムの勝率を計測"""
    env = PTCGEnv(randomize_decks=True)
    wins = 0
    
    for _ in range(n_games):
        try:
            obs, _ = env.reset()
            done = False
            steps = 0
            while not done and steps < 5000:
                mask = env.action_masks()
                valid = np.where(mask)[0].tolist()
                if not valid:
                    break
                action = rule_based_expert(env.game, env.agent_id)
                if action not in valid:
                    action = valid[0]
                obs, reward, done, truncated, info = env.step(action)
                steps += 1
            if env.game.winner == env.agent_id:
                wins += 1
        except Exception:
            pass
    
    return wins / n_games


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--games", type=int, default=1000)
    parser.add_argument("--output", default="data/expert_games")
    parser.add_argument("--text", action="store_true", help="Save text logs for first 5 games")
    parser.add_argument("--eval", action="store_true", help="Evaluate expert vs random")
    parser.add_argument("--eval-games", type=int, default=200)
    args = parser.parse_args()
    
    if args.eval:
        print("Evaluating rule-based expert vs random...")
        wr = evaluate_expert_vs_random(args.eval_games)
        print(f"Expert vs Random ({args.eval_games} games): {wr*100:.1f}% win rate")
    
    print(f"\nGenerating expert data ({args.games} games)...")
    stats = generate_expert_games(
        n_games=args.games,
        output_dir=args.output,
        save_text=args.text,
        verbose=True,
    )
    
    print(f"\n=== Generation Complete ===")
    print(f"Total samples: {stats['total_samples']}")
    print(f"Avg samples/game: {stats['avg_samples_per_game']:.1f}")
    print(f"Avg turns/game: {stats['avg_turns']:.1f}")
    print(f"Expert wins: {stats['wins'][0]}, Opponent wins: {stats['wins'][1]}, Draws: {stats['draws']}")
    print(f"Errors: {stats['errors']}")
    print(f"Time: {stats['elapsed']:.1f}s")
    print(f"Data saved to: {args.output}/")
