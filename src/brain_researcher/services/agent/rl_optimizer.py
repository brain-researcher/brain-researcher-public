"""Reinforcement Learning-based planning optimization using IQL/CQL.

This module implements offline RL algorithms for optimizing agent planning
decisions based on historical execution data.
"""

import json
import logging
import pickle
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import DataLoader, Dataset

logger = logging.getLogger(__name__)


@dataclass
class State:
    """RL state representation."""

    query_embedding: np.ndarray
    dataset_features: Dict[str, float]
    system_load: Dict[str, float]
    context_features: Dict[str, Any]
    timestamp: datetime = field(default_factory=datetime.now)

    def to_tensor(self) -> torch.Tensor:
        """Convert state to tensor."""
        # Use to_vector for consistency
        return torch.tensor(self.to_vector(), dtype=torch.float32)

    def to_vector(self) -> np.ndarray:
        """Convert state to numpy vector (compatibility method)."""
        features = []

        # Query embedding
        if isinstance(self.query_embedding, np.ndarray):
            features.extend(self.query_embedding.tolist())
        else:
            features.extend(self.query_embedding)

        # Only add extra features if they exist and have values
        if self.dataset_features:
            features.extend([
                self.dataset_features.get('size_gb', 0),
                self.dataset_features.get('num_subjects', 0),
                self.dataset_features.get('num_sessions', 0),
                self.dataset_features.get('has_derivatives', 0)
            ])

        if self.system_load:
            features.extend([
                self.system_load.get('cpu_percent', 0),
                self.system_load.get('memory_percent', 0),
                self.system_load.get('gpu_percent', 0)
            ])

        return np.array(features, dtype=np.float32)


@dataclass
class Action:
    """RL action representation."""

    tool_sequence: List[str]
    parameters: Dict[str, Any]
    resource_allocation: Dict[str, float]
    parallelization_strategy: str

    def to_index(self, action_space: List['Action']) -> int:
        """Convert action to index."""
        for i, a in enumerate(action_space):
            if a.tool_sequence == self.tool_sequence:
                return i
        return 0


@dataclass
class Transition:
    """State-action-reward transition."""

    state: State
    action: Action
    reward: float
    next_state: Optional[State]
    done: bool
    info: Dict[str, Any] = field(default_factory=dict)


class ReplayBuffer(Dataset):
    """Experience replay buffer for offline RL."""

    def __init__(self, capacity: int = 100000):
        """Initialize replay buffer.

        Args:
            capacity: Maximum buffer size
        """
        self.capacity = capacity
        self.buffer: List[Transition] = []
        self.position = 0

    def push(self, transition: Transition):
        """Add transition to buffer."""
        if len(self.buffer) < self.capacity:
            self.buffer.append(transition)
        else:
            self.buffer[self.position] = transition
        self.position = (self.position + 1) % self.capacity

    def sample(self, batch_size: int) -> List[Transition]:
        """Sample batch of transitions."""
        indices = np.random.choice(len(self.buffer), batch_size, replace=False)
        return [self.buffer[i] for i in indices]

    def __len__(self) -> int:
        return len(self.buffer)

    def __getitem__(self, idx: int) -> Transition:
        return self.buffer[idx]

    def save(self, path: Path):
        """Save buffer to disk."""
        with open(path, 'wb') as f:
            pickle.dump(self.buffer, f)

    def load(self, path: Path):
        """Load buffer from disk."""
        with open(path, 'rb') as f:
            self.buffer = pickle.load(f)


