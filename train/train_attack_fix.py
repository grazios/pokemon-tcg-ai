"""技選択率改善 - reward修正後の再学習 + 評価スクリプト"""
from __future__ import annotations
import sys, os, time, json
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sb3_contrib import MaskablePPO
from sb3_contrib.common.wrappers import ActionMasker
from stable_baselines3.common.callbacks import BaseCallback
from env.ptcg_env import PTCGEnv
from engine.actions import NUM_ACTIONS, END_TURN, ATTACK_BASE

MODELS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "models")


class AttackRateCallback(BaseCallback):
    """学習中に技選択率とvsランダム勝率を計測"""
    def __init__(self, eval_interval=50000, eval_games=50, verbose=1):
        super().__init__(verbose)
        self.eval_interval = eval_interval
        self.eval_games = eval_games
        self._last_eval = 0
        self.metrics = []

    def _on_step(self):
        if self.num_timesteps - self._last_eval >= self.eval_interval:
            self._last_eval = self.num_timesteps
            wr, attack_rate, win_types = evaluate_detailed(self.model, self.eval_games)
            self.metrics.append({
                "steps": self.num_timesteps,
                "win_rate": wr,
                "attack_rate": attack_rate,
                "win_types": win_types,
            })
            print(f"\n[{self.num_timesteps}] WR={wr:.1f}% | AttackRate={attack_rate:.1f}% | {win_types}")
        return True


def evaluate_detailed(model, n_games=50):
    """技選択率 + 勝率 + 勝利パターン"""
    raw_env = PTCGEnv(randomize_decks=True)
    env = ActionMasker(raw_env, lambda e: e.action_masks())

    wins = 0
    attack_opportunities = 0
    attacks_chosen = 0
    win_types = {"prize": 0, "no_pokemon": 0, "deckout": 0, "draw": 0, "loss": 0}

    for _ in range(n_games):
        obs, _ = env.reset()
        done = False
        steps = 0
        while not done and steps < 5000:
            mask = raw_env.action_masks()
            valid = np.where(mask)[0]

            # Check if attack is available
            attack_available = any(ATTACK_BASE <= a <= ATTACK_BASE + 1 for a in valid)
            if attack_available:
                attack_opportunities += 1

            action, _ = model.predict(obs, action_masks=mask, deterministic=False)
            action = int(action)

            if attack_available and ATTACK_BASE <= action <= ATTACK_BASE + 1:
                attacks_chosen += 1

            obs, reward, done, truncated, info = env.step(action)
            steps += 1

        g = raw_env.game
        if g.winner == raw_env.agent_id:
            wins += 1
            # Determine win type
            opp = g.players[1 - raw_env.agent_id]
            me = g.players[raw_env.agent_id]
            if me.prizes_taken >= g.PRIZE_TARGET or not me.prizes:
                win_types["prize"] += 1
            elif opp.active is None and not opp.bench:
                win_types["no_pokemon"] += 1
            else:
                win_types["deckout"] += 1
        elif g.winner is None:
            win_types["draw"] += 1
        else:
            win_types["loss"] += 1

    wr = wins / n_games * 100
    ar = attacks_chosen / max(attack_opportunities, 1) * 100
    return wr, ar, win_types


def print_game_log(model, n_games=10):
    """対戦ログ出力"""
    raw_env = PTCGEnv(randomize_decks=True)
    env = ActionMasker(raw_env, lambda e: e.action_masks())

    for game_num in range(n_games):
        obs, _ = env.reset()
        done = False
        steps = 0
        print(f"\n{'='*60}")
        print(f"Game {game_num+1}")
        print(f"{'='*60}")

        last_turn = -1
        while not done and steps < 5000:
            mask = raw_env.action_masks()
            valid = np.where(mask)[0]
            action, _ = model.predict(obs, action_masks=mask, deterministic=False)
            action = int(action)

            g = raw_env.game
            if g.turn_count != last_turn and g.current_player == raw_env.agent_id:
                last_turn = g.turn_count
                me = g.players[raw_env.agent_id]
                opp = g.players[1 - raw_env.agent_id]
                active_name = me.active.card.name if me.active else "None"
                active_hp = me.active.current_hp if me.active else 0
                active_energy = me.active.total_energy() if me.active else 0
                opp_active = opp.active.card.name if opp.active else "None"
                opp_hp = opp.active.current_hp if opp.active else 0
                print(f"\nTurn {g.turn_count}: {active_name}(HP{active_hp},E{active_energy}) vs {opp_active}(HP{opp_hp})")

            # Decode action for logging
            from engine.actions import decode_action
            info = decode_action(action)
            if g.current_player == raw_env.agent_id:
                if info["type"] == "attack":
                    atk_name = ""
                    me = g.players[raw_env.agent_id]
                    if me.active and info["attack_idx"] < len(me.active.card.attacks):
                        atk_name = me.active.card.attacks[info["attack_idx"]].name
                    print(f"  -> ATTACK: {atk_name}")
                elif info["type"] == "end_turn":
                    attack_avail = any(ATTACK_BASE <= a <= ATTACK_BASE + 1 for a in valid)
                    flag = " ⚠️ COULD ATTACK!" if attack_avail else ""
                    print(f"  -> END TURN{flag}")
                elif info["type"] == "play_card":
                    me = g.players[raw_env.agent_id]
                    if info["hand_idx"] < len(me.hand):
                        print(f"  -> PLAY: {me.hand[info['hand_idx']].name}")
                elif info["type"] == "energy_active" or info["type"] == "energy_bench":
                    print(f"  -> ENERGY")
                elif info["type"] in ("evolve_active", "evolve_bench"):
                    print(f"  -> EVOLVE")

            obs, reward, done, truncated, _ = env.step(action)
            steps += 1

        g = raw_env.game
        winner = "AI" if g.winner == raw_env.agent_id else ("Opponent" if g.winner is not None else "Draw")
        print(f"  Result: {winner} (turns: {g.turn_count})")


