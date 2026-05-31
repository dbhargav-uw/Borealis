"""Train the Actor-Critic on Apple Silicon (MPS), saving a .pt checkpoint.

Device-aware training loop that reuses the model from `actor_critic.py`. Defaults
to the MPS (Metal) backend on Apple Silicon, falling back to CUDA then CPU. On
completion it writes a checkpoint (`--out`, default `checkpoint.pt`) containing the
model weights plus the architecture/config needed to reload it.

Standalone — no dependency on the rest of the repository.

Usage:
    python train_mps.py --env CartPole-v1 --episodes 500 --out checkpoint.pt
    python train_mps.py --device cpu                 # force a backend
    python train_mps.py --env LunarLander-v2 --episodes 1500 --lr 7e-4
"""

from __future__ import annotations

import argparse

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

from actor_critic import ActorCritic, Config, Rollout, compute_returns

# gymnasium is imported lazily inside train_on_device so this module's helpers
# (pick_device, save_checkpoint, load_checkpoint) work without it installed.


def pick_device(requested: str | None) -> torch.device:
    """Resolve the compute device: explicit request, else MPS > CUDA > CPU."""
    if requested and requested != "auto":
        return torch.device(requested)
    if torch.backends.mps.is_available():
        return torch.device("mps")
    if torch.cuda.is_available():
        return torch.device("cuda")
    return torch.device("cpu")


def save_checkpoint(path: str, model: ActorCritic, cfg: Config, obs_dim: int, n_actions: int) -> None:
    """Persist weights plus everything needed to rebuild the model."""
    torch.save(
        {
            "model_state_dict": model.state_dict(),
            "obs_dim": obs_dim,
            "n_actions": n_actions,
            "hidden": cfg.hidden,
            "env": cfg.env,
            "config": vars(cfg),
        },
        path,
    )
    print(f"saved checkpoint -> {path}")


def load_checkpoint(path: str, device: torch.device | str = "cpu") -> ActorCritic:
    """Rebuild an ActorCritic from a checkpoint written by save_checkpoint."""
    ckpt = torch.load(path, map_location=device, weights_only=False)
    model = ActorCritic(ckpt["obs_dim"], ckpt["n_actions"], hidden=ckpt["hidden"])
    model.load_state_dict(ckpt["model_state_dict"])
    return model.to(device)


def train_on_device(cfg: Config, device: torch.device, out_path: str) -> ActorCritic:
    import gymnasium as gym

    torch.manual_seed(cfg.seed)
    np.random.seed(cfg.seed)

    env = gym.make(cfg.env)
    obs_dim = int(np.prod(env.observation_space.shape))
    n_actions = env.action_space.n

    model = ActorCritic(obs_dim, n_actions, hidden=cfg.hidden).to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=cfg.lr)

    obs, _ = env.reset(seed=cfg.seed)
    episode_return = 0.0
    recent_returns: list[float] = []

    for episode in range(cfg.episodes):
        rollout = Rollout.empty()

        for _ in range(cfg.rollout_len):
            obs_t = torch.as_tensor(obs, dtype=torch.float32, device=device)
            action, log_prob, entropy, value = model.act(obs_t)
            next_obs, reward, terminated, truncated, _ = env.step(action)
            done = terminated or truncated

            rollout.add(log_prob, value, float(reward), entropy, done)
            episode_return += float(reward)
            obs = next_obs

            if done:
                recent_returns.append(episode_return)
                episode_return = 0.0
                obs, _ = env.reset()

        with torch.no_grad():
            obs_t = torch.as_tensor(obs, dtype=torch.float32, device=device)
            _, bootstrap_value = model.forward(obs_t)
            bootstrap = 0.0 if rollout.dones[-1] else float(bootstrap_value.item())

        returns = compute_returns(rollout, bootstrap, cfg.gamma).to(device)
        values = torch.stack(rollout.values)
        log_probs = torch.stack(rollout.log_probs)
        entropies = torch.stack(rollout.entropies)

        advantages = returns - values
        if advantages.numel() > 1:
            advantages = (advantages - advantages.mean()) / (advantages.std() + 1e-8)

        policy_loss = -(log_probs * advantages.detach()).mean()
        value_loss = F.mse_loss(values, returns)
        entropy_bonus = entropies.mean()
        loss = policy_loss + cfg.value_coef * value_loss - cfg.entropy_coef * entropy_bonus

        optimizer.zero_grad()
        loss.backward()
        nn.utils.clip_grad_norm_(model.parameters(), cfg.max_grad_norm)
        optimizer.step()

        if (episode + 1) % cfg.log_every == 0 and recent_returns:
            avg = float(np.mean(recent_returns[-20:]))
            print(
                f"ep {episode + 1:4d} | avg_return {avg:7.1f} | "
                f"policy_loss {policy_loss.item():+.3f} | "
                f"value_loss {value_loss.item():.3f} | "
                f"entropy {entropy_bonus.item():.3f}"
            )

    env.close()
    save_checkpoint(out_path, model, cfg, obs_dim, n_actions)
    return model


def parse_args():
    p = argparse.ArgumentParser(description="Train A2C on MPS (Apple Silicon)")
    p.add_argument("--env", default="CartPole-v1")
    p.add_argument("--episodes", type=int, default=500)
    p.add_argument("--rollout-len", type=int, default=32)
    p.add_argument("--gamma", type=float, default=0.99)
    p.add_argument("--lr", type=float, default=3e-4)
    p.add_argument("--value-coef", type=float, default=0.5)
    p.add_argument("--entropy-coef", type=float, default=0.01)
    p.add_argument("--max-grad-norm", type=float, default=0.5)
    p.add_argument("--hidden", type=int, default=128)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--log-every", type=int, default=10)
    p.add_argument("--device", default="auto", help="auto | mps | cuda | cpu")
    p.add_argument("--out", default="checkpoint.pt", help="checkpoint output path")
    args = p.parse_args()
    cfg = Config(
        env=args.env,
        episodes=args.episodes,
        rollout_len=args.rollout_len,
        gamma=args.gamma,
        lr=args.lr,
        value_coef=args.value_coef,
        entropy_coef=args.entropy_coef,
        max_grad_norm=args.max_grad_norm,
        hidden=args.hidden,
        seed=args.seed,
        log_every=args.log_every,
    )
    return cfg, args


def main() -> None:
    cfg, args = parse_args()
    device = pick_device(args.device)
    print(f"Training A2C on {cfg.env} for {cfg.episodes} episodes (device: {device})…")
    train_on_device(cfg, device, args.out)


if __name__ == "__main__":
    main()