class QNetwork(nn.Module):
    """Q-network for value estimation."""

    def __init__(self, state_dim: int, action_dim: int, hidden_dim: int = 256):
        """Initialize Q-network.

        Args:
            state_dim: State dimension
            action_dim: Action dimension
            hidden_dim: Hidden layer dimension
        """
        super().__init__()

        self.fc1 = nn.Linear(state_dim, hidden_dim)
        self.fc2 = nn.Linear(hidden_dim, hidden_dim)
        self.fc3 = nn.Linear(hidden_dim, hidden_dim)
        self.fc4 = nn.Linear(hidden_dim, action_dim)

        self.ln1 = nn.LayerNorm(hidden_dim)
        self.ln2 = nn.LayerNorm(hidden_dim)
        self.ln3 = nn.LayerNorm(hidden_dim)

        self.dropout = nn.Dropout(0.1)

    def forward(self, state: torch.Tensor) -> torch.Tensor:
        """Forward pass.

        Args:
            state: State tensor

        Returns:
            Q-values for all actions
        """
        x = F.relu(self.ln1(self.fc1(state)))
        x = self.dropout(x)
        x = F.relu(self.ln2(self.fc2(x)))
        x = self.dropout(x)
        x = F.relu(self.ln3(self.fc3(x)))
        x = self.fc4(x)
        return x


class ValueNetwork(nn.Module):
    """Value network for IQL."""

    def __init__(self, state_dim: int, hidden_dim: int = 256):
        """Initialize value network.

        Args:
            state_dim: State dimension
            hidden_dim: Hidden layer dimension
        """
        super().__init__()

        self.fc1 = nn.Linear(state_dim, hidden_dim)
        self.fc2 = nn.Linear(hidden_dim, hidden_dim)
        self.fc3 = nn.Linear(hidden_dim, 1)

        self.ln1 = nn.LayerNorm(hidden_dim)
        self.ln2 = nn.LayerNorm(hidden_dim)

    def forward(self, state: torch.Tensor) -> torch.Tensor:
        """Forward pass.

        Args:
            state: State tensor

        Returns:
            State value
        """
        x = F.relu(self.ln1(self.fc1(state)))
        x = F.relu(self.ln2(self.fc2(x)))
        x = self.fc3(x)
        return x


