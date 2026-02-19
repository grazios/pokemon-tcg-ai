"""模倣学習 (Behavioral Cloning) - エキスパートデータでNNを事前学習"""
from __future__ import annotations
import sys, os, json, time
import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.actions import NUM_ACTIONS
from env.ptcg_env import PTCGEnv


# =====================================================
# Dataset
# =====================================================

class ExpertDataset(Dataset):
    def __init__(self, data_path: str = "data/expert_games/expert_data.npz"):
        data = np.load(data_path)
        self.obs = torch.from_numpy(data["obs"])          # (N, 471)
        self.actions = torch.from_numpy(data["actions"])   # (N,)
        self.masks = torch.from_numpy(data["masks"])       # (N, 256)
    
    def __len__(self):
        return len(self.obs)
    
    def __getitem__(self, idx):
        return self.obs[idx], self.actions[idx], self.masks[idx]


# =====================================================
# Network (same architecture as MaskablePPO MlpPolicy [256, 256])
# =====================================================

class ImitationPolicy(nn.Module):
    """PPOと同じMLP構造: obs→256→256→action_logits"""
    def __init__(self, obs_size: int = 471, action_size: int = NUM_ACTIONS):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(obs_size, 256),
            nn.ReLU(),
            nn.Linear(256, 256),
            nn.ReLU(),
        )
        self.action_head = nn.Linear(256, action_size)
        self.value_head = nn.Linear(256, 1)  # PPO互換のためvalue headも用意
    
    def forward(self, obs):
        features = self.net(obs)
        return self.action_head(features)
    
    def forward_with_value(self, obs):
        features = self.net(obs)
        return self.action_head(features), self.value_head(features)


# =====================================================
# Training
# =====================================================

def masked_cross_entropy(logits: torch.Tensor, targets: torch.Tensor,
                         masks: torch.Tensor) -> torch.Tensor:
    """valid_mask内のアクションのみ対象のCrossEntropyLoss"""
    # Mask out invalid actions with large negative value
    masked_logits = logits.clone()
    masked_logits[~masks] = -1e8
    return nn.functional.cross_entropy(masked_logits, targets)


def train_imitation(
    data_path: str = "data/expert_games/expert_data.npz",
    output_path: str = "models/imitation_pretrained.pt",
    batch_size: int = 256,
    n_epochs: int = 10,
    lr: float = 3e-4,
    device: str = "auto",
):
    """模倣学習のメイン"""
    if device == "auto":
        if torch.backends.mps.is_available():
            device = "mps"
        elif torch.cuda.is_available():
            device = "cuda"
        else:
            device = "cpu"
    
    print(f"Device: {device}")
    
    # Load data
    dataset = ExpertDataset(data_path)
    print(f"Dataset size: {len(dataset)} samples")
    
    # Split: 90% train, 10% val
    n_val = max(1, len(dataset) // 10)
    n_train = len(dataset) - n_val
    train_set, val_set = torch.utils.data.random_split(dataset, [n_train, n_val])
    
    train_loader = DataLoader(train_set, batch_size=batch_size, shuffle=True, num_workers=0)
    val_loader = DataLoader(val_set, batch_size=batch_size, shuffle=False, num_workers=0)
    
    # Model
    model = ImitationPolicy().to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=lr)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=n_epochs)
    
    print(f"Model params: {sum(p.numel() for p in model.parameters()):,}")
    
    best_val_acc = 0.0
    t0 = time.time()
    
    for epoch in range(n_epochs):
        # Train
        model.train()
        total_loss = 0.0
        correct = 0
        total = 0
        
        for obs, actions, masks in train_loader:
            obs = obs.to(device)
            actions = actions.to(device)
            masks = masks.to(device)
            
            logits = model(obs)
            loss = masked_cross_entropy(logits, actions, masks)
            
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
            
            total_loss += loss.item() * obs.size(0)
            
            # Accuracy (masked)
            masked_logits = logits.clone()
            masked_logits[~masks] = -1e8
            pred = masked_logits.argmax(dim=1)
            correct += (pred == actions).sum().item()
            total += obs.size(0)
        
        scheduler.step()
        train_loss = total_loss / total
        train_acc = correct / total
        
        # Validation
        model.eval()
        val_correct = 0
        val_total = 0
        val_loss = 0.0
        
        with torch.no_grad():
            for obs, actions, masks in val_loader:
                obs = obs.to(device)
                actions = actions.to(device)
                masks = masks.to(device)
                
                logits = model(obs)
                loss = masked_cross_entropy(logits, actions, masks)
                val_loss += loss.item() * obs.size(0)
                
                masked_logits = logits.clone()
                masked_logits[~masks] = -1e8
                pred = masked_logits.argmax(dim=1)
                val_correct += (pred == actions).sum().item()
                val_total += obs.size(0)
        
        val_loss /= val_total
        val_acc = val_correct / val_total
        
        elapsed = time.time() - t0
        print(f"Epoch {epoch+1}/{n_epochs} | "
              f"Train Loss: {train_loss:.4f} Acc: {train_acc:.3f} | "
              f"Val Loss: {val_loss:.4f} Acc: {val_acc:.3f} | "
              f"Time: {elapsed:.1f}s")
        
        if val_acc > best_val_acc:
            best_val_acc = val_acc
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            torch.save(model.state_dict(), output_path)
    
    print(f"\nBest val accuracy: {best_val_acc:.3f}")
    print(f"Model saved to: {output_path}")
    
    return model


