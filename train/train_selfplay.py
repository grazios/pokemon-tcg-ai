"""Self-Play学習スクリプト - Phase 3: AI同士の対戦で強化"""
from __future__ import annotations
import sys, os, json, time, argparse, copy
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sb3_contrib import MaskablePPO
from sb3_contrib.common.wrappers import ActionMasker
from sb3_contrib.common.maskable.callbacks import MaskableEvalCallback
from stable_baselines3.common.callbacks import BaseCallback
from env.ptcg_env import PTCGEnv
from engine.actions import NUM_ACTIONS

MODELS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "models")


# ──────────────────────────────────────────
# ELO rating system
# ──────────────────────────────────────────
class EloTracker:
    def __init__(self, k=32, default=1000):
        self.k = k
        self.default = default
        self.ratings: dict[str, float] = {"random": 800}

    def get(self, name: str) -> float:
        return self.ratings.get(name, self.default)

    def update(self, a: str, b: str, winner: str | None):
        ra, rb = self.get(a), self.get(b)
        ea = 1 / (1 + 10 ** ((rb - ra) / 400))
        eb = 1 - ea
        if winner == a:
            sa, sb = 1.0, 0.0
        elif winner == b:
            sa, sb = 0.0, 1.0
        else:
            sa, sb = 0.5, 0.5
        self.ratings[a] = ra + self.k * (sa - ea)
        self.ratings[b] = rb + self.k * (sb - eb)

    def save(self, path: str):
        with open(path, "w") as f:
            json.dump(self.ratings, f, indent=2)


# ──────────────────────────────────────────
# Opponent policy from a saved model
# ──────────────────────────────────────────
class ModelOpponent:
    """Wraps a MaskablePPO model to act as opponent_policy."""

    def __init__(self, model: MaskablePPO, env_ref: PTCGEnv):
        self.model = model
        self.env_ref = env_ref

    def __call__(self, game, opp_id):
        # Build obs from opponent's perspective
        obs = self._get_opp_obs(game, opp_id)
        mask = self._get_opp_mask(game, opp_id)
        action, _ = self.model.predict(obs, action_masks=mask, deterministic=False)
        valid = game.get_valid_actions()
        if int(action) in valid:
            return int(action)
        # Fallback to random if model picks invalid
        return np.random.choice(valid)

    def _get_opp_obs(self, game, opp_id):
        """Build observation from opp_id's perspective using a temp env trick."""
        env = self.env_ref
        saved = env.agent_id
        env.agent_id = opp_id
        obs = env._get_obs()
        env.agent_id = saved
        return obs

    def _get_opp_mask(self, game, opp_id):
        env = self.env_ref
        saved = env.agent_id
        env.agent_id = opp_id
        mask = env.action_masks()
        env.agent_id = saved
        return mask


# ──────────────────────────────────────────
# Opponent pool
# ──────────────────────────────────────────
class OpponentPool:
    def __init__(self, models_dir: str, latest_ratio: float = 0.8):
        self.models_dir = models_dir
        self.latest_ratio = latest_ratio
        self.snapshots: list[str] = []  # paths
        os.makedirs(models_dir, exist_ok=True)

    def add(self, path: str):
        self.snapshots.append(path)

    def sample_path(self) -> str | None:
        if not self.snapshots:
            return None
        if np.random.random() < self.latest_ratio and self.snapshots:
            return self.snapshots[-1]
        return np.random.choice(self.snapshots)