class IQLAgent:
    """Implicit Q-Learning agent for offline RL."""

    def __init__(
        self,
        state_dim: int,
        action_dim: int,
        learning_rate: float = 3e-4,
        gamma: float = 0.99,
        tau: float = 0.005,
        beta: float = 3.0,
        device: str = "cuda" if torch.cuda.is_available() else "cpu"
    ):
        """Initialize IQL agent.

        Args:
            state_dim: State dimension
            action_dim: Action dimension
            learning_rate: Learning rate
            gamma: Discount factor
            tau: Soft update parameter
            beta: Inverse temperature for AWR
            device: Computation device
        """
        self.device = device
        self.gamma = gamma
        self.tau = tau
        self.beta = beta

        # Networks
        self.q_network = QNetwork(state_dim, action_dim).to(device)
        self.q_target = QNetwork(state_dim, action_dim).to(device)
        self.q_target.load_state_dict(self.q_network.state_dict())

        self.v_network = ValueNetwork(state_dim).to(device)

        # Optimizers
        self.q_optimizer = torch.optim.Adam(self.q_network.parameters(), lr=learning_rate)
        self.v_optimizer = torch.optim.Adam(self.v_network.parameters(), lr=learning_rate)

        self.total_steps = 0

    def update(self, batch: List[Transition]) -> Dict[str, float]:
        """Update agent with batch of transitions.

        Args:
            batch: Batch of transitions

        Returns:
            Training metrics
        """
        # Convert batch to tensors
        states = torch.stack([t.state.to_tensor() for t in batch]).to(self.device)
        actions = torch.tensor([t.action.to_index([]) for t in batch]).to(self.device)
        rewards = torch.tensor([t.reward for t in batch], dtype=torch.float32).to(self.device)
        next_states = torch.stack([
            t.next_state.to_tensor() if t.next_state else torch.zeros_like(states[0])
            for t in batch
        ]).to(self.device)
        dones = torch.tensor([t.done for t in batch], dtype=torch.float32).to(self.device)

        # Update value network
        with torch.no_grad():
            q_values = self.q_network(states).gather(1, actions.unsqueeze(1)).squeeze()
            next_v = self.v_network(next_states).squeeze()
            target_v = rewards + self.gamma * next_v * (1 - dones)
            advantage = q_values - self.v_network(states).squeeze()
            weight = torch.exp(advantage * self.beta).clamp(max=100.0)

        v_pred = self.v_network(states).squeeze()
        v_loss = (weight * (v_pred - target_v) ** 2).mean()

        self.v_optimizer.zero_grad()
        v_loss.backward()
        torch.nn.utils.clip_grad_norm_(self.v_network.parameters(), 1.0)
        self.v_optimizer.step()

        # Update Q network
        with torch.no_grad():
            next_v = self.v_network(next_states).squeeze()
            q_target = rewards + self.gamma * next_v * (1 - dones)

        q_pred = self.q_network(states).gather(1, actions.unsqueeze(1)).squeeze()
        q_loss = F.mse_loss(q_pred, q_target)

        self.q_optimizer.zero_grad()
        q_loss.backward()
        torch.nn.utils.clip_grad_norm_(self.q_network.parameters(), 1.0)
        self.q_optimizer.step()

        # Soft update target network
        self._soft_update()

        self.total_steps += 1

        return {
            'v_loss': v_loss.item(),
            'q_loss': q_loss.item(),
            'v_mean': v_pred.mean().item(),
            'q_mean': q_pred.mean().item(),
            'advantage_mean': advantage.mean().item()
        }

    def _soft_update(self):
        """Soft update target network."""
        for target_param, param in zip(self.q_target.parameters(), self.q_network.parameters()):
            target_param.data.copy_(self.tau * param.data + (1 - self.tau) * target_param.data)

    def select_action(self, state: State, epsilon: float = 0.0) -> int:
        """Select action using epsilon-greedy policy.

        Args:
            state: Current state
            epsilon: Exploration rate

        Returns:
            Action index
        """
        if np.random.random() < epsilon:
            return np.random.randint(0, self.q_network.fc4.out_features)

        with torch.no_grad():
            state_tensor = state.to_tensor().unsqueeze(0).to(self.device)
            q_values = self.q_network(state_tensor)
            return q_values.argmax(dim=1).item()

    def save(self, path: Path):
        """Save agent state."""
        torch.save({
            'q_network': self.q_network.state_dict(),
            'q_target': self.q_target.state_dict(),
            'v_network': self.v_network.state_dict(),
            'q_optimizer': self.q_optimizer.state_dict(),
            'v_optimizer': self.v_optimizer.state_dict(),
            'total_steps': self.total_steps
        }, path)

    def load(self, path: Path):
        """Load agent state."""
        checkpoint = torch.load(path, map_location=self.device)
        self.q_network.load_state_dict(checkpoint['q_network'])
        self.q_target.load_state_dict(checkpoint['q_target'])
        self.v_network.load_state_dict(checkpoint['v_network'])
        self.q_optimizer.load_state_dict(checkpoint['q_optimizer'])
        self.v_optimizer.load_state_dict(checkpoint['v_optimizer'])
        self.total_steps = checkpoint['total_steps']


