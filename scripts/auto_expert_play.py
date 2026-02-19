"""Automated expert player for generating imitation learning data.

Applies heuristic strategy rules to make decisions automatically.
Usage: python scripts/auto_expert_play.py <start_id> <end_id> [output_dir]
"""
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


def classify_action(action_id, action_text, game, pid):
    """Classify action into priority categories for expert play."""
    text = action_text.lower()
    me = game.players[pid]
    opp = game.players[1 - pid]
    turn = game.turn_count
    
    # Priority scores (higher = do first)
    score = 0
    
    # === ABILITIES (highest priority) ===
    if '特性' in action_text:
        score = 900
        if 'teal dance' in text:
            score = 950  # Energy acceleration
        if 'restart' in text:
            score = 940
        if 'jewel seeker' in text:
            score = 930
        if 'recon directive' in text:
            score = 920
        return score
    
    # === EVOLUTION (very high priority) ===
    if '進化' in action_text:
        score = 800
        if 'ふしぎなアメ' in action_text or 'rare candy' in text:
            score = 880  # Rare Candy evolution = highest evolution priority
            if 'dragapult ex' in text or 'charizard ex' in text or 'pidgeot ex' in text:
                score = 890  # Stage 2 ex evolution
        elif 'stage 2' in text or 'ex' in text:
            score = 850
        return score
    
    # === ITEMS - Search/Draw ===
    if any(item in text for item in ['buddy-buddy poffin', 'nest ball', 'ultra ball']):
        score = 700
        if 'buddy-buddy poffin' in text:
            score = 750
        return score
    
    if any(item in text for item in ['earthen vessel', 'glass trumpet', 'night stretcher']):
        score = 680
        return score
    
    if 'prime catcher' in text:
        # Save for important targets, but use if available
        score = 650
        return score
    
    if 'energy switch' in text:
        score = 640
        return score
    
    if 'unfair stamp' in text:
        score = 100  # Low priority, situational
        return score
    
    # === SUPPORTERS ===
    if any(s in text for s in ['iono', 'lillie', 'dawn', 'professor', 'crispin']):
        score = 600
        if 'crispin' in text:
            score = 620  # Energy search
        if 'iono' in text and opp.hand and len(opp.hand) > 6:
            score = 650  # Disruption when opponent has many cards
        if 'dawn' in text:
            score = 610
        if 'lillie' in text:
            score = 615
        return score
    
    if "boss's orders" in text:
        # Use Boss strategically - pull weak/important targets
        score = 400  # Default moderate
        # Late game: higher priority
        if me.prizes_taken >= 4:
            score = 750
        return score
    
    # === BENCH POKEMON ===
    if 'ベンチに出す' in action_text:
        score = 500
        # Prioritize key basics
        if any(name in text for name in ['charmander', 'dreepy', 'ogerpon', 'raging bolt']):
            score = 550
        if 'ditto' in text:
            score = 520
        return score
    
    # === STADIUM ===
    if any(s in text for s in ['artazon', 'area zero', 'stadium']):
        score = 450
        return score
    
    # === POKEMON TOOL ===
    if any(t in text for t in ['vitality band', 'air balloon']):
        score = 430
        return score
    
    # === ENERGY ATTACHMENT ===
    if 'energyを' in action_text.lower() or 'energy' in text and '付ける' in action_text:
        score = 300
        # Prioritize main attackers
        if any(name in text for name in ['dragapult ex', 'charizard ex', 'raging bolt ex', 'ogerpon ex']):
            score = 380
        elif any(name in text for name in ['drakloak', 'charmeleon', 'chi-yu']):
            score = 350
        # Prefer attackers that are close to being able to attack
        return score
    
    # === ATTACK ===
    if '技「' in action_text or '技' in action_text:
        score = 200  # Attack after setup
        # But if we can KO, attack immediately
        if 'phantom dive' in text:
            score = 850  # 200 damage = likely KO
        if 'burning darkness' in text:
            score = 840
        if 'bellowing thunder' in text:
            score = 830
        if 'dragon headbutt' in text:
            score = 500  # 70 damage, moderate
        if 'eon blade' in text:
            score = 820  # 200 damage
        if 'myriad leaf shower' in text:
            score = 810
        return score
    
    # === RETREAT ===
    if 'にげる' in action_text:
        score = 150
        # Retreat to main attacker if ready
        if any(name in text for name in ['dragapult ex', 'charizard ex', 'raging bolt ex', 'ogerpon ex']):
            score = 250
        return score
    
    # === END TURN ===
    if 'ターン終了' in action_text:
        score = 1  # Always last resort
        return score
    
    return score