# =====================================================
# Convert to MaskablePPO compatible format
# =====================================================

def convert_to_sb3(
    pt_path: str = "models/imitation_pretrained.pt",
    sb3_path: str = "models/imitation_pretrained.zip",
):
    """PyTorchモデルをMaskablePPOの初期重みとしてロード可能な形式に変換"""
    from sb3_contrib import MaskablePPO
    from sb3_contrib.common.wrappers import ActionMasker
    
    def mask_fn(env):
        return env.action_masks()
    
    # Create a fresh MaskablePPO with same architecture
    env = PTCGEnv(randomize_decks=True)
    env = ActionMasker(env, mask_fn)
    
    ppo_model = MaskablePPO(
        "MlpPolicy", env, verbose=0,
        learning_rate=3e-4,
        policy_kwargs=dict(net_arch=[256, 256]),
    )
    
    # Load our trained weights
    state_dict = torch.load(pt_path, map_location="cpu", weights_only=True)
    
    # Map our weights to SB3's naming convention
    # Our: net.0.weight/bias, net.2.weight/bias, action_head.weight/bias, value_head.weight/bias
    # SB3 MlpPolicy:
    #   policy.mlp_extractor.policy_net.0.weight/bias  (256x471)
    #   policy.mlp_extractor.policy_net.2.weight/bias  (256x256)
    #   policy.mlp_extractor.value_net.0.weight/bias   (256x471)
    #   policy.mlp_extractor.value_net.2.weight/bias   (256x256)
    #   policy.action_net.weight/bias                  (256x256)
    #   policy.value_net.weight/bias                   (1x256)
    
    sb3_policy = ppo_model.policy
    
    # Copy shared feature extractor weights to both policy and value nets
    with torch.no_grad():
        # Policy net (feature extractor part)
        sb3_policy.mlp_extractor.policy_net[0].weight.copy_(state_dict["net.0.weight"])
        sb3_policy.mlp_extractor.policy_net[0].bias.copy_(state_dict["net.0.bias"])
        sb3_policy.mlp_extractor.policy_net[2].weight.copy_(state_dict["net.2.weight"])
        sb3_policy.mlp_extractor.policy_net[2].bias.copy_(state_dict["net.2.bias"])
        
        # Value net (copy same features)
        sb3_policy.mlp_extractor.value_net[0].weight.copy_(state_dict["net.0.weight"])
        sb3_policy.mlp_extractor.value_net[0].bias.copy_(state_dict["net.0.bias"])
        sb3_policy.mlp_extractor.value_net[2].weight.copy_(state_dict["net.2.weight"])
        sb3_policy.mlp_extractor.value_net[2].bias.copy_(state_dict["net.2.bias"])
        
        # Action head
        sb3_policy.action_net.weight.copy_(state_dict["action_head.weight"])
        sb3_policy.action_net.bias.copy_(state_dict["action_head.bias"])
        
        # Value head
        sb3_policy.value_net.weight.copy_(state_dict["value_head.weight"])
        sb3_policy.value_net.bias.copy_(state_dict["value_head.bias"])
    
    ppo_model.save(sb3_path.replace(".zip", ""))
    print(f"SB3 model saved to: {sb3_path}")
    return ppo_model