class CQLAgent(IQLAgent):
    """Conservative Q-Learning agent."""

    def __init__(
        self,
        state_dim: int,
        action_dim: int,
        learning_rate: float = 3e-4,
        gamma: float = 0.99,
        tau: float = 0.005,
        alpha: float = 0.2,
        device: str = "cuda" if torch.cuda.is_available() else "cpu"
    ):
        """Initialize CQL agent.

        Args:
            state_dim: State dimension
            action_dim: Action dimension
            learning_rate: Learning rate
            gamma: Discount factor
            tau: Soft update parameter
            alpha: CQL regularization weight
            device: Computation device
        """
        super().__init__(state_dim, action_dim, learning_rate, gamma, tau, device=device)
        self.alpha = alpha
        self.action_dim = action_dim

    def update(self, batch: List[Transition]) -> Dict[str, float]:
        """Update agent with CQL objective.

        Args:
            batch: Batch of transitions

        Returns:
            Training metrics
        """
        # Convert batch to tensors
        states = torch.stack([t.state.to_tensor() for t in batch]).to(self.device)
        actions = torch.tensor([t.action.to_index([]) for t in batch]).to(self.device)
        rewards = torch.tensor([t.reward for t in batch], dtype=torch.float32).to(self.device)
        next_states = torch.stack([
            t.next_state.to_tensor() if t.next_state else torch.zeros_like(states[0])
            for t in batch
        ]).to(self.device)
        dones = torch.tensor([t.done for t in batch], dtype=torch.float32).to(self.device)

        # Compute Q targets
        with torch.no_grad():
            next_q = self.q_target(next_states)
            next_q_max = next_q.max(dim=1)[0]
            q_target = rewards + self.gamma * next_q_max * (1 - dones)

        # Q network loss
        q_pred = self.q_network(states).gather(1, actions.unsqueeze(1)).squeeze()
        td_loss = F.mse_loss(q_pred, q_target)

        # CQL regularization
        q_values = self.q_network(states)
        logsumexp = torch.logsumexp(q_values, dim=1)
        cql_loss = (logsumexp - q_values.gather(1, actions.unsqueeze(1)).squeeze()).mean()

        # Total loss
        q_loss = td_loss + self.alpha * cql_loss

        self.q_optimizer.zero_grad()
        q_loss.backward()
        torch.nn.utils.clip_grad_norm_(self.q_network.parameters(), 1.0)
        self.q_optimizer.step()

        # Soft update target network
        self._soft_update()

        self.total_steps += 1

        return {
            'td_loss': td_loss.item(),
            'cql_loss': cql_loss.item(),
            'q_loss': q_loss.item(),
            'q_mean': q_pred.mean().item(),
            'q_std': q_pred.std().item()
        }


