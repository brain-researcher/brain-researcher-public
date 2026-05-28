"""Reward tracking for reinforcement learning training."""

import logging
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any, Union
from dataclasses import dataclass, asdict
from enum import Enum
from collections import deque
import numpy as np
import redis
import json

logger = logging.getLogger(__name__)


class RewardType(Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    QUALITY = "quality"
    EFFICIENCY = "efficiency"
    USER_SATISFACTION = "user_satisfaction"
    COST = "cost"
    TIME = "time"
    CUSTOM = "custom"


@dataclass
class RewardSignal:
    """Individual reward signal from user interaction."""
    user_id: str
    session_id: str
    state: Dict[str, Any]
    action: str
    reward: float
    next_state: Optional[Dict[str, Any]]
    timestamp: datetime
    reward_type: RewardType
    metadata: Dict[str, Any]
    terminal: bool = False


@dataclass
class TrainingExample:
    """Formatted training example for RL algorithms."""
    state_vector: np.ndarray
    action_index: int
    reward: float
    next_state_vector: Optional[np.ndarray]
    done: bool
    importance_weight: float = 1.0


class RewardModel:
    """Models reward signals for different neuroimaging tasks."""
    
    def __init__(self):
        # Reward weights for different components
        self.weights = {
            "success": 1.0,
            "time_penalty": -0.01,  # per second
            "cost_penalty": -0.1,   # per unit cost
            "quality_bonus": 2.0,
            "error_penalty": -0.5,
            "user_satisfaction": 3.0
        }
        
        # Baseline expectations
        self.baselines = {
            "execution_time": 300,  # 5 minutes expected
            "quality_threshold": 0.7,
            "cost_threshold": 1.0
        }
    
    def calculate_reward(
        self,
        execution_result: Dict[str, Any],
        execution_time: float,
        execution_cost: float,
        quality_metrics: Dict[str, float],
        user_feedback: Optional[Dict[str, Any]] = None
    ) -> Tuple[float, Dict[str, float]]:
        """Calculate comprehensive reward signal."""
        reward_components = {}
        
        # Success/failure reward
        success = execution_result.get("success", False)
        reward_components["success"] = self.weights["success"] if success else -self.weights["success"]
        
        # Time penalty (relative to baseline)
        time_ratio = execution_time / self.baselines["execution_time"]
        if time_ratio > 1.0:
            reward_components["time"] = self.weights["time_penalty"] * (time_ratio - 1.0) * 100
        else:
            reward_components["time"] = 0.0
        
        # Cost penalty
        cost_ratio = execution_cost / self.baselines["cost_threshold"]
        if cost_ratio > 1.0:
            reward_components["cost"] = self.weights["cost_penalty"] * (cost_ratio - 1.0)
        else:
            reward_components["cost"] = 0.0
        
        # Quality bonus
        avg_quality = np.mean(list(quality_metrics.values())) if quality_metrics else 0.0
        if avg_quality > self.baselines["quality_threshold"]:
            quality_bonus = (avg_quality - self.baselines["quality_threshold"]) * self.weights["quality_bonus"]
            reward_components["quality"] = quality_bonus
        else:
            reward_components["quality"] = 0.0
        
        # Error penalty
        error_count = execution_result.get("error_count", 0)
        reward_components["errors"] = self.weights["error_penalty"] * error_count
        
        # User satisfaction
        if user_feedback:
            satisfaction = user_feedback.get("satisfaction_score", 0.0)
            reward_components["user_satisfaction"] = self.weights["user_satisfaction"] * (satisfaction - 0.5)
        else:
            reward_components["user_satisfaction"] = 0.0
        
        total_reward = sum(reward_components.values())
        
        return total_reward, reward_components
    
    def update_baselines(self, recent_data: List[Dict]) -> None:
        """Update baseline expectations based on recent performance."""
        if not recent_data:
            return
        
        times = [d.get("execution_time", 0) for d in recent_data if d.get("execution_time")]
        if times:
            self.baselines["execution_time"] = np.percentile(times, 75)  # 75th percentile
        
        qualities = []
        for d in recent_data:
            if d.get("quality_metrics"):
                avg_quality = np.mean(list(d["quality_metrics"].values()))
                qualities.append(avg_quality)
        
        if qualities:
            self.baselines["quality_threshold"] = np.percentile(qualities, 25)  # 25th percentile


class StateActionEncoder:
    """Encodes states and actions for RL training."""
    
    def __init__(self):
        self.state_features = [
            "task_type", "data_size", "complexity_score", "user_expertise",
            "available_memory", "cpu_cores", "time_constraints", "quality_requirements"
        ]
        
        self.action_features = [
            "tool_name", "parameter_count", "estimated_time", "estimated_cost",
            "confidence_score", "complexity_level"
        ]
        
        # Feature encoders (would be learned or predefined)
        self.state_dim = 64
        self.action_dim = 32
    
    def encode_state(self, state: Dict[str, Any]) -> np.ndarray:
        """Encode state dictionary to fixed-size vector."""
        # Initialize with zeros
        vector = np.zeros(self.state_dim)
        
        # Task type (one-hot)
        task_types = ["fmri_analysis", "preprocessing", "visualization", "statistics"]
        task_type = state.get("task_type", "unknown")
        if task_type in task_types:
            vector[task_types.index(task_type)] = 1.0
        
        # Numerical features (normalized)
        vector[4] = self._normalize(state.get("data_size", 0), 0, 10000)  # MB
        vector[5] = self._normalize(state.get("complexity_score", 0.5), 0, 1)
        vector[6] = self._normalize(state.get("user_expertise", 0.5), 0, 1)
        vector[7] = self._normalize(state.get("available_memory", 8000), 1000, 32000)  # MB
        vector[8] = self._normalize(state.get("cpu_cores", 4), 1, 32)
        vector[9] = self._normalize(state.get("time_constraints", 3600), 60, 86400)  # seconds
        vector[10] = self._normalize(state.get("quality_requirements", 0.7), 0, 1)
        
        # Context features
        vector[11] = 1.0 if state.get("has_previous_results") else 0.0
        vector[12] = 1.0 if state.get("is_interactive") else 0.0
        vector[13] = self._normalize(state.get("session_step", 0), 0, 20)
        
        # Resource usage history (last 5 steps)
        history = state.get("resource_history", [])
        for i, usage in enumerate(history[-5:]):
            if i < 5:
                vector[14 + i] = self._normalize(usage, 0, 1)
        
        return vector
    
    def encode_action(self, action: str, action_metadata: Optional[Dict] = None) -> int:
        """Encode action to integer index."""
        # Predefined action vocabulary
        action_vocab = [
            "preprocess_fmri", "run_glm", "create_contrast", "visualize_results",
            "statistical_test", "quality_check", "export_data", "optimize_parameters"
        ]
        
        try:
            return action_vocab.index(action)
        except ValueError:
            return len(action_vocab)  # Unknown action
    
    def _normalize(self, value: float, min_val: float, max_val: float) -> float:
        """Normalize value to [0, 1] range."""
        if max_val == min_val:
            return 0.0
        return max(0.0, min(1.0, (value - min_val) / (max_val - min_val)))


class RewardTracker:
    """Main reward tracking system for RL training data collection."""
    
    def __init__(self, redis_client: Optional[redis.Redis] = None, buffer_size: int = 10000):
        self.redis_client = redis_client or redis.Redis(decode_responses=True)
        self.buffer_size = buffer_size
        self.reward_model = RewardModel()
        self.encoder = StateActionEncoder()
        
        # In-memory buffer for recent experiences
        self.experience_buffer = deque(maxlen=buffer_size)
        
        # Load existing experiences
        self._load_recent_experiences()
    
    def track_reward(
        self,
        user_id: str,
        session_id: str,
        state: Dict[str, Any],
        action: str,
        reward: Optional[float] = None,
        next_state: Optional[Dict[str, Any]] = None,
        reward_type: str = "custom",
        metadata: Optional[Dict[str, Any]] = None,
        terminal: bool = False,
        execution_result: Optional[Dict[str, Any]] = None,
        execution_time: Optional[float] = None,
        execution_cost: Optional[float] = None,
        quality_metrics: Optional[Dict[str, float]] = None,
        user_feedback: Optional[Dict[str, Any]] = None
    ) -> float:
        """Track a reward signal and store for RL training."""
        
        # Calculate reward if not provided
        if reward is None and execution_result is not None:
            calculated_reward, reward_components = self.reward_model.calculate_reward(
                execution_result=execution_result,
                execution_time=execution_time or 0.0,
                execution_cost=execution_cost or 0.0,
                quality_metrics=quality_metrics or {},
                user_feedback=user_feedback
            )
            reward = calculated_reward
            metadata = metadata or {}
            metadata["reward_components"] = reward_components
        
        if reward is None:
            reward = 0.0
        
        try:
            reward_type_enum = RewardType(reward_type.lower())
        except ValueError:
            reward_type_enum = RewardType.CUSTOM
        
        reward_signal = RewardSignal(
            user_id=user_id,
            session_id=session_id,
            state=state,
            action=action,
            reward=reward,
            next_state=next_state,
            timestamp=datetime.utcnow(),
            reward_type=reward_type_enum,
            metadata=metadata or {},
            terminal=terminal
        )
        
        # Store in buffer and Redis
        self.experience_buffer.append(reward_signal)
        self._store_reward_signal(reward_signal)
        
        logger.debug(f"Tracked reward: {reward:.3f} for action {action} (user: {user_id})")
        
        return reward
    
    def get_training_data(
        self,
        batch_size: Optional[int] = None,
        min_reward: Optional[float] = None,
        max_age_hours: int = 24,
        balance_actions: bool = True
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """Get formatted training data for RL algorithms."""
        
        # Filter experiences
        cutoff_time = datetime.utcnow() - timedelta(hours=max_age_hours)
        
        filtered_experiences = []
        for signal in self.experience_buffer:
            if signal.timestamp < cutoff_time:
                continue
            if min_reward is not None and signal.reward < min_reward:
                continue
            filtered_experiences.append(signal)
        
        if not filtered_experiences:
            # Return empty arrays with correct shapes
            return (
                np.zeros((0, self.encoder.state_dim)),
                np.zeros((0,), dtype=int),
                np.zeros((0,)),
                np.zeros((0, self.encoder.state_dim)),
                np.zeros((0,), dtype=bool),
                np.zeros((0,))
            )
        
        # Balance actions if requested
        if balance_actions:
            filtered_experiences = self._balance_actions(filtered_experiences)
        
        # Sample batch if specified
        if batch_size and len(filtered_experiences) > batch_size:
            indices = np.random.choice(len(filtered_experiences), batch_size, replace=False)
            filtered_experiences = [filtered_experiences[i] for i in indices]
        
        # Convert to training format
        states = []
        actions = []
        rewards = []
        next_states = []
        dones = []
        importance_weights = []
        
        for signal in filtered_experiences:
            state_vector = self.encoder.encode_state(signal.state)
            action_index = self.encoder.encode_action(signal.action)
            
            states.append(state_vector)
            actions.append(action_index)
            rewards.append(signal.reward)
            dones.append(signal.terminal)
            
            # Next state
            if signal.next_state:
                next_state_vector = self.encoder.encode_state(signal.next_state)
                next_states.append(next_state_vector)
            else:
                next_states.append(np.zeros(self.encoder.state_dim))
            
            # Importance weight (could be based on recency, reward magnitude, etc.)
            age_hours = (datetime.utcnow() - signal.timestamp).total_seconds() / 3600
            importance_weight = np.exp(-age_hours / 24)  # Exponential decay
            importance_weights.append(importance_weight)
        
        return (
            np.array(states),
            np.array(actions),
            np.array(rewards),
            np.array(next_states),
            np.array(dones),
            np.array(importance_weights)
        )
    
    def get_reward_statistics(
        self,
        user_id: Optional[str] = None,
        action: Optional[str] = None,
        hours_back: int = 24
    ) -> Dict[str, float]:
        """Get reward statistics for analysis."""
        cutoff_time = datetime.utcnow() - timedelta(hours=hours_back)
        
        filtered_signals = []
        for signal in self.experience_buffer:
            if signal.timestamp < cutoff_time:
                continue
            if user_id and signal.user_id != user_id:
                continue
            if action and signal.action != action:
                continue
            filtered_signals.append(signal)
        
        if not filtered_signals:
            return {"count": 0}
        
        rewards = [s.reward for s in filtered_signals]
        
        return {
            "count": len(filtered_signals),
            "mean_reward": float(np.mean(rewards)),
            "std_reward": float(np.std(rewards)),
            "min_reward": float(np.min(rewards)),
            "max_reward": float(np.max(rewards)),
            "median_reward": float(np.median(rewards)),
            "positive_rate": sum(1 for r in rewards if r > 0) / len(rewards)
        }
    
    def get_action_performance(self, hours_back: int = 24) -> Dict[str, Dict]:
        """Get performance statistics by action."""
        cutoff_time = datetime.utcnow() - timedelta(hours=hours_back)
        
        action_stats = {}
        
        for signal in self.experience_buffer:
            if signal.timestamp < cutoff_time:
                continue
            
            action = signal.action
            if action not in action_stats:
                action_stats[action] = {"rewards": [], "count": 0}
            
            action_stats[action]["rewards"].append(signal.reward)
            action_stats[action]["count"] += 1
        
        # Calculate statistics for each action
        for action, data in action_stats.items():
            rewards = data["rewards"]
            if rewards:
                action_stats[action].update({
                    "mean_reward": float(np.mean(rewards)),
                    "std_reward": float(np.std(rewards)),
                    "success_rate": sum(1 for r in rewards if r > 0) / len(rewards),
                    "total_reward": sum(rewards)
                })
        
        return action_stats
    
    def update_reward_model(self, performance_data: List[Dict]) -> None:
        """Update reward model baselines based on recent performance."""
        self.reward_model.update_baselines(performance_data)
        logger.info("Updated reward model baselines")
    
    def export_training_data(
        self,
        file_path: str,
        format: str = "numpy",
        max_samples: Optional[int] = None
    ) -> None:
        """Export training data to file."""
        states, actions, rewards, next_states, dones, weights = self.get_training_data(
            batch_size=max_samples
        )
        
        if format == "numpy":
            np.savez(
                file_path,
                states=states,
                actions=actions,
                rewards=rewards,
                next_states=next_states,
                dones=dones,
                importance_weights=weights
            )
        elif format == "json":
            data = {
                "states": states.tolist(),
                "actions": actions.tolist(),
                "rewards": rewards.tolist(),
                "next_states": next_states.tolist(),
                "dones": dones.tolist(),
                "importance_weights": weights.tolist()
            }
            
            with open(file_path, 'w') as f:
                json.dump(data, f)
        
        logger.info(f"Exported {len(states)} training samples to {file_path}")
    
    def clear_old_data(self, max_age_days: int = 30) -> int:
        """Clear old reward signals to manage storage."""
        cutoff_time = datetime.utcnow() - timedelta(days=max_age_days)
        
        # Clear from buffer
        original_size = len(self.experience_buffer)
        self.experience_buffer = deque(
            [s for s in self.experience_buffer if s.timestamp >= cutoff_time],
            maxlen=self.buffer_size
        )
        
        # Clear from Redis
        pattern = "reward:*"
        deleted_count = 0
        
        for key in self.redis_client.scan_iter(match=pattern):
            try:
                timestamp_str = self.redis_client.hget(key, "timestamp")
                if timestamp_str:
                    timestamp = datetime.fromisoformat(timestamp_str)
                    if timestamp < cutoff_time:
                        self.redis_client.delete(key)
                        deleted_count += 1
            except Exception as e:
                logger.warning(f"Error checking timestamp for {key}: {e}")
        
        cleared_count = original_size - len(self.experience_buffer)
        logger.info(f"Cleared {cleared_count} old reward signals from buffer and {deleted_count} from Redis")
        
        return cleared_count + deleted_count
    
    # Private Methods
    
    def _store_reward_signal(self, signal: RewardSignal) -> None:
        """Store reward signal in Redis."""
        key = f"reward:{signal.user_id}:{signal.session_id}:{int(signal.timestamp.timestamp())}"
        
        data = asdict(signal)
        data["timestamp"] = signal.timestamp.isoformat()
        data["reward_type"] = signal.reward_type.value
        
        # Convert numpy arrays to lists for JSON serialization
        if isinstance(data["state"], dict):
            data["state"] = {k: v.tolist() if isinstance(v, np.ndarray) else v 
                           for k, v in data["state"].items()}
        
        if data["next_state"] and isinstance(data["next_state"], dict):
            data["next_state"] = {k: v.tolist() if isinstance(v, np.ndarray) else v 
                                for k, v in data["next_state"].items()}
        
        self.redis_client.hset(key, mapping={
            k: json.dumps(v) if isinstance(v, dict) else str(v)
            for k, v in data.items()
        })
        
        # Set expiration (30 days)
        self.redis_client.expire(key, 30 * 24 * 3600)
    
    def _load_recent_experiences(self) -> None:
        """Load recent experiences from Redis."""
        pattern = "reward:*"
        
        for key in self.redis_client.scan_iter(match=pattern):
            try:
                data = self.redis_client.hgetall(key)
                if not data:
                    continue
                
                # Parse data
                data["timestamp"] = datetime.fromisoformat(data["timestamp"])
                data["reward_type"] = RewardType(data["reward_type"])
                data["reward"] = float(data["reward"])
                data["terminal"] = data["terminal"].lower() == "true"
                data["state"] = json.loads(data["state"])
                data["metadata"] = json.loads(data["metadata"])
                
                if data["next_state"] != "None":
                    data["next_state"] = json.loads(data["next_state"])
                else:
                    data["next_state"] = None
                
                signal = RewardSignal(**data)
                self.experience_buffer.append(signal)
                
            except Exception as e:
                logger.warning(f"Failed to load reward signal from {key}: {e}")
        
        logger.info(f"Loaded {len(self.experience_buffer)} recent reward signals")
    
    def _balance_actions(self, experiences: List[RewardSignal]) -> List[RewardSignal]:
        """Balance action distribution in training data."""
        action_groups = {}
        
        for exp in experiences:
            action = exp.action
            if action not in action_groups:
                action_groups[action] = []
            action_groups[action].append(exp)
        
        # Find minimum group size
        min_size = min(len(group) for group in action_groups.values())
        
        # Sample equally from each group
        balanced_experiences = []
        for group in action_groups.values():
            if len(group) > min_size:
                sampled = np.random.choice(group, min_size, replace=False)
                balanced_experiences.extend(sampled)
            else:
                balanced_experiences.extend(group)
        
        return balanced_experiences