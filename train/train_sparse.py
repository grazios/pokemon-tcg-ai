"""Sparse Reward Self-Play Training - 10M steps
AlphaGo style: reward = game outcome only (+prize delta).
"""
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


class ModelOpponent:
    def __init__(self, model: MaskablePPO, env_ref: PTCGEnv):
        self.model = model
        self.env_ref = env_ref

    def __call__(self, game, opp_id):
        env = self.env_ref
        saved = env.agent_id
        env.agent_id = opp_id
        obs = env._get_obs()
        mask = env.action_masks()
        env.agent_id = saved
        action, _ = self.model.predict(obs, action_masks=mask, deterministic=False)
        valid = game.get_valid_actions()
        if int(action) in valid:
            return int(action)
        return np.random.choice(valid)


class SelfPlayMetricsCallback(BaseCallback):
    """Snapshot + periodic eval (vs random) with attack rate tracking."""
    def __init__(self, raw_env, snapshot_interval=500_000, eval_interval=500_000,
                 eval_games=100, warmup_steps=500_000, verbose=1):
        super().__init__(verbose)
        self.raw_env = raw_env
        self.snapshot_interval = snapshot_interval
        self.eval_interval = eval_interval
        self.eval_games = eval_games
        self.warmup_steps = warmup_steps
        self._last_snapshot = 0
        self._last_eval = 0
        self.snapshots: list[str] = []
        self.metrics: list[dict] = []

    def _on_step(self):
        s = self.num_timesteps

        # Snapshot
        if s - self._last_snapshot >= self.snapshot_interval:
            self._last_snapshot = s
            name = f"sparse_{s // 1000}k"
            path = os.path.join(MODELS_DIR, name)
            self.model.save(path)
            self.snapshots.append(path + ".zip")
            print(f"\n[{s}] Snapshot: {name}")

            # Update opponent after warmup
            if s >= self.warmup_steps and self.snapshots:
                self._update_opponent()

        # Eval
        if s - self._last_eval >= self.eval_interval:
            self._last_eval = s
            wr, ar, wt = evaluate_detailed(self.model, self.eval_games)
            m = {"steps": s, "win_rate": wr, "attack_rate": ar, "win_types": wt}
            self.metrics.append(m)
            print(f"\n[{s}] vs Random: WR={wr:.1f}% | AttackRate={ar:.1f}% | {wt}")

        return True

    def _update_opponent(self):
        # 70% latest, 30% random from pool
        if np.random.random() < 0.7:
            path = self.snapshots[-1]
        else:
            path = np.random.choice(self.snapshots)
        try:
            opp_model = MaskablePPO.load(path)
            self.raw_env.opponent_policy = ModelOpponent(opp_model, self.raw_env)
            print(f"  Opponent → {os.path.basename(path)}")
        except Exception as e:
            print(f"  Opponent load failed: {e}")


def evaluate_detailed(model, n_games=100):
    raw_env = PTCGEnv(randomize_decks=True)
    env = ActionMasker(raw_env, lambda e: e.action_masks())

    wins = 0
    attack_opps = 0
    attacks_chosen = 0
    win_types = {"prize": 0, "no_pokemon": 0, "deckout": 0, "draw": 0, "loss": 0}

    for _ in range(n_games):
        obs, _ = env.reset()
        done = False
        steps = 0
        while not done and steps < 5000:
            mask = raw_env.action_masks()
            valid = np.where(mask)[0]
            attack_avail = any(ATTACK_BASE <= a <= ATTACK_BASE + 1 for a in valid)
            if attack_avail:
                attack_opps += 1
            action, _ = model.predict(obs, action_masks=mask, deterministic=False)
            action = int(action)
            if attack_avail and ATTACK_BASE <= action <= ATTACK_BASE + 1:
                attacks_chosen += 1
            obs, reward, done, _, _ = env.step(action)
            steps += 1

        g = raw_env.game
        if g.winner == raw_env.agent_id:
            wins += 1
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

    return (wins / n_games * 100,
            attacks_chosen / max(attack_opps, 1) * 100,
            win_types)


