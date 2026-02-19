"""PPO自己対戦学習スクリプト"""
from __future__ import annotations
import sys
import os
import numpy as np

# プロジェクトルートをパスに追加
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from env.ptcg_env import PTCGEnv
from engine.actions import NUM_ACTIONS


def random_test(n_episodes: int = 100):
    """ランダムエージェントでテスト"""
    env = PTCGEnv()
    wins = 0
    draws = 0
    total_turns = 0
    
    for ep in range(n_episodes):
        obs, _ = env.reset()
        done = False
        while not done:
            mask = env.action_masks()
            valid = np.where(mask)[0]
            action = np.random.choice(valid)
            obs, reward, done, truncated, info = env.step(action)
        
        if env.game.winner == 0:
            wins += 1
        elif env.game.winner is None:
            draws += 1
        total_turns += env.game.turn_count
    
    print(f"Random vs Random ({n_episodes} games):")
    print(f"  Player 0 wins: {wins} ({wins/n_episodes*100:.1f}%)")
    print(f"  Draws: {draws} ({draws/n_episodes*100:.1f}%)")
    print(f"  Avg turns: {total_turns/n_episodes:.1f}")


def train_ppo(total_timesteps: int = 50000):
    """PPOで学習（sb3-contrib MaskablePPO使用）"""
    try:
        from sb3_contrib import MaskablePPO
        from sb3_contrib.common.wrappers import ActionMasker
    except ImportError:
        print("sb3-contrib not installed. Installing...")
        os.system("uv pip install 'sb3-contrib[extra]' --python /opt/homebrew/bin/python3.12")
        from sb3_contrib import MaskablePPO
        from sb3_contrib.common.wrappers import ActionMasker
    
    def mask_fn(env: PTCGEnv) -> np.ndarray:
        return env.action_masks()
    
    env = PTCGEnv()
    env = ActionMasker(env, mask_fn)
    
    model = MaskablePPO(
        "MlpPolicy",
        env,
        verbose=1,
        learning_rate=3e-4,
        n_steps=512,
        batch_size=64,
        n_epochs=10,
        gamma=0.99,
        ent_coef=0.05,  # 探索促進
        # tensorboard_log="./logs/",
    )
    
    print(f"Training MaskablePPO for {total_timesteps} timesteps...")
    model.learn(total_timesteps=total_timesteps)
    model.save("ppo_ptcg")
    print("Model saved to ppo_ptcg.zip")
    
    # 学習後の評価
    print("\nEvaluating trained agent vs random...")
    evaluate(model, n_episodes=200)


def evaluate(model, n_episodes: int = 200):
    """学習済みモデルの評価"""
    from sb3_contrib.common.wrappers import ActionMasker
    
    def mask_fn(env):
        return env.action_masks()
    
    env = PTCGEnv()
    raw_env = env  # マスクなしのenv参照保持
    env = ActionMasker(env, mask_fn)
    
    wins = 0
    for ep in range(n_episodes):
        obs, _ = env.reset()
        done = False
        while not done:
            action, _ = model.predict(obs, action_masks=raw_env.action_masks())
            obs, reward, done, truncated, info = env.step(action)
        if raw_env.game.winner == 0:
            wins += 1
    
    print(f"Trained agent vs Random ({n_episodes} games):")
    print(f"  Win rate: {wins/n_episodes*100:.1f}%")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", default="test", choices=["test", "train"])
    parser.add_argument("--timesteps", type=int, default=50000)
    args = parser.parse_args()
    
    if args.mode == "test":
        random_test(500)
    elif args.mode == "train":
        train_ppo(args.timesteps)