def train():
    os.makedirs(MODELS_DIR, exist_ok=True)

    # Phase 1: vs Random warmup (500k steps)
    print("=" * 60)
    print("Phase 1: vs Random warmup (500k steps)")
    print("=" * 60)

    raw_env = PTCGEnv(randomize_decks=True)
    env = ActionMasker(raw_env, lambda e: e.action_masks())

    model = MaskablePPO(
        "MlpPolicy", env, verbose=1,
        learning_rate=3e-4,
        n_steps=2048,
        batch_size=256,
        n_epochs=10,
        gamma=0.99,
        ent_coef=0.05,
        policy_kwargs=dict(net_arch=[256, 256]),
    )

    cb = AttackRateCallback(eval_interval=100000, eval_games=50)
    model.learn(total_timesteps=500000, callback=cb)

    warmup_path = os.path.join(MODELS_DIR, "attack_fix_warmup")
    model.save(warmup_path)
    print(f"\nWarmup model saved: {warmup_path}.zip")

    # Phase 2: Self-play (2M steps)
    print("\n" + "=" * 60)
    print("Phase 2: Self-play (2M steps)")
    print("=" * 60)

    from train.train_selfplay import ModelOpponent, OpponentPool, SelfPlayCallback, EloTracker

    pool = OpponentPool(MODELS_DIR, latest_ratio=0.7)
    pool.add(warmup_path + ".zip")
    elo = EloTracker()

    # Start with self as opponent
    opp = ModelOpponent(model, raw_env)
    raw_env.opponent_policy = opp

    sp_cb = SelfPlayCallback(
        pool=pool, raw_env=raw_env,
        snapshot_interval=50000, warmup_steps=0, elo=elo,
    )
    ar_cb = AttackRateCallback(eval_interval=200000, eval_games=50)

    model.learn(total_timesteps=2000000, callback=[sp_cb, ar_cb])

    final_path = os.path.join(MODELS_DIR, "attack_fix_final")
    model.save(final_path)
    print(f"\nFinal model saved: {final_path}.zip")

    # Save metrics
    metrics = {"warmup": cb.metrics, "selfplay": ar_cb.metrics}
    with open(os.path.join(MODELS_DIR, "attack_fix_metrics.json"), "w") as f:
        json.dump(metrics, f, indent=2)

    # Final evaluation
    print("\n" + "=" * 60)
    print("FINAL EVALUATION")
    print("=" * 60)

    wr, ar, wt = evaluate_detailed(model, 200)
    print(f"\nvs Random (200 games):")
    print(f"  Win rate: {wr:.1f}%")
    print(f"  Attack rate: {ar:.1f}%")
    print(f"  Win types: {wt}")

    # Game logs
    print("\n" + "=" * 60)
    print("GAME LOGS (10 games)")
    print("=" * 60)
    print_game_log(model, 10)

    return final_path


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--eval-only", type=str, help="Evaluate existing model")
    parser.add_argument("--games", type=int, default=200)
    args = parser.parse_args()

    if args.eval_only:
        model = MaskablePPO.load(args.eval_only)
        wr, ar, wt = evaluate_detailed(model, args.games)
        print(f"Win rate: {wr:.1f}%")
        print(f"Attack rate: {ar:.1f}%")
        print(f"Win types: {wt}")
        print_game_log(model, 10)
    else:
        train()
