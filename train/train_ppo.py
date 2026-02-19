"""PPO学習スクリプト - Phase 2: 3デッキ総当たり"""
from __future__ import annotations
import sys
import os
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from env.ptcg_env import PTCGEnv
from engine.actions import NUM_ACTIONS, END_TURN


def random_test(n_episodes: int = 100):
    """ランダムエージェントでテスト"""
    env = PTCGEnv(randomize_decks=True)
    wins = {0: 0, 1: 0, None: 0}
    total_turns = 0
    errors = 0
    
    for ep in range(n_episodes):
        try:
            obs, _ = env.reset()
            done = False
            steps = 0
            while not done and steps < 5000:
                mask = env.action_masks()
                valid = np.where(mask)[0]
                if len(valid) == 0:
                    break
                action = np.random.choice(valid)
                obs, reward, done, truncated, info = env.step(action)
                steps += 1
            
            winner = env.game.winner
            if winner == env.agent_id:
                wins[0] = wins.get(0, 0) + 1
            elif winner is not None:
                wins[1] = wins.get(1, 0) + 1
            else:
                wins[None] = wins.get(None, 0) + 1
            total_turns += env.game.turn_count
        except Exception as e:
            errors += 1
            if errors <= 3:
                print(f"Error in episode {ep}: {e}")
    
    total = n_episodes - errors
    if total > 0:
        print(f"Random vs Random ({n_episodes} games, {errors} errors):")
        print(f"  Agent wins: {wins[0]} ({wins[0]/total*100:.1f}%)")
        print(f"  Opponent wins: {wins[1]} ({wins[1]/total*100:.1f}%)")
        print(f"  Draws: {wins[None]} ({wins.get(None,0)/total*100:.1f}%)")
        print(f"  Avg turns: {total_turns/total:.1f}")


def train_ppo(total_timesteps: int = 200000):
    """PPOで学習"""
    try:
        from sb3_contrib import MaskablePPO
        from sb3_contrib.common.wrappers import ActionMasker
    except ImportError:
        print("Installing sb3-contrib...")
        os.system("pip install 'sb3-contrib'")
        from sb3_contrib import MaskablePPO
        from sb3_contrib.common.wrappers import ActionMasker
    
    def mask_fn(env: PTCGEnv) -> np.ndarray:
        return env.action_masks()
    
    env = PTCGEnv(randomize_decks=True)
    env = ActionMasker(env, mask_fn)
    
    model = MaskablePPO(
        "MlpPolicy",
        env,
        verbose=1,
        learning_rate=3e-4,
        n_steps=1024,
        batch_size=128,
        n_epochs=10,
        gamma=0.99,
        ent_coef=0.05,
        policy_kwargs=dict(net_arch=[256, 256]),
    )
    
    print(f"Training MaskablePPO for {total_timesteps} timesteps...")
    print(f"Observation space: {env.observation_space}")
    print(f"Action space: {env.action_space}")
    model.learn(total_timesteps=total_timesteps)
    model.save("ppo_ptcg_phase2")
    print("Model saved to ppo_ptcg_phase2.zip")
    
    print("\nEvaluating trained agent vs random...")
    evaluate(model, n_episodes=200)


def evaluate(model, n_episodes: int = 200):
    from sb3_contrib.common.wrappers import ActionMasker
    
    def mask_fn(env):
        return env.action_masks()
    
    raw_env = PTCGEnv(randomize_decks=True)
    env = ActionMasker(raw_env, mask_fn)
    
    wins = 0
    for ep in range(n_episodes):
        obs, _ = env.reset()
        done = False
        steps = 0
        while not done and steps < 5000:
            action, _ = model.predict(obs, action_masks=raw_env.action_masks())
            obs, reward, done, truncated, info = env.step(action)
            steps += 1
        if raw_env.game.winner == raw_env.agent_id:
            wins += 1
    
    print(f"Trained agent vs Random ({n_episodes} games):")
    print(f"  Win rate: {wins/n_episodes*100:.1f}%")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", default="test", choices=["test", "train"])
    parser.add_argument("--timesteps", type=int, default=200000)
    parser.add_argument("--episodes", type=int, default=100)
    args = parser.parse_args()
    
    if args.mode == "test":
        random_test(args.episodes)
    elif args.mode == "train":
        train_ppo(args.timesteps)