# =====================================================
# Evaluate imitation model
# =====================================================

def evaluate_imitation(pt_path: str = "models/imitation_pretrained.pt",
                       n_games: int = 200, device: str = "cpu") -> float:
    """模倣学習モデル vs ランダムの勝率"""
    model = ImitationPolicy()
    model.load_state_dict(torch.load(pt_path, map_location=device, weights_only=True))
    model.eval()
    model.to(device)
    
    env = PTCGEnv(randomize_decks=True)
    wins = 0
    
    for _ in range(n_games):
        try:
            obs, _ = env.reset()
            done = False
            steps = 0
            while not done and steps < 5000:
                mask = env.action_masks()
                with torch.no_grad():
                    obs_t = torch.from_numpy(obs).unsqueeze(0).to(device)
                    logits = model(obs_t)[0]
                    mask_t = torch.from_numpy(mask)
                    logits[~mask_t] = -1e8
                    action = logits.argmax().item()
                
                obs, reward, done, truncated, info = env.step(action)
                steps += 1
            if env.game.winner == env.agent_id:
                wins += 1
        except Exception:
            pass
    
    return wins / n_games


# =====================================================
# Self-play fine-tuning
# =====================================================

def train_selfplay(
    sb3_path: str = "models/imitation_pretrained",
    output_path: str = "models/imitation_selfplay_final",
    total_timesteps: int = 1_000_000,
):
    """模倣学習済みモデルからself-playでファインチューン"""
    from sb3_contrib import MaskablePPO
    from sb3_contrib.common.wrappers import ActionMasker
    
    def mask_fn(env):
        return env.action_masks()
    
    env = PTCGEnv(randomize_decks=True)
    env = ActionMasker(env, mask_fn)
    
    model = MaskablePPO.load(sb3_path, env=env)
    
    # Reduce learning rate for fine-tuning
    model.learning_rate = 1e-4
    model.ent_coef = 0.02
    
    print(f"Self-play training for {total_timesteps} steps...")
    model.learn(total_timesteps=total_timesteps)
    model.save(output_path)
    print(f"Model saved to: {output_path}.zip")
    
    return model


def evaluate_sb3(model_path: str, n_games: int = 200) -> float:
    """SB3モデル vs ランダムの勝率"""
    from sb3_contrib import MaskablePPO
    from sb3_contrib.common.wrappers import ActionMasker
    
    def mask_fn(env):
        return env.action_masks()
    
    raw_env = PTCGEnv(randomize_decks=True)
    env = ActionMasker(raw_env, mask_fn)
    model = MaskablePPO.load(model_path, env=env)
    
    wins = 0
    for _ in range(n_games):
        try:
            obs, _ = env.reset()
            done = False
            steps = 0
            while not done and steps < 5000:
                action, _ = model.predict(obs, action_masks=raw_env.action_masks())
                obs, reward, done, truncated, info = env.step(action)
                steps += 1
            if raw_env.game.winner == raw_env.agent_id:
                wins += 1
        except Exception:
            pass
    
    return wins / n_games


# =====================================================
# Full pipeline
# =====================================================

def full_pipeline():
    """Phase 1-4 全パイプライン実行"""
    print("=" * 60)
    print("Phase 1: Expert data generation")
    print("=" * 60)
    
    from train.generate_expert_data import generate_expert_games, evaluate_expert_vs_random
    
    # Evaluate expert
    print("\nEvaluating expert vs random...")
    expert_wr = evaluate_expert_vs_random(200)
    print(f"Expert vs Random: {expert_wr*100:.1f}%")
    
    # Generate data
    print("\nGenerating 1000 games...")
    stats = generate_expert_games(n_games=1000, save_text=True, verbose=True)
    print(f"Samples: {stats['total_samples']}")
    
    print("\n" + "=" * 60)
    print("Phase 2: Imitation Learning (Behavioral Cloning)")
    print("=" * 60)
    
    model = train_imitation(
        data_path="data/expert_games/expert_data.npz",
        output_path="models/imitation_pretrained.pt",
        batch_size=256,
        n_epochs=10,
    )
    
    # Evaluate imitation model
    print("\nEvaluating imitation model vs random...")
    imit_wr = evaluate_imitation("models/imitation_pretrained.pt", n_games=200)
    print(f"Imitation vs Random: {imit_wr*100:.1f}%")
    
    print("\n" + "=" * 60)
    print("Phase 3: Convert to SB3 + Self-Play")
    print("=" * 60)
    
    convert_to_sb3(
        pt_path="models/imitation_pretrained.pt",
        sb3_path="models/imitation_pretrained.zip",
    )
    
    train_selfplay(
        sb3_path="models/imitation_pretrained",
        output_path="models/imitation_selfplay_final",
        total_timesteps=1_000_000,
    )
    
    # Evaluate self-play model
    print("\nEvaluating self-play model vs random...")
    sp_wr = evaluate_sb3("models/imitation_selfplay_final", n_games=200)
    print(f"Imitation+Self-Play vs Random: {sp_wr*100:.1f}%")
    
    print("\n" + "=" * 60)
    print("Final Results")
    print("=" * 60)
    print(f"Expert (rule-based) vs Random: {expert_wr*100:.1f}%")
    print(f"Imitation model vs Random:     {imit_wr*100:.1f}%")
    print(f"Imitation+Self-Play vs Random: {sp_wr*100:.1f}%")