# ──────────────────────────────────────────
# Self-play callback
# ──────────────────────────────────────────
class SelfPlayCallback(BaseCallback):
    def __init__(self, pool: OpponentPool, raw_env: PTCGEnv,
                 snapshot_interval: int = 10000, warmup_steps: int = 20000,
                 elo: EloTracker | None = None, verbose=0):
        super().__init__(verbose)
        self.pool = pool
        self.raw_env = raw_env
        self.snapshot_interval = snapshot_interval
        self.warmup_steps = warmup_steps
        self.elo = elo
        self._last_snapshot = 0
        self._wins = 0
        self._games = 0

    def _on_step(self) -> bool:
        # Track wins
        dones = self.locals.get("dones", self.locals.get("done", None))
        if dones is not None:
            if isinstance(dones, np.ndarray):
                for i, d in enumerate(dones):
                    if d:
                        self._games += 1
                        infos = self.locals.get("infos", [])
                        # Check reward for win
                        rewards = self.locals.get("rewards", [])
                        if i < len(rewards) and rewards[i] > 0.5:
                            self._wins += 1
            elif dones:
                self._games += 1
                reward = self.locals.get("rewards", [0])[0] if isinstance(self.locals.get("rewards"), (list, np.ndarray)) else 0
                if reward > 0.5:
                    self._wins += 1

        # Snapshot & update opponent
        steps = self.num_timesteps
        if steps - self._last_snapshot >= self.snapshot_interval:
            self._last_snapshot = steps
            snap_name = f"snap_{steps // 1000}k"
            snap_path = os.path.join(self.pool.models_dir, snap_name)
            self.model.save(snap_path)
            self.pool.add(snap_path + ".zip")

            wr = self._wins / max(self._games, 1) * 100
            print(f"\n[{steps}] Snapshot saved: {snap_name} | Win rate: {wr:.1f}% ({self._wins}/{self._games})")

            # ELO update based on win rate vs current opponent
            if self.elo:
                games = max(self._games_at_snap, 1) if hasattr(self, '_games_at_snap') else max(self._games, 1)
                wins_count = self._wins_at_snap if hasattr(self, '_wins_at_snap') else self._wins
                # Simulate ELO matches based on actual results
                opp_name = self._current_opp_name if hasattr(self, '_current_opp_name') else "random"
                self.elo.ratings[snap_name] = self.elo.get(opp_name)
                for _ in range(wins_count):
                    self.elo.update(snap_name, opp_name, snap_name)
                for _ in range(games - wins_count):
                    self.elo.update(snap_name, opp_name, opp_name)
                print(f"  ELO: {self.elo.get(snap_name):.0f}")

            self._wins = 0
            self._games = 0

            self._games_at_snap = self._games
            self._wins_at_snap = self._wins

            # Update opponent
            if steps >= self.warmup_steps:
                self._update_opponent()
            else:
                self._current_opp_name = "random"
                print(f"  Warmup phase ({steps}/{self.warmup_steps}), opponent=random")

        return True

    def _update_opponent(self):
        path = self.pool.sample_path()
        if path and os.path.exists(path):
            try:
                opp_model = MaskablePPO.load(path)
                opp = ModelOpponent(opp_model, self.raw_env)
                self.raw_env.opponent_policy = opp
                opp_name = os.path.basename(path).replace(".zip", "")
                self._current_opp_name = opp_name
                print(f"  Opponent updated → {opp_name}")
            except Exception as e:
                print(f"  Failed to load opponent: {e}")


# ──────────────────────────────────────────
# Evaluation: model vs model
# ──────────────────────────────────────────
def evaluate_models(model1_path: str, model2_path: str, n_games: int = 100):
    """Evaluate two models against each other."""
    model1 = MaskablePPO.load(model1_path)
    model2 = MaskablePPO.load(model2_path)

    raw_env = PTCGEnv(randomize_decks=True)
    # model2 as opponent
    opp = ModelOpponent(model2, raw_env)
    raw_env.opponent_policy = opp
    env = ActionMasker(raw_env, lambda e: e.action_masks())

    wins1, wins2, draws = 0, 0, 0
    for g in range(n_games):
        obs, _ = env.reset()
        done = False
        steps = 0
        while not done and steps < 5000:
            mask = raw_env.action_masks()
            action, _ = model1.predict(obs, action_masks=mask, deterministic=False)
            obs, reward, done, trunc, info = env.step(action)
            steps += 1
        w = raw_env.game.winner
        if w == raw_env.agent_id:
            wins1 += 1
        elif w is not None:
            wins2 += 1
        else:
            draws += 1

    m1 = os.path.basename(model1_path)
    m2 = os.path.basename(model2_path)
    print(f"\n{m1} vs {m2} ({n_games} games):")
    print(f"  Model1 wins: {wins1} ({wins1/n_games*100:.1f}%)")
    print(f"  Model2 wins: {wins2} ({wins2/n_games*100:.1f}%)")
    print(f"  Draws: {draws} ({draws/n_games*100:.1f}%)")
    return wins1, wins2, draws


def evaluate_vs_random(model_path: str, n_games: int = 200):
    """Evaluate model vs random opponent."""
    model = MaskablePPO.load(model_path)
    raw_env = PTCGEnv(randomize_decks=True)  # opponent_policy=None → random
    env = ActionMasker(raw_env, lambda e: e.action_masks())

    wins = 0
    for g in range(n_games):
        obs, _ = env.reset()
        done = False
        steps = 0
        while not done and steps < 5000:
            mask = raw_env.action_masks()
            action, _ = model.predict(obs, action_masks=mask, deterministic=False)
            obs, reward, done, trunc, info = env.step(action)
            steps += 1
        if raw_env.game.winner == raw_env.agent_id:
            wins += 1

    print(f"\n{os.path.basename(model_path)} vs Random ({n_games} games): {wins/n_games*100:.1f}% win rate")
    return wins


