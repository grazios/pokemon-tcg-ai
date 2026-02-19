"""Auto-play script using strategic heuristics for expert data generation."""
import sys
import os
import json
import random
import re
import numpy as np
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.game import Game
from engine.card_db import DECK_NAMES
from engine.actions import NUM_ACTIONS, decode_action
from engine.text_state import format_game_state, format_valid_actions, format_action
from env.ptcg_env import PTCGEnv


def get_obs(env, game, player_id):
    original_agent = env.agent_id
    env.agent_id = player_id
    obs = env._get_obs()
    env.agent_id = original_agent
    return obs


def categorize_action(action_id, me, opp, game):
    """Categorize an action for priority-based selection."""
    desc = format_action(action_id, me, opp, game)
    desc_lower = desc.lower()
    
    # Priority categories (lower = higher priority)
    # 1. Use abilities (free)
    if '特性' in desc:
        return (1, desc)
    # 2. Evolution (Rare Candy for Stage 2 ex highest)
    if 'ふしぎなアメ' in desc or 'rare candy' in desc_lower:
        return (2, desc)
    if '進化' in desc:
        return (3, desc)
    # 3. Item search cards
    if 'poffin' in desc_lower or 'buddy-buddy' in desc_lower:
        return (4, desc)
    if 'nest ball' in desc_lower:
        return (5, desc)
    if 'ultra ball' in desc_lower:
        return (6, desc)
    if 'earthen vessel' in desc_lower:
        return (7, desc)
    # Items (other)
    if '[item]' in desc_lower or 'グッズ' in desc or 'を使う' in desc:
        # Night Stretcher, Super Rod, etc
        if 'night stretcher' in desc_lower or 'super rod' in desc_lower:
            return (8, desc)
        if 'technical machine' in desc_lower:
            return (9, desc)
        if 'prime catcher' in desc_lower:
            # Only use if we can attack
            return (20, desc)  # evaluate later
        if 'unfair stamp' in desc_lower:
            return (25, desc)
        return (10, desc)
    # 4. Supporters (draw)
    if 'lillie' in desc_lower:
        return (11, desc)
    if 'iono' in desc_lower:
        return (12, desc)
    if 'crispin' in desc_lower:
        return (13, desc)
    if 'supporter' in desc_lower or 'サポーター' in desc:
        return (14, desc)
    # 5. Deploy basics to bench
    if 'ベンチに出す' in desc:
        return (15, desc)
    # 6. Attach energy (prefer to main attacker)
    if 'に付ける' in desc or 'エネルギー' in desc:
        # Prefer attacker (Charizard ex, Raging Bolt ex, Dragapult ex)
        if 'charizard' in desc_lower or 'raging bolt' in desc_lower or 'dragapult' in desc_lower:
            return (16, desc)
        if 'charmander' in desc_lower or 'charmeleon' in desc_lower:
            return (17, desc)
        if 'dreepy' in desc_lower or 'drakloak' in desc_lower:
            return (17, desc)
        return (18, desc)
    # 7. Attack
    if '技' in desc and 'ダメージ' in desc:
        return (30, desc)
    if '技「' in desc:
        return (30, desc)
    # Retreat
    if 'にげる' in desc or '入れ替え' in desc:
        return (40, desc)
    # End turn
    if 'ターン終了' in desc:
        return (50, desc)
    
    return (35, desc)


def choose_action(valid_actions, game, pid):
    """Choose best action using heuristics."""
    me = game.players[pid]
    opp = game.players[1 - pid]
    
    categorized = []
    for i, action_id in enumerate(valid_actions):
        cat = categorize_action(action_id, me, opp, game)
        categorized.append((cat[0], i, cat[1], action_id))
    
    categorized.sort(key=lambda x: x[0])
    
    # Check if we can attack
    can_attack = any(c[0] == 30 for c in categorized)
    
    # If we can attack, check if Boss's Orders / Prime Catcher would be good
    # For now, simple: pick highest priority action
    
    best = categorized[0]
    
    # Don't end turn if we can do something useful
    if best[0] >= 50 and len(categorized) > 1:
        # Pick the next best that isn't end turn
        for c in categorized:
            if c[0] < 50:
                best = c
                break
    
    # If only end turn and retreat available, and we can attack, attack first
    if can_attack:
        for c in categorized:
            if c[0] == 30:
                # But do other things first (energy, evolution, etc)
                non_attack_useful = [x for x in categorized if x[0] < 30]
                if non_attack_useful:
                    best = non_attack_useful[0]
                else:
                    best = c
                break
    
    return best[1]  # return the index (1-based choice will be index+1)


def play_one_game(game_id=0, output_dir="data/claude_games"):
    decks = [0, 1, 2]
    d0 = random.choice(decks)
    d1 = random.choice(decks)
    
    game = Game(d0, d1)
    game.reset()
    
    env = PTCGEnv(d0, d1, randomize_decks=False)
    env.game = game
    
    deck_name_0 = DECK_NAMES.get(d0, f"Deck{d0}")
    deck_name_1 = DECK_NAMES.get(d1, f"Deck{d1}")
    
    print(f"GAME_START|{game_id}|{deck_name_0}|{deck_name_1}")
    
    samples = []
    step_count = 0
    max_steps = 500
    
    while not game.done and step_count < max_steps:
        pid = game.current_player
        valid_actions = game.get_valid_actions()
        
        if not valid_actions:
            break
        
        obs = get_obs(env, game, pid)
        mask = np.zeros(NUM_ACTIONS, dtype=np.float32)
        for v in valid_actions:
            mask[v] = 1.0
        me = game.players[pid]
        opp = game.players[1 - pid]
        
        if len(valid_actions) == 1:
            action = valid_actions[0]
            desc = format_action(action, me, opp, game)
            samples.append({
                "obs": obs.tolist(),
                "action": int(action),
                "valid_mask": mask.tolist(),
                "player_id": pid,
                "action_desc": desc,
                "auto": True,
            })
            game.step(action)
            step_count += 1
            continue
        
        choice_idx = choose_action(valid_actions, game, pid)
        action = valid_actions[choice_idx]
        desc = format_action(action, me, opp, game)
        
        samples.append({
            "obs": obs.tolist(),
            "action": int(action),
            "valid_mask": mask.tolist(),
            "player_id": pid,
            "action_desc": desc,
            "auto": False,
        })
        
        game.step(action)
        step_count += 1
    
    winner = game.winner
    p0_prizes = game.players[0].prizes_taken
    p1_prizes = game.players[1].prizes_taken
    
    result = {
        "game_id": game_id,
        "deck_0": deck_name_0,
        "deck_1": deck_name_1,
        "winner": f"P{winner}" if winner is not None else "draw",
        "turns": game.turn_count,
        "steps": step_count,
        "p0_prizes": p0_prizes,
        "p1_prizes": p1_prizes,
        "num_samples": len(samples),
        "num_decisions": sum(1 for s in samples if not s["auto"]),
    }
    
    print(f"GAME_END|{json.dumps(result, ensure_ascii=False)}")
    
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    
    with open(out_path / f"game_{game_id}.jsonl", "w") as f:
        for s in samples:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")
    
    return result


if __name__ == "__main__":
    start_id = int(sys.argv[1]) if len(sys.argv) > 1 else 42
    end_id = int(sys.argv[2]) if len(sys.argv) > 2 else 55
    out_dir = sys.argv[3] if len(sys.argv) > 3 else "data/claude_games"
    
    for gid in range(start_id, end_id + 1):
        result = play_one_game(gid, out_dir)
        print(f"--- Game {gid} complete: {result['winner']} won in {result['turns']} turns ---")