class RLOptimizer:
    """RL-based planning optimizer."""

    def __init__(
        self,
        algorithm: str = "iql",
        state_dim: int = 128,
        action_dim: int = 50,
        buffer_size: int = 100000,
        model_dir: Path = Path("models/rl")
    ):
        """Initialize RL optimizer.

        Args:
            algorithm: RL algorithm (iql or cql)
            state_dim: State dimension
            action_dim: Action dimension
            buffer_size: Replay buffer size
            model_dir: Model directory
        """
        self.algorithm = algorithm
        self.state_dim = state_dim
        self.action_dim = action_dim
        self.model_dir = model_dir
        self.model_dir.mkdir(parents=True, exist_ok=True)

        # Initialize agent
        if algorithm == "iql":
            self.agent = IQLAgent(state_dim, action_dim)
        elif algorithm == "cql":
            self.agent = CQLAgent(state_dim, action_dim)
        else:
            raise ValueError(f"Unknown algorithm: {algorithm}")

        # Initialize replay buffer
        self.buffer = ReplayBuffer(buffer_size)

        # Training statistics
        self.training_stats = []

        logger.info(f"Initialized {algorithm.upper()} optimizer")

    def add_experience(self, transition: Transition):
        """Add experience to replay buffer.

        Args:
            transition: State-action-reward transition
        """
        self.buffer.push(transition)

    def train(
        self,
        num_epochs: int = 100,
        batch_size: int = 256,
        save_interval: int = 10
    ) -> List[Dict[str, float]]:
        """Train the RL agent.

        Args:
            num_epochs: Number of training epochs
            batch_size: Batch size
            save_interval: Model save interval

        Returns:
            Training statistics
        """
        if len(self.buffer) < batch_size:
            logger.warning(f"Insufficient data in buffer: {len(self.buffer)} < {batch_size}")
            return []

        logger.info(f"Starting training for {num_epochs} epochs")

        stats = []
        for epoch in range(num_epochs):
            epoch_stats = []

            # Train on multiple batches per epoch
            num_batches = min(100, len(self.buffer) // batch_size)
            for _ in range(num_batches):
                batch = self.buffer.sample(batch_size)
                batch_stats = self.agent.update(batch)
                epoch_stats.append(batch_stats)

            # Aggregate epoch statistics
            epoch_summary = {
                key: np.mean([s[key] for s in epoch_stats])
                for key in epoch_stats[0].keys()
            }
            epoch_summary['epoch'] = epoch
            stats.append(epoch_summary)

            # Log progress
            if epoch % 10 == 0:
                logger.info(
                    f"Epoch {epoch}: "
                    f"Loss={epoch_summary.get('q_loss', 0):.4f}, "
                    f"Q-mean={epoch_summary.get('q_mean', 0):.4f}"
                )

            # Save model
            if epoch % save_interval == 0:
                self.save(self.model_dir / f"checkpoint_epoch_{epoch}.pt")

        self.training_stats.extend(stats)

        # Save final model
        self.save(self.model_dir / "final_model.pt")

        return stats

    def optimize_plan(
        self,
        state: State,
        action_space: List[Action]
    ) -> Tuple[Action, float]:
        """Optimize execution plan using learned policy.

        Args:
            state: Current state
            action_space: Available actions

        Returns:
            Optimal action and its value
        """
        # Get Q-values for all actions
        with torch.no_grad():
            state_tensor = state.to_tensor().unsqueeze(0).to(self.agent.device)
            q_values = self.agent.q_network(state_tensor).squeeze().cpu().numpy()

        # Select best action
        best_idx = np.argmax(q_values[:len(action_space)])
        best_action = action_space[best_idx]
        best_value = q_values[best_idx]

        logger.info(f"Selected action with value {best_value:.4f}")

        return best_action, best_value

    def evaluate_performance(
        self,
        test_transitions: List[Transition]
    ) -> Dict[str, float]:
        """Evaluate agent performance.

        Args:
            test_transitions: Test transitions

        Returns:
            Performance metrics
        """
        if not test_transitions:
            return {}

        total_reward = sum(t.reward for t in test_transitions)
        avg_reward = total_reward / len(test_transitions)

        # Compute value estimates
        values = []
        for t in test_transitions:
            with torch.no_grad():
                state_tensor = t.state.to_tensor().unsqueeze(0).to(self.agent.device)
                value = self.agent.v_network(state_tensor).item() if hasattr(self.agent, 'v_network') else 0
                values.append(value)

        return {
            'total_reward': total_reward,
            'avg_reward': avg_reward,
            'avg_value': np.mean(values) if values else 0,
            'value_std': np.std(values) if values else 0,
            'num_episodes': len(test_transitions)
        }

    def save(self, path: Path):
        """Save optimizer state.

        Args:
            path: Save path
        """
        self.agent.save(path)

        # Save buffer
        buffer_path = path.parent / f"{path.stem}_buffer.pkl"
        self.buffer.save(buffer_path)

        # Save statistics
        stats_path = path.parent / f"{path.stem}_stats.json"
        with open(stats_path, 'w') as f:
            json.dump(self.training_stats, f, indent=2, default=str)

        logger.info(f"Saved optimizer to {path}")

    def load(self, path: Path):
        """Load optimizer state.

        Args:
            path: Load path
        """
        self.agent.load(path)

        # Load buffer
        buffer_path = path.parent / f"{path.stem}_buffer.pkl"
        if buffer_path.exists():
            self.buffer.load(buffer_path)

        # Load statistics
        stats_path = path.parent / f"{path.stem}_stats.json"
        if stats_path.exists():
            with open(stats_path, 'r') as f:
                self.training_stats = json.load(f)

        logger.info(f"Loaded optimizer from {path}")


def create_rl_optimizer(config: Dict[str, Any]) -> RLOptimizer:
    """Factory function to create RL optimizer.

    Args:
        config: Configuration dictionary

    Returns:
        RL optimizer instance
    """
    return RLOptimizer(
        algorithm=config.get('algorithm', 'iql'),
        state_dim=config.get('state_dim', 128),
        action_dim=config.get('action_dim', 50),
        buffer_size=config.get('buffer_size', 100000),
        model_dir=Path(config.get('model_dir', 'models/rl'))
    )