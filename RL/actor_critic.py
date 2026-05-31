"""Advantage Actor-Critic (A2C) for discrete-action Gym environments.

Self-contained reference implementation. A shared-feature network produces both a
policy (actor) and a state-value estimate (critic). The actor is trained with the
policy-gradient objective using the advantage as the baseline-corrected signal;
the critic is regressed onto the bootstrapped return.

This file is standalone — it does not import from or depend on the rest of the
repository.

Usage:
    python actor_critic.py --env CartPole-v1 --episodes 500
    python actor_critic.py --env LunarLander-v2 --episodes 1500 --lr 7e-4
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass

import gymnasium as gym
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.distributions import Categorical


# ----------------------------------------------------------------------------- #
# Model
# ----------------------------------------------------------------------------- #
class ActorCritic(nn.Module):
    """Shared trunk with separate policy (actor) and value (critic) heads."""

    def __init__(self, obs_dim: int, n_actions: int, hidden: int = 128) -> None:
        super().__init__()
        self.shared = nn.Sequential(
            nn.Linear(obs_dim, hidden),
            nn.Tanh(),
            nn.Linear(hidden, hidden),
            nn.Tanh(),
        )
        self.actor = nn.Linear(hidden, n_actions)   # logits over actions
        self.critic = nn.Linear(hidden, 1)           # state-value V(s)

    def forward(self, obs: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        features = self.shared(obs)
        logits = self.actor(features)
        value = self.critic(features).squeeze(-1)
        return logits, value

    def act(self, obs: torch.Tensor) -> tuple[int, torch.Tensor, torch.Tensor, torch.Tensor]:
        """Sample an action; return (action, log_prob, entropy, value)."""
        logits, value = self.forward(obs)
        dist = Categorical(logits=logits)
        action = dist.sample()
        return int(action.item()), dist.log_prob(action), dist.entropy(), value


# ----------------------------------------------------------------------------- #
# Rollout storage + advantage estimation
# ----------------------------------------------------------------------------- #
@dataclass
class Rollout:
    log_probs: list[torch.Tensor]
    values: list[torch.Tensor]
    rewards: list[float]
    entropies: list[torch.Tensor]
    dones: list[bool]

    @classmethod
    def empty(cls) -> "Rollout":
        return cls([], [], [], [], [])

    def add(self, log_prob, value, reward, entropy, done) -> None:
        self.log_probs.append(log_prob)
        self.values.append(value)
        self.rewards.append(reward)
        self.entropies.append(entropy)
        self.dones.append(done)

    def __len__(self) -> int:
        return len(self.rewards)


def compute_returns(rollout: Rollout, bootstrap_value: float, gamma: float) -> torch.Tensor:
    """Discounted returns with bootstrap, reset at episode boundaries."""
    returns: list[float] = []
    running = bootstrap_value
    for reward, done in zip(reversed(rollout.rewards), reversed(rollout.dones)):
        running = reward + gamma * running * (0.0 if done else 1.0)
        returns.append(running)
    returns.reverse()
    return torch.tensor(returns, dtype=torch.float32)


# ----------------------------------------------------------------------------- #
# Training
# ----------------------------------------------------------------------------- #
@dataclass
class Config:
    env: str = "CartPole-v1"
    episodes: int = 500
    rollout_len: int = 32
    gamma: float = 0.99
    lr: float = 3e-4
    value_coef: float = 0.5
    entropy_coef: float = 0.01
    max_grad_norm: float = 0.5
    hidden: int = 128
    seed: int = 0
    log_every: int = 10


def train(cfg: Config) -> ActorCritic:
    torch.manual_seed(cfg.seed)
    np.random.seed(cfg.seed)

    env = gym.make(cfg.env)
    obs_dim = int(np.prod(env.observation_space.shape))
    n_actions = env.action_space.n

    model = ActorCritic(obs_dim, n_actions, hidden=cfg.hidden)
    optimizer = torch.optim.Adam(model.parameters(), lr=cfg.lr)

    obs, _ = env.reset(seed=cfg.seed)
    episode_return = 0.0
    recent_returns: list[float] = []

    for episode in range(cfg.episodes):
        rollout = Rollout.empty()

        # --- collect a fixed-length rollout -------------------------------- #
        for _ in range(cfg.rollout_len):
            obs_t = torch.as_tensor(obs, dtype=torch.float32)
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

        # --- bootstrap value of the state we stopped on -------------------- #
        with torch.no_grad():
            _, bootstrap_value = model.forward(torch.as_tensor(obs, dtype=torch.float32))
            bootstrap = 0.0 if rollout.dones[-1] else float(bootstrap_value.item())

        returns = compute_returns(rollout, bootstrap, cfg.gamma)
        values = torch.stack(rollout.values)
        log_probs = torch.stack(rollout.log_probs)
        entropies = torch.stack(rollout.entropies)

        advantages = returns - values
        # normalize advantages for a more stable policy gradient
        if advantages.numel() > 1:
            advantages = (advantages - advantages.mean()) / (advantages.std() + 1e-8)

        # --- losses -------------------------------------------------------- #
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
    return model


# ----------------------------------------------------------------------------- #
# Evaluation
# ----------------------------------------------------------------------------- #
@torch.no_grad()
def evaluate(model: ActorCritic, env_id: str, episodes: int = 10, render: bool = False) -> float:
    env = gym.make(env_id, render_mode="human" if render else None)
    total = 0.0
    for _ in range(episodes):
        obs, _ = env.reset()
        done = False
        while not done:
            logits, _ = model.forward(torch.as_tensor(obs, dtype=torch.float32))
            action = int(torch.argmax(logits).item())  # greedy at eval time
            obs, reward, terminated, truncated, _ = env.step(action)
            total += float(reward)
            done = terminated or truncated
    env.close()
    return total / episodes


# ----------------------------------------------------------------------------- #
# CLI
# ----------------------------------------------------------------------------- #
def parse_args() -> Config:
    p = argparse.ArgumentParser(description="Advantage Actor-Critic (A2C)")
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
    p.add_argument("--eval-episodes", type=int, default=10)
    p.add_argument("--render", action="store_true", help="render greedy eval episodes")
    args = p.parse_args()
    return Config(
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
    ), args


def main() -> None:
    cfg, args = parse_args()
    print(f"Training A2C on {cfg.env} for {cfg.episodes} episodes…")
    model = train(cfg)
    avg = evaluate(model, cfg.env, episodes=args.eval_episodes, render=args.render)
    print(f"\nGreedy eval over {args.eval_episodes} episodes: avg return {avg:.1f}")


if __name__ == "__main__":
    main()