def expert_choose_action(valid_actions, game, pid, action_texts):
    """Choose the best action using expert heuristics."""
    if len(valid_actions) == 1:
        return 0  # Only one choice
    
    scored = []
    for i, (action_id, text) in enumerate(zip(valid_actions, action_texts)):
        score = classify_action(action_id, text, game, pid)
        # Add small random tiebreaker
        score += random.uniform(0, 0.1)
        scored.append((score, i))
    
    scored.sort(reverse=True)
    
    # Return the index of the best action
    return scored[0][1]


def play_one_game(game_id=0, output_dir="data/claude_games"):
    """Play one game with automated expert decisions."""
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
        
        # Auto-select if only one choice
        if len(valid_actions) == 1:
            action = valid_actions[0]
            obs = get_obs(env, game, pid)
            mask = np.zeros(NUM_ACTIONS, dtype=np.float32)
            for v in valid_actions:
                mask[v] = 1.0
            me = game.players[pid]
            opp = game.players[1 - pid]
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
        
        # Get action texts for classification
        me = game.players[pid]
        opp = game.players[1 - pid]
        action_texts = []
        for a in valid_actions:
            try:
                desc = format_action(a, me, opp, game)
                action_texts.append(desc)
            except:
                action_texts.append(str(a))
        
        # Expert decision
        choice_idx = expert_choose_action(valid_actions, game, pid, action_texts)
        action = valid_actions[choice_idx]
        
        # Record
        obs = get_obs(env, game, pid)
        mask = np.zeros(NUM_ACTIONS, dtype=np.float32)
        for v in valid_actions:
            mask[v] = 1.0
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
        
        if step_count % 50 == 0:
            print(f"  Step {step_count}, Turn {game.turn_count}, "
                  f"P0 prizes: {game.players[0].prizes_taken}, "
                  f"P1 prizes: {game.players[1].prizes_taken}")
    
    winner = game.winner
    result = {
        "game_id": game_id,
        "deck_0": deck_name_0,
        "deck_1": deck_name_1,
        "winner": f"P{winner}" if winner is not None else "draw",
        "turns": game.turn_count,
        "steps": step_count,
        "p0_prizes": game.players[0].prizes_taken,
        "p1_prizes": game.players[1].prizes_taken,
        "num_samples": len(samples),
        "num_decisions": sum(1 for s in samples if not s["auto"]),
    }
    
    print(f"GAME_END|{json.dumps(result, ensure_ascii=False)}")
    
    # Save
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    
    with open(out_path / f"game_{game_id}.jsonl", "w") as f:
        for s in samples:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")
    
    return result


if __name__ == "__main__":
    start_id = int(sys.argv[1]) if len(sys.argv) > 1 else 14
    end_id = int(sys.argv[2]) if len(sys.argv) > 2 else 27
    out = sys.argv[3] if len(sys.argv) > 3 else "data/claude_games"
    
    results = []
    for gid in range(start_id, end_id + 1):
        print(f"\n{'='*50}")
        print(f"Playing game {gid}...")
        print(f"{'='*50}")
        r = play_one_game(gid, out)
        results.append(r)
        print(f"Result: {r['winner']}, {r['turns']} turns, {r['num_decisions']} decisions")
    
    print(f"\n{'='*50}")
    print(f"All {len(results)} games completed!")
    for r in results:
        print(f"  Game {r['game_id']}: {r['winner']} ({r['deck_0']} vs {r['deck_1']}), "
              f"{r['turns']}T, {r['num_decisions']} decisions")
