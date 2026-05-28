"""Base contextual bandit implementation for multi-armed bandit problems."""

import numpy as np
import logging
from typing import Dict, List, Optional, Tuple, Any, Union
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from collections import defaultdict, deque
import json

logger = logging.getLogger(__name__)


@dataclass
class BanditAction:
    """Represents a bandit arm/action with metadata."""
    id: int
    name: str
    description: str
    parameters: Dict[str, Any]
    cost: float = 0.0
    expected_time: float = 0.0


@dataclass
class Context:
    """Context information for contextual bandits."""
    features: np.ndarray
    metadata: Dict[str, Any]
    timestamp: datetime
    user_id: Optional[str] = None
    session_id: Optional[str] = None


@dataclass
class BanditFeedback:
    """Feedback from bandit action execution."""
    context: Context
    action_id: int
    reward: float
    execution_time: float
    success: bool
    metadata: Dict[str, Any]
    timestamp: datetime


class ContextualBandit(ABC):
    """Base class for contextual multi-armed bandits."""
    
    def __init__(
        self,
        n_arms: int,
        context_dim: int,
        actions: Optional[List[BanditAction]] = None,
        exploration_bonus: float = 1.0,
        decay_rate: float = 0.99
    ):
        self.n_arms = n_arms
        self.context_dim = context_dim
        self.exploration_bonus = exploration_bonus
        self.decay_rate = decay_rate
        
        # Action definitions
        if actions:
            assert len(actions) == n_arms, "Number of actions must match n_arms"
            self.actions = {action.id: action for action in actions}
        else:
            # Create default actions
            self.actions = {
                i: BanditAction(id=i, name=f"action_{i}", description=f"Action {i}", parameters={})
                for i in range(n_arms)
            }
        
        # Experience storage
        self.contexts = []
        self.action_history = []
        self.rewards = []
        self.feedback_history = []
        
        # Statistics tracking
        self.action_counts = np.zeros(n_arms)
        self.total_rewards = np.zeros(n_arms)
        self.regret_history = []
        self.cumulative_regret = 0.0
        
        # Performance tracking
        self.action_performance = {
            i: {
                "total_reward": 0.0,
                "count": 0,
                "success_rate": 0.0,
                "avg_execution_time": 0.0,
                "recent_rewards": deque(maxlen=100)
            }
            for i in range(n_arms)
        }
        
        self.training_step = 0
        
    @abstractmethod
    def select_arm(
        self,
        context: Union[np.ndarray, Context],
        available_arms: Optional[List[int]] = None,
        exploit: bool = False
    ) -> Tuple[int, Dict[str, Any]]:
        """Select an arm given context.
        
        Args:
            context: Context vector or Context object
            available_arms: List of available arm indices (None = all arms)
            exploit: If True, select greedily without exploration
            
        Returns:
            Selected arm index and selection info
        """
        pass
    
    def update(
        self,
        context: Union[np.ndarray, Context],
        action: int,
        reward: float,
        feedback: Optional[BanditFeedback] = None
    ) -> None:
        """Update bandit with observed reward.
        
        Args:
            context: Context vector or Context object
            action: Selected action index
            reward: Observed reward
            feedback: Additional feedback information
        """
        # Convert context to numpy array if needed
        if isinstance(context, Context):
            context_vector = context.features
            self.contexts.append(context)
        else:
            context_vector = context
            self.contexts.append(Context(
                features=context_vector.copy(),
                metadata={},
                timestamp=datetime.utcnow()
            ))
        
        # Update history
        self.action_history.append(action)
        self.rewards.append(reward)
        
        if feedback:
            self.feedback_history.append(feedback)
        
        # Update statistics
        self.action_counts[action] += 1
        self.total_rewards[action] += reward
        
        # Update performance tracking
        perf = self.action_performance[action]
        perf["total_reward"] += reward
        perf["count"] += 1
        perf["recent_rewards"].append(reward)
        
        if feedback:
            # Update success rate
            old_successes = perf["success_rate"] * (perf["count"] - 1)
            new_successes = old_successes + (1 if feedback.success else 0)
            perf["success_rate"] = new_successes / perf["count"]
            
            # Update average execution time
            old_time_sum = perf["avg_execution_time"] * (perf["count"] - 1)
            new_time_sum = old_time_sum + feedback.execution_time
            perf["avg_execution_time"] = new_time_sum / perf["count"]
        
        # Calculate instantaneous regret (requires oracle reward)
        oracle_reward = self._calculate_oracle_reward(context_vector)
        regret = oracle_reward - reward
        self.regret_history.append(regret)
        self.cumulative_regret += regret
        
        self.training_step += 1
        
        # Decay old information periodically
        if self.training_step % 100 == 0:
            self._decay_history()
    
    def get_arm_statistics(self, arm_id: int) -> Dict[str, float]:
        """Get statistics for a specific arm."""
        if arm_id not in range(self.n_arms):
            raise ValueError(f"Invalid arm_id: {arm_id}")
        
        perf = self.action_performance[arm_id]
        
        stats = {
            "total_pulls": int(self.action_counts[arm_id]),
            "total_reward": float(self.total_rewards[arm_id]),
            "average_reward": float(self.total_rewards[arm_id] / max(1, self.action_counts[arm_id])),
            "success_rate": float(perf["success_rate"]),
            "avg_execution_time": float(perf["avg_execution_time"]),
            "recent_performance": float(np.mean(perf["recent_rewards"])) if perf["recent_rewards"] else 0.0,
            "confidence": self._calculate_confidence(arm_id)
        }
        
        return stats
    
    def get_overall_statistics(self) -> Dict[str, Any]:
        """Get overall bandit statistics."""
        total_pulls = int(np.sum(self.action_counts))
        
        if total_pulls == 0:
            return {"message": "No actions taken yet"}
        
        # Calculate exploration vs exploitation ratio
        if hasattr(self, '_exploration_count'):
            exploration_rate = self._exploration_count / total_pulls
        else:
            exploration_rate = 0.5  # Default estimate
        
        # Best performing arm
        avg_rewards = self.total_rewards / np.maximum(1, self.action_counts)
        best_arm = int(np.argmax(avg_rewards))
        
        stats = {
            "total_pulls": total_pulls,
            "total_reward": float(np.sum(self.total_rewards)),
            "average_reward": float(np.sum(self.total_rewards) / total_pulls),
            "cumulative_regret": float(self.cumulative_regret),
            "average_regret": float(self.cumulative_regret / total_pulls),
            "exploration_rate": float(exploration_rate),
            "best_arm": best_arm,
            "best_arm_reward": float(avg_rewards[best_arm]),
            "arm_distribution": {
                str(i): float(count / total_pulls) 
                for i, count in enumerate(self.action_counts)
            },
            "recent_regret": float(np.mean(self.regret_history[-100:])) if len(self.regret_history) >= 100 else 0.0
        }
        
        return stats
    
    def predict_rewards(
        self,
        contexts: np.ndarray,
        arms: Optional[List[int]] = None
    ) -> np.ndarray:
        """Predict rewards for given contexts and arms."""
        arms = arms or list(range(self.n_arms))
        
        # Default implementation: use historical averages
        predictions = np.zeros((len(contexts), len(arms)))
        
        for i, arm in enumerate(arms):
            if self.action_counts[arm] > 0:
                predictions[:, i] = self.total_rewards[arm] / self.action_counts[arm]
            else:
                predictions[:, i] = 0.0  # No experience with this arm
        
        return predictions
    
    def get_feature_importance(self) -> Dict[str, float]:
        """Get importance of context features (if applicable)."""
        # Base implementation returns uniform importance
        return {f"feature_{i}": 1.0 / self.context_dim for i in range(self.context_dim)}
    
    def save_state(self, filepath: str) -> None:
        """Save bandit state to file."""
        state = {
            "n_arms": self.n_arms,
            "context_dim": self.context_dim,
            "exploration_bonus": self.exploration_bonus,
            "decay_rate": self.decay_rate,
            "action_counts": self.action_counts.tolist(),
            "total_rewards": self.total_rewards.tolist(),
            "cumulative_regret": self.cumulative_regret,
            "training_step": self.training_step,
            "actions": {
                str(k): {
                    "id": v.id,
                    "name": v.name,
                    "description": v.description,
                    "parameters": v.parameters,
                    "cost": v.cost,
                    "expected_time": v.expected_time
                }
                for k, v in self.actions.items()
            },
            "action_performance": {
                str(k): {
                    "total_reward": v["total_reward"],
                    "count": v["count"],
                    "success_rate": v["success_rate"],
                    "avg_execution_time": v["avg_execution_time"],
                    "recent_rewards": list(v["recent_rewards"])
                }
                for k, v in self.action_performance.items()
            }
        }
        
        # Add algorithm-specific state
        state.update(self._get_algorithm_state())
        
        with open(filepath, 'w') as f:
            json.dump(state, f, indent=2)
        
        logger.info(f"Saved bandit state to {filepath}")
    
    def load_state(self, filepath: str) -> None:
        """Load bandit state from file."""
        with open(filepath, 'r') as f:
            state = json.load(f)
        
        self.n_arms = state["n_arms"]
        self.context_dim = state["context_dim"]
        self.exploration_bonus = state["exploration_bonus"]
        self.decay_rate = state["decay_rate"]
        self.action_counts = np.array(state["action_counts"])
        self.total_rewards = np.array(state["total_rewards"])
        self.cumulative_regret = state["cumulative_regret"]
        self.training_step = state["training_step"]
        
        # Reconstruct actions
        self.actions = {}
        for k, v in state["actions"].items():
            self.actions[int(k)] = BanditAction(**v)
        
        # Reconstruct performance tracking
        self.action_performance = {}
        for k, v in state["action_performance"].items():
            self.action_performance[int(k)] = {
                "total_reward": v["total_reward"],
                "count": v["count"],
                "success_rate": v["success_rate"],
                "avg_execution_time": v["avg_execution_time"],
                "recent_rewards": deque(v["recent_rewards"], maxlen=100)
            }
        
        # Load algorithm-specific state
        self._set_algorithm_state(state)
        
        logger.info(f"Loaded bandit state from {filepath}")
    
    def reset(self) -> None:
        """Reset bandit to initial state."""
        self.contexts = []
        self.action_history = []
        self.rewards = []
        self.feedback_history = []
        
        self.action_counts = np.zeros(self.n_arms)
        self.total_rewards = np.zeros(self.n_arms)
        self.regret_history = []
        self.cumulative_regret = 0.0
        
        self.action_performance = {
            i: {
                "total_reward": 0.0,
                "count": 0,
                "success_rate": 0.0,
                "avg_execution_time": 0.0,
                "recent_rewards": deque(maxlen=100)
            }
            for i in range(self.n_arms)
        }
        
        self.training_step = 0
        
        logger.info("Reset bandit to initial state")
    
    # Protected/Private methods
    
    def _calculate_oracle_reward(self, context: np.ndarray) -> float:
        """Calculate oracle (optimal) reward for given context.
        
        This is used for regret calculation. In practice, this would be
        unknown, but can be estimated or set based on domain knowledge.
        """
        # Simple implementation: assume optimal reward is max of current averages
        avg_rewards = self.total_rewards / np.maximum(1, self.action_counts)
        return np.max(avg_rewards) if np.sum(self.action_counts) > 0 else 1.0
    
    def _calculate_confidence(self, arm_id: int) -> float:
        """Calculate confidence score for an arm's performance estimate."""
        count = self.action_counts[arm_id]
        if count == 0:
            return 0.0
        
        # Simple confidence based on number of observations
        # Higher count = higher confidence, but with diminishing returns
        return min(1.0, count / 100.0)
    
    def _decay_history(self) -> None:
        """Apply decay to historical information."""
        if len(self.contexts) > 1000:
            # Keep only recent history
            keep_size = int(1000 * self.decay_rate)
            self.contexts = self.contexts[-keep_size:]
            self.action_history = self.action_history[-keep_size:]
            self.rewards = self.rewards[-keep_size:]
            
            if len(self.feedback_history) > keep_size:
                self.feedback_history = self.feedback_history[-keep_size:]
    
    @abstractmethod
    def _get_algorithm_state(self) -> Dict[str, Any]:
        """Get algorithm-specific state for saving."""
        return {}
    
    @abstractmethod
    def _set_algorithm_state(self, state: Dict[str, Any]) -> None:
        """Set algorithm-specific state from loaded data."""
        pass
    
    def _extract_context_features(self, context: Union[np.ndarray, Context]) -> np.ndarray:
        """Extract feature vector from context."""
        if isinstance(context, Context):
            return context.features
        return context
    
    def _softmax(self, values: np.ndarray, temperature: float = 1.0) -> np.ndarray:
        """Compute softmax probabilities."""
        exp_values = np.exp((values - np.max(values)) / temperature)
        return exp_values / np.sum(exp_values)
    
    def _upper_confidence_bound(self, arm_id: int, confidence_level: float = 2.0) -> float:
        """Calculate upper confidence bound for an arm."""
        if self.action_counts[arm_id] == 0:
            return float('inf')  # Infinite uncertainty for unobserved arms
        
        mean_reward = self.total_rewards[arm_id] / self.action_counts[arm_id]
        total_count = np.sum(self.action_counts)
        
        if total_count <= 1:
            return mean_reward
        
        confidence_radius = confidence_level * np.sqrt(
            np.log(total_count) / self.action_counts[arm_id]
        )
        
        return mean_reward + confidence_radius
    
    def get_arm_rankings(self) -> List[Tuple[int, float, str]]:
        """Get arms ranked by performance with confidence."""
        rankings = []
        
        for arm_id in range(self.n_arms):
            stats = self.get_arm_statistics(arm_id)
            avg_reward = stats["average_reward"]
            confidence = stats["confidence"]
            
            # Create confidence description
            if confidence > 0.8:
                conf_desc = "high"
            elif confidence > 0.5:
                conf_desc = "medium"
            elif confidence > 0.2:
                conf_desc = "low"
            else:
                conf_desc = "very_low"
            
            rankings.append((arm_id, avg_reward, conf_desc))
        
        # Sort by average reward (descending)
        rankings.sort(key=lambda x: x[1], reverse=True)
        
        return rankings