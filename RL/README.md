# RL — Actor-Critic

## Contents
- `actor_critic.py` — Advantage Actor-Critic (A2C) for discrete-action Gym
  environments. A shared-trunk network with a policy head (actor) and a value
  head (critic). Trains on fixed-length rollouts with bootstrapped, advantage-
  normalized policy gradients, a value-regression loss, and an entropy bonus.
- `train_mps.py` — device-aware training (defaults to Apple-Silicon **MPS**,
  falls back to CUDA then CPU) that reuses the model from `actor_critic.py` and
  writes a `.pt` checkpoint with the weights + architecture/config to reload it.
- `RL_model.pt` — a sample CartPole-v1 checkpoint (dims: obs_dim 4, n_actions 2,
  hidden 128). Load it with `train_mps.load_checkpoint`.

## Setup
```bash
cd RL
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## Run
```bash
# CPU/auto trainer with greedy eval
python actor_critic.py --env CartPole-v1 --episodes 500
python actor_critic.py --env LunarLander-v2 --episodes 1500 --lr 7e-4   # needs gymnasium[box2d]
python actor_critic.py --env CartPole-v1 --episodes 500 --render        # render greedy eval

# MPS (Apple Silicon) trainer — saves a checkpoint
python train_mps.py --env CartPole-v1 --episodes 500 --out checkpoint.pt
python train_mps.py --device cpu                                        # force a backend
```

Reload a checkpoint:
```python
from train_mps import load_checkpoint
model = load_checkpoint("RL_model.pt", device="cpu")
```

Key flags: `--gamma`, `--lr`, `--rollout-len`, `--entropy-coef`,
`--value-coef`, `--max-grad-norm`, `--hidden`, `--seed`. See
`python actor_critic.py --help`.

## Algorithm notes
- **Actor** maximizes `E[log π(a|s) · A(s,a)]` where the advantage
  `A = R - V(s)` uses the critic as a baseline; advantages are normalized per
  rollout for stability.
- **Critic** regresses `V(s)` onto the discounted bootstrapped return.
- The combined objective is `policy_loss + c_v · value_loss − c_e · entropy`,
  with gradient-norm clipping.
- Discrete action spaces only (uses a `Categorical` policy). Continuous-action
  variants would swap in a Gaussian policy head.