def claude_pipeline(n_games: int = 10, model: str = "claude-sonnet-4-20250514"):
    """Claude模倣学習パイプライン"""
    from train.generate_claude_data import generate_claude_games, evaluate_claude_vs_random

    print("=" * 60)
    print("Phase 1: Claude vs Random evaluation")
    print("=" * 60)
    eval_wr = evaluate_claude_vs_random(min(n_games, 5), model=model)

    print("\n" + "=" * 60)
    print(f"Phase 2: Generate Claude data ({n_games} games)")
    print("=" * 60)
    stats = generate_claude_games(n_games=n_games, model=model)

    print("\n" + "=" * 60)
    print("Phase 3: Imitation Learning from Claude data")
    print("=" * 60)
    il_model = train_imitation(
        data_path="data/claude_games/claude_data.npz",
        output_path="models/claude_imitation.pt",
        batch_size=128,
        n_epochs=20,
    )

    print("\nEvaluating Claude-imitation model vs random...")
    imit_wr = evaluate_imitation("models/claude_imitation.pt", n_games=200)
    print(f"Claude-Imitation vs Random: {imit_wr*100:.1f}%")

    print("\n" + "=" * 60)
    print("Phase 4: Convert + Self-Play")
    print("=" * 60)
    convert_to_sb3(
        pt_path="models/claude_imitation.pt",
        sb3_path="models/claude_imitation.zip",
    )
    train_selfplay(
        sb3_path="models/claude_imitation",
        output_path="models/claude_selfplay_final",
        total_timesteps=1_000_000,
    )

    sp_wr = evaluate_sb3("models/claude_selfplay_final", n_games=200)

    print("\n" + "=" * 60)
    print("Final Results")
    print("=" * 60)
    print(f"Claude vs Random:              {eval_wr*100:.1f}%")
    print(f"Claude-Imitation vs Random:    {imit_wr*100:.1f}%")
    print(f"Claude+Self-Play vs Random:    {sp_wr*100:.1f}%")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", default="train",
                        choices=["train", "convert", "selfplay", "eval", "pipeline", "claude"])
    parser.add_argument("--data", default="data/expert_games/expert_data.npz")
    parser.add_argument("--output", default="models/imitation_pretrained.pt")
    parser.add_argument("--epochs", type=int, default=10)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--lr", type=float, default=3e-4)
    parser.add_argument("--selfplay-steps", type=int, default=1_000_000)
    parser.add_argument("--eval-games", type=int, default=200)
    parser.add_argument("--claude-games", type=int, default=10)
    parser.add_argument("--claude-model", default="claude-sonnet-4-20250514")
    args = parser.parse_args()
    
    if args.mode == "claude":
        claude_pipeline(n_games=args.claude_games, model=args.claude_model)
    elif args.mode == "pipeline":
        full_pipeline()
    elif args.mode == "train":
        train_imitation(args.data, args.output, args.batch_size, args.epochs, args.lr)
    elif args.mode == "convert":
        convert_to_sb3()
    elif args.mode == "selfplay":
        train_selfplay(total_timesteps=args.selfplay_steps)
    elif args.mode == "eval":
        wr = evaluate_imitation(args.output, args.eval_games)
        print(f"Imitation vs Random: {wr*100:.1f}%")
