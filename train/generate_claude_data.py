"""お手本データ生成 - Claude vs ランダム / Claude vs Claude で対戦データを生成"""
from __future__ import annotations
import sys, os, json, time, random
import numpy as np
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.game import Game
from engine.actions import NUM_ACTIONS, END_TURN, decode_action
from engine.text_state import format_game_state, format_valid_actions
from engine.claude_player import ClaudePlayer
from env.ptcg_env import PTCGEnv


def generate_claude_games(
    n_games: int = 10,
    output_dir: str = "data/claude_games",
    mode: str = "claude_vs_random",   # "claude_vs_random" or "claude_vs_claude"
    model: str = "claude-sonnet-4-20250514",
    verbose: bool = True,
) -> dict:
    """
    Claudeプレイヤーでゲームをプレイし、(obs, action, valid_mask)を保存。
    
    mode:
      - claude_vs_random: Claude(agent) vs Random(opponent)
      - claude_vs_claude: Both players are Claude (2x API calls)
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    claude = ClaudePlayer(model=model, verbose=verbose)

    # For claude_vs_claude, we need a second instance for opponent
    claude_opp = None
    if mode == "claude_vs_claude":
        claude_opp = ClaudePlayer(model=model, verbose=False)

    all_samples = []
    stats = {
        "wins": [0, 0], "draws": 0, "total_turns": 0,
        "total_samples": 0, "errors": 0, "mode": mode,
    }

    t0 = time.time()

    for game_idx in range(n_games):
        try:
            # Create game with random decks
            deck_ids = [0, 1, 2]
            d0 = random.choice(deck_ids)
            d1 = random.choice(deck_ids)
            game = Game(d0, d1)
            game.reset()

            agent_id = game.first_player
            game_samples = []
            text_log = []
            steps = 0
            max_steps = 5000

            if verbose:
                print(f"\n=== Game {game_idx+1}/{n_games} (deck {d0} vs {d1}) ===")

            while not game.done and steps < max_steps:
                cp = game.current_player
                valid = game.get_valid_actions()

                if not valid:
                    break

                if len(valid) == 1:
                    action = valid[0]
                elif cp == agent_id:
                    # Claude's turn - get turn actions
                    turn_actions = claude.choose_turn_actions(game, cp)

                    # Execute actions one by one
                    first = True
                    for action_idx in turn_actions:
                        if game.done or game.current_player != cp:
                            break
                        current_valid = game.get_valid_actions()
                        if not current_valid:
                            break
                        if action_idx < len(current_valid):
                            action = current_valid[action_idx]
                        else:
                            continue

                        # Record observation before action
                        obs = _get_obs_for_player(game, cp)
                        mask = _get_mask(game)

                        game_samples.append({
                            "game_id": game_idx,
                            "turn": game.turn_count,
                            "step": steps,
                            "obs": obs.tolist(),
                            "action": int(action),
                            "valid_mask": mask.tolist(),
                            "deck_id": d0,
                        })

                        if verbose and first:
                            text_log.append(format_game_state(game, cp))
                            text_log.append(format_valid_actions(game, cp))
                            first = False

                        reward, done = game.step(action)
                        steps += 1

                        if done:
                            break

                        # Re-check valid actions after step - list may have changed
                        new_valid = game.get_valid_actions()
                        if game.current_player != cp:
                            break  # Turn ended

                    continue  # Skip the single-action path below

                elif mode == "claude_vs_claude" and claude_opp:
                    # Opponent is also Claude
                    turn_actions = claude_opp.choose_turn_actions(game, cp)
                    for action_idx in turn_actions:
                        if game.done or game.current_player != cp:
                            break
                        current_valid = game.get_valid_actions()
                        if action_idx < len(current_valid):
                            action = current_valid[action_idx]
                            reward, done = game.step(action)
                            steps += 1
                            if done:
                                break
                            if game.current_player != cp:
                                break
                    continue
                else:
                    # Random opponent
                    action = random.choice(valid)

                # Single action execution (for random opponent or len(valid)==1)
                if cp == agent_id and len(valid) > 1:
                    # Already handled above
                    pass
                else:
                    if cp == agent_id:
                        obs = _get_obs_for_player(game, cp)
                        mask = _get_mask(game)
                        game_samples.append({
                            "game_id": game_idx,
                            "turn": game.turn_count,
                            "step": steps,
                            "obs": obs.tolist(),
                            "action": int(action),
                            "valid_mask": mask.tolist(),
                            "deck_id": d0,
                        })

                    reward, done = game.step(action)
                    steps += 1

            all_samples.extend(game_samples)

            winner = game.winner
            if winner == agent_id:
                stats["wins"][0] += 1
                result = "WIN"
            elif winner is not None:
                stats["wins"][1] += 1
                result = "LOSE"
            else:
                stats["draws"] += 1
                result = "DRAW"

            stats["total_turns"] += game.turn_count
            stats["total_samples"] += len(game_samples)

            if verbose:
                print(f"  Result: {result} | Turns: {game.turn_count} | "
                      f"Samples: {len(game_samples)} | "
                      f"Claude calls: {claude.total_calls}")

            # Save text log for first few games
            if text_log and game_idx < 3:
                text_path = output_path / f"game_{game_idx:04d}.txt"
                with open(text_path, "w") as f:
                    f.write("\n".join(text_log))

        except Exception as e:
            stats["errors"] += 1
            if verbose:
                print(f"  Error in game {game_idx}: {e}")
            import traceback
            traceback.print_exc()

    elapsed = time.time() - t0

    # Save JSONL
    jsonl_path = output_path / "claude_data.jsonl"
    with open(jsonl_path, "w") as f:
        for s in all_samples:
            f.write(json.dumps(s) + "\n")

    # Save as numpy for training
    if all_samples:
        obs_array = np.array([s["obs"] for s in all_samples], dtype=np.float32)
        action_array = np.array([s["action"] for s in all_samples], dtype=np.int64)
        mask_array = np.array([s["valid_mask"] for s in all_samples], dtype=bool)

        np.savez_compressed(
            output_path / "claude_data.npz",
            obs=obs_array,
            actions=action_array,
            masks=mask_array,
        )

    # Stats
    claude_stats = claude.get_stats()
    if claude_opp:
        opp_stats = claude_opp.get_stats()
        claude_stats["opp_calls"] = opp_stats["total_calls"]
        claude_stats["opp_input_tokens"] = opp_stats["total_input_tokens"]
        claude_stats["opp_output_tokens"] = opp_stats["total_output_tokens"]

    stats["elapsed"] = elapsed
    stats["claude_stats"] = claude_stats
    stats["avg_turns"] = stats["total_turns"] / max(n_games - stats["errors"], 1)
    stats["avg_samples_per_game"] = stats["total_samples"] / max(n_games - stats["errors"], 1)

    with open(output_path / "stats.json", "w") as f:
        json.dump(stats, f, indent=2, ensure_ascii=False)

    if verbose:
        print(f"\n=== Generation Complete ===")
        print(f"Games: {n_games} | Wins: {stats['wins'][0]} | Losses: {stats['wins'][1]} | Draws: {stats['draws']}")
        print(f"Total samples: {stats['total_samples']}")
        print(f"Claude API calls: {claude_stats['total_calls']}")
        print(f"Input tokens: {claude_stats['total_input_tokens']:,}")
        print(f"Output tokens: {claude_stats['total_output_tokens']:,}")
        print(f"Time: {elapsed:.1f}s")
        print(f"Data saved to: {output_dir}/")

    return stats


def _get_obs_for_player(game: Game, player_id: int) -> np.ndarray:
    """PTCGEnvを使わずにobservationを直接生成"""
    # Create a temporary env and extract obs
    env = PTCGEnv.__new__(PTCGEnv)
    env.game = game
    env.agent_id = player_id
    return env._get_obs()


def _get_mask(game: Game) -> np.ndarray:
    """valid action mask"""
    mask = np.zeros(NUM_ACTIONS, dtype=bool)
    for a in game.get_valid_actions():
        if 0 <= a < NUM_ACTIONS:
            mask[a] = True
    return mask


def evaluate_claude_vs_random(n_games: int = 10,
                               model: str = "claude-sonnet-4-20250514",
                               verbose: bool = True) -> float:
    """Claude vs ランダムの勝率を計測"""
    claude = ClaudePlayer(model=model, verbose=False)
    wins = 0

    for i in range(n_games):
        try:
            d0, d1 = random.choice([0, 1, 2]), random.choice([0, 1, 2])
            game = Game(d0, d1)
            game.reset()
            agent_id = game.first_player
            steps = 0

            while not game.done and steps < 5000:
                cp = game.current_player
                valid = game.get_valid_actions()
                if not valid:
                    break

                if cp == agent_id:
                    if len(valid) == 1:
                        action = valid[0]
                    else:
                        turn_actions = claude.choose_turn_actions(game, cp)
                        # Execute turn actions
                        for idx in turn_actions:
                            if game.done or game.current_player != cp:
                                break
                            cv = game.get_valid_actions()
                            if idx < len(cv):
                                game.step(cv[idx])
                                steps += 1
                                if game.current_player != cp:
                                    break
                        continue
                else:
                    action = random.choice(valid)

                game.step(action)
                steps += 1

            if game.winner == agent_id:
                wins += 1
            if verbose:
                result = "WIN" if game.winner == agent_id else ("LOSE" if game.winner is not None else "DRAW")
                print(f"  Game {i+1}: {result}")

        except Exception as e:
            if verbose:
                print(f"  Game {i+1}: ERROR - {e}")

    wr = wins / n_games
    if verbose:
        print(f"\nClaude vs Random: {wr*100:.1f}% ({wins}/{n_games})")
        stats = claude.get_stats()
        print(f"API calls: {stats['total_calls']} | "
              f"Tokens: {stats['total_input_tokens']:,} in / {stats['total_output_tokens']:,} out")
    return wr


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", default="generate",
                        choices=["generate", "eval"])
    parser.add_argument("--games", type=int, default=10)
    parser.add_argument("--output", default="data/claude_games")
    parser.add_argument("--match-mode", default="claude_vs_random",
                        choices=["claude_vs_random", "claude_vs_claude"])
    parser.add_argument("--model", default="claude-sonnet-4-20250514")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    if args.mode == "eval":
        evaluate_claude_vs_random(args.games, args.model, not args.quiet)
    else:
        generate_claude_games(
            n_games=args.games,
            output_dir=args.output,
            mode=args.match_mode,
            model=args.model,
            verbose=not args.quiet,
        )
