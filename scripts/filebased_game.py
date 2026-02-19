"""ファイルベース対戦スクリプト - サブエージェントとファイルでやり取り

ゲームループ:
1. state.json に盤面+選択肢を書き出し
2. decision.json が出現するまでポーリング
3. decision.json を読んでアクション実行
4. decision.json を削除して次のステップへ
5. ゲーム終了時に result.json を書き出し

Usage: python scripts/filebased_game.py [game_id] [work_dir]
"""
import sys
import os
import json
import time
import random
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


def play_one_game(game_id=0, work_dir="data/claude_games/active"):
    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)
    
    state_file = work / "state.json"
    decision_file = work / "decision.json"
    result_file = work / "result.json"
    
    # Clean up old files
    for f in [state_file, decision_file, result_file]:
        if f.exists():
            f.unlink()
    
    # Setup game
    decks = [0, 1, 2]
    d0 = random.choice(decks)
    d1 = random.choice(decks)
    game = Game(d0, d1)
    game.reset()
    env = PTCGEnv(d0, d1, randomize_decks=False)
    env.game = game
    
    deck_name_0 = DECK_NAMES.get(d0, f"Deck{d0}")
    deck_name_1 = DECK_NAMES.get(d1, f"Deck{d1}")
    
    samples = []
    step_count = 0
    max_steps = 500
    
    print(f"Game {game_id}: {deck_name_0} vs {deck_name_1}, first=P{game.first_player}")
    
    while not game.done and step_count < max_steps:
        pid = game.current_player
        valid_actions = game.get_valid_actions()
        
        if not valid_actions:
            break
        
        # Auto-pick if only 1 choice
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
        
        # Write state for agent
        state_text = format_game_state(game, pid)
        me = game.players[pid]
        opp = game.players[1 - pid]
        
        actions_list = []
        for i, a in enumerate(valid_actions):
            desc = format_action(a, me, opp, game)
            actions_list.append({"index": i + 1, "action_id": a, "description": desc})
        
        state_data = {
            "game_id": game_id,
            "step": step_count,
            "player_id": pid,
            "turn": game.turn_count,
            "board_state": state_text,
            "valid_actions": actions_list,
            "num_actions": len(valid_actions),
            "status": "waiting_for_decision",
        }
        
        with open(state_file, "w") as f:
            json.dump(state_data, f, ensure_ascii=False, indent=2)
        
        print(f"  Step {step_count}: P{pid} T{game.turn_count} - {len(valid_actions)} actions, waiting...")
        
        # Poll for decision
        timeout = 300  # 5 min max per decision
        start = time.time()
        while not decision_file.exists():
            if time.time() - start > timeout:
                print(f"  TIMEOUT at step {step_count}, picking action 1")
                break
            time.sleep(0.5)
        
        # Read decision
        if decision_file.exists():
            with open(decision_file, "r") as f:
                dec = json.load(f)
            choice = dec.get("choice", 1)
            decision_file.unlink()
        else:
            choice = 1
        
        if choice < 1 or choice > len(valid_actions):
            choice = 1
        
        action = valid_actions[choice - 1]
        
        # Record sample
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
        
        print(f"  -> choice {choice}: {desc}")
        game.step(action)
        step_count += 1
    
    # Game over
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
        "status": "complete",
    }
    
    # Save result
    with open(result_file, "w") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    
    # Clear state file
    if state_file.exists():
        state_file.unlink()
    
    # Save training data
    out_dir = Path("data/claude_games")
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / f"game_{game_id}.jsonl", "w") as f:
        for s in samples:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")
    
    print(f"Game {game_id} complete: {result['winner']}, {result['turns']} turns, {result['num_decisions']} decisions")
    return result


if __name__ == "__main__":
    gid = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    wdir = sys.argv[2] if len(sys.argv) > 2 else "data/claude_games/active"
    play_one_game(gid, wdir)