# ──────────────────────────────────────────
# Main training loop
# ──────────────────────────────────────────
def train_selfplay(total_timesteps: int = 500000, snapshot_interval: int = 10000,
                   warmup_steps: int = 20000):
    os.makedirs(MODELS_DIR, exist_ok=True)

    raw_env = PTCGEnv(randomize_decks=True)
    env = ActionMasker(raw_env, lambda e: e.action_masks())

    elo = EloTracker()
    elo.ratings["current"] = 1000
    pool = OpponentPool(MODELS_DIR, latest_ratio=0.8)

    model = MaskablePPO(
        "MlpPolicy", env, verbose=1,
        learning_rate=3e-4,
        n_steps=1024,
        batch_size=128,
        n_epochs=10,
        gamma=0.99,
        ent_coef=0.05,
        policy_kwargs=dict(net_arch=[256, 256]),
    )

    callback = SelfPlayCallback(
        pool=pool, raw_env=raw_env,
        snapshot_interval=snapshot_interval,
        warmup_steps=warmup_steps,
        elo=elo,
    )

    print(f"=== Self-Play Training ===")
    print(f"Total timesteps: {total_timesteps}")
    print(f"Snapshot interval: {snapshot_interval}")
    print(f"Warmup (vs random): {warmup_steps}")
    print(f"Models dir: {MODELS_DIR}")
    print()

    t0 = time.time()
    model.learn(total_timesteps=total_timesteps, callback=callback)
    elapsed = time.time() - t0

    # Save final model
    final_path = os.path.join(MODELS_DIR, "selfplay_final")
    model.save(final_path)
    print(f"\nTraining complete in {elapsed:.0f}s")
    print(f"Final model: {final_path}.zip")
    print(f"Snapshots: {len(pool.snapshots)}")

    # Save ELO ratings
    elo_path = os.path.join(MODELS_DIR, "elo_ratings.json")
    elo.save(elo_path)
    print(f"ELO ratings: {elo_path}")

    # Print ELO progression
    print("\n=== ELO Progression ===")
    for name, rating in sorted(elo.ratings.items(), key=lambda x: x[1]):
        print(f"  {name}: {rating:.0f}")

    # Evaluate final model vs random
    print("\n=== Final Evaluation ===")
    evaluate_vs_random(final_path + ".zip", n_games=200)

    # Evaluate against earliest snapshot
    if len(pool.snapshots) >= 2:
        print("\n=== Final vs First Snapshot ===")
        evaluate_models(final_path + ".zip", pool.snapshots[0], n_games=100)

    # ELO tournament: each snapshot vs random to build ELO
    print("\n=== ELO Tournament (each snapshot vs random, 50 games) ===")
    for snap_path in pool.snapshots[::max(1, len(pool.snapshots)//10)]:  # sample ~10
        name = os.path.basename(snap_path).replace(".zip", "")
        try:
            snap_model = MaskablePPO.load(snap_path)
            raw_e = PTCGEnv(randomize_decks=True)
            env_e = ActionMasker(raw_e, lambda e: e.action_masks())
            w = 0
            for _ in range(50):
                obs, _ = env_e.reset()
                done = False
                s = 0
                while not done and s < 5000:
                    mask = raw_e.action_masks()
                    a, _ = snap_model.predict(obs, action_masks=mask, deterministic=False)
                    obs, r, done, tr, info = env_e.step(a)
                    s += 1
                if raw_e.game.winner == raw_e.agent_id:
                    w += 1
            wr = w / 50 * 100
            # Update ELO: snapshot vs random
            for _ in range(w):
                elo.update(name, "random", name)
            for _ in range(50 - w):
                elo.update(name, "random", "random")
            print(f"  {name}: {wr:.0f}% vs random, ELO={elo.get(name):.0f}")
        except:
            pass

    elo.save(elo_path)
    print(f"\nFinal ELO ratings saved to {elo_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Self-Play Training for Pokemon TCG AI")
    parser.add_argument("--mode", default="train", choices=["train", "eval"])
    parser.add_argument("--timesteps", type=int, default=500000)
    parser.add_argument("--snapshot-interval", type=int, default=10000)
    parser.add_argument("--warmup", type=int, default=20000)
    parser.add_argument("--model1", type=str, help="Model 1 path for eval mode")
    parser.add_argument("--model2", type=str, help="Model 2 path for eval mode")
    parser.add_argument("--games", type=int, default=100, help="Number of games for eval")
    args = parser.parse_args()

    if args.mode == "eval":
        if args.model1 and args.model2:
            evaluate_models(args.model1, args.model2, args.games)
        elif args.model1:
            evaluate_vs_random(args.model1, args.games)
        else:
            print("Eval mode requires --model1 (and optionally --model2)")
    else:
        train_selfplay(args.timesteps, args.snapshot_interval, args.warmup)