def print_game_log(model, n_games=10):
    raw_env = PTCGEnv(randomize_decks=True)
    env = ActionMasker(raw_env, lambda e: e.action_masks())

    for gn in range(n_games):
        obs, _ = env.reset()
        done = False
        steps = 0
        print(f"\n{'='*60}\nGame {gn+1}\n{'='*60}")
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
                an = me.active.card.name if me.active else "None"
                ah = me.active.current_hp if me.active else 0
                ae = me.active.total_energy() if me.active else 0
                on = opp.active.card.name if opp.active else "None"
                oh = opp.active.current_hp if opp.active else 0
                print(f"\nTurn {g.turn_count}: {an}(HP{ah},E{ae}) vs {on}(HP{oh})")

            from engine.actions import decode_action
            info = decode_action(action)
            if g.current_player == raw_env.agent_id:
                if info["type"] == "attack":
                    atk = ""
                    me = g.players[raw_env.agent_id]
                    if me.active and info["attack_idx"] < len(me.active.card.attacks):
                        atk = me.active.card.attacks[info["attack_idx"]].name
                    print(f"  -> ATTACK: {atk}")
                elif info["type"] == "end_turn":
                    flag = " ⚠️ COULD ATTACK!" if any(ATTACK_BASE <= a <= ATTACK_BASE + 1 for a in valid) else ""
                    print(f"  -> END TURN{flag}")
                elif info["type"] == "play_card":
                    me = g.players[raw_env.agent_id]
                    if info["hand_idx"] < len(me.hand):
                        print(f"  -> PLAY: {me.hand[info['hand_idx']].name}")
                elif "energy" in info["type"]:
                    print(f"  -> ENERGY")
                elif "evolve" in info["type"]:
                    print(f"  -> EVOLVE")

            obs, reward, done, _, _ = env.step(action)
            steps += 1

        winner = "AI" if g.winner == raw_env.agent_id else ("Opponent" if g.winner is not None else "Draw")
        print(f"  Result: {winner} (turns: {g.turn_count})")


def main():
    os.makedirs(MODELS_DIR, exist_ok=True)

    raw_env = PTCGEnv(randomize_decks=True)
    env = ActionMasker(raw_env, lambda e: e.action_masks())

    model = MaskablePPO(
        "MlpPolicy", env, verbose=1,
        learning_rate=1e-4,
        n_steps=2048,
        batch_size=128,
        n_epochs=5,
        gamma=0.995,
        gae_lambda=0.98,
        ent_coef=0.05,     # Higher entropy to prevent collapse
        vf_coef=0.5,
        max_grad_norm=0.5,
        clip_range=0.1,    # Tighter clipping for stability
        policy_kwargs=dict(net_arch=[256, 256]),
    )

    cb = SelfPlayMetricsCallback(
        raw_env=raw_env,
        snapshot_interval=500_000,
        eval_interval=500_000,
        eval_games=100,
        warmup_steps=1_000_000,  # 1M vs random first
    )

    total = 10_000_000
    print(f"=== Sparse Reward Self-Play Training ===")
    print(f"Total: {total/1e6:.0f}M steps")
    print(f"Reward: win +1.0 / loss -1.0 / prize ±0.1")
    print(f"Warmup: 1M steps vs random")
    print(f"Obs: {raw_env.observation_space.shape}")
    print()

    t0 = time.time()
    model.learn(total_timesteps=total, callback=cb)
    elapsed = time.time() - t0

    final_path = os.path.join(MODELS_DIR, "sparse_final")
    model.save(final_path)
    print(f"\nDone in {elapsed:.0f}s ({elapsed/60:.1f}min)")

    # Save metrics
    with open(os.path.join(MODELS_DIR, "sparse_metrics.json"), "w") as f:
        json.dump(cb.metrics, f, indent=2)

    # Final eval
    print("\n" + "=" * 60)
    print("FINAL EVALUATION (200 games)")
    print("=" * 60)
    wr, ar, wt = evaluate_detailed(model, 200)
    print(f"Win rate: {wr:.1f}%")
    print(f"Attack rate: {ar:.1f}%")
    print(f"Win types: {wt}")

    print("\n" + "=" * 60)
    print("GAME LOGS (10 games)")
    print("=" * 60)
    print_game_log(model, 10)


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--eval", type=str, help="Evaluate existing model")
    p.add_argument("--games", type=int, default=200)
    args = p.parse_args()

    if args.eval:
        model = MaskablePPO.load(args.eval)
        wr, ar, wt = evaluate_detailed(model, args.games)
        print(f"Win rate: {wr:.1f}%")
        print(f"Attack rate: {ar:.1f}%")
        print(f"Win types: {wt}")
        print_game_log(model, 10)
    else:
        main()
