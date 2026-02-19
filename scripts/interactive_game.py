"""インタラクティブ対戦スクリプト - Claude/人間が標準入出力でプレイ

使い方: python scripts/interactive_game.py [game_id] [output_dir]
- 盤面とアクション一覧を表示 → 標準入力でアクション番号を受け取る
- 両プレイヤーの判断を記録（obs, action, valid_mask）
- 1ゲーム完了時にJSONL形式で保存
"""
import sys
import os
import json
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
    """指定プレイヤー視点のobsを取得"""
    original_agent = env.agent_id
    env.agent_id = player_id
    obs = env._get_obs()
    env.agent_id = original_agent
    return obs


def play_one_game(game_id=0, output_dir="data/claude_games"):
    """1ゲームをインタラクティブにプレイ"""
    decks = [0, 1, 2]
    d0 = random.choice(decks)
    d1 = random.choice(decks)
    
    game = Game(d0, d1)
    game.reset()
    
    # envはobs取得用
    env = PTCGEnv(d0, d1, randomize_decks=False)
    env.game = game
    
    deck_name_0 = DECK_NAMES.get(d0, f"Deck{d0}")
    deck_name_1 = DECK_NAMES.get(d1, f"Deck{d1}")
    
    print(f"GAME_START|{game_id}|{deck_name_0}|{deck_name_1}")
    print(f"先攻: P{game.first_player} ({deck_name_0 if game.first_player == 0 else deck_name_1})")
    sys.stdout.flush()
    
    samples = []  # (obs, action, valid_mask, player_id, action_desc)
    step_count = 0
    max_steps = 500  # safety
    
    while not game.done and step_count < max_steps:
        pid = game.current_player
        valid_actions = game.get_valid_actions()
        
        if not valid_actions:
            break
        
        # 選択肢が1つしかない場合は自動選択
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
        
        # 盤面表示
        state_text = format_game_state(game, pid)
        actions_text = format_valid_actions(game, pid)
        
        print(f"STEP|{step_count}|P{pid}")
        print(state_text)
        print(actions_text)
        print(f"ACTION_PROMPT|{len(valid_actions)}")
        sys.stdout.flush()
        
        # 入力待ち
        try:
            line = input().strip()
            choice = int(line)
        except (ValueError, EOFError):
            # 不正入力 → ランダム
            choice = 1
        
        if choice < 1 or choice > len(valid_actions):
            choice = 1
        
        action = valid_actions[choice - 1]
        
        # obs/mask記録
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
            "auto": False,
        })
        
        game.step(action)
        step_count += 1
    
    # 結果
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
    sys.stdout.flush()
    
    # 保存
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    
    with open(out_path / f"game_{game_id}.jsonl", "w") as f:
        for s in samples:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")
    
    return result


if __name__ == "__main__":
    gid = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    out = sys.argv[2] if len(sys.argv) > 2 else "data/claude_games"
    play_one_game(gid, out)
