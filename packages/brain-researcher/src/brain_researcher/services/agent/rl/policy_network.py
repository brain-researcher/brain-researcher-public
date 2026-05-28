"""Neural network architectures for RL policies and value functions."""

import numpy as np
import logging
from typing import Dict, List, Optional, Tuple, Any
from abc import ABC, abstractmethod
import json
import pickle

logger = logging.getLogger(__name__)


class BaseNetwork(ABC):
    """Base class for neural networks with numpy implementation."""
    
    def __init__(self, input_dim: int, output_dim: int, hidden_dims: List[int]):
        self.input_dim = input_dim
        self.output_dim = output_dim
        self.hidden_dims = hidden_dims
        
        # Initialize weights and biases
        self.weights = []
        self.biases = []
        self._initialize_parameters()
        
        # For training
        self.learning_rate = 0.001
        self.momentum = 0.9
        self.weight_decay = 0.0001
        
        # Momentum terms
        self.weight_momentum = [np.zeros_like(w) for w in self.weights]
        self.bias_momentum = [np.zeros_like(b) for b in self.biases]
    
    def _initialize_parameters(self) -> None:
        """Initialize network parameters."""
        layer_sizes = [self.input_dim] + self.hidden_dims + [self.output_dim]
        
        for i in range(len(layer_sizes) - 1):
            input_size = layer_sizes[i]
            output_size = layer_sizes[i + 1]
            
            # Xavier initialization
            limit = np.sqrt(6.0 / (input_size + output_size))
            weight = np.random.uniform(-limit, limit, (input_size, output_size))
            bias = np.zeros(output_size)
            
            self.weights.append(weight)
            self.biases.append(bias)
    
    def forward(self, x: np.ndarray) -> np.ndarray:
        """Forward pass through the network."""
        activation = x
        
        for i, (weight, bias) in enumerate(zip(self.weights, self.biases)):
            activation = np.dot(activation, weight) + bias
            
            # Apply ReLU to hidden layers
            if i < len(self.weights) - 1:
                activation = np.maximum(0, activation)
        
        return activation
    
    def backward(self, x: np.ndarray, target: np.ndarray) -> float:
        """Backward pass and parameter update."""
        # Forward pass with stored activations
        activations = [x]
        current_activation = x
        
        for i, (weight, bias) in enumerate(zip(self.weights, self.biases)):
            z = np.dot(current_activation, weight) + bias
            
            if i < len(self.weights) - 1:  # Hidden layers
                current_activation = np.maximum(0, z)
            else:  # Output layer
                current_activation = z
            
            activations.append(current_activation)
        
        # Calculate loss
        loss = 0.5 * np.mean((current_activation - target) ** 2)
        
        # Backward pass
        delta = current_activation - target
        
        for i in range(len(self.weights) - 1, -1, -1):
            # Gradients
            weight_grad = np.dot(activations[i].T, delta)
            bias_grad = np.mean(delta, axis=0)
            
            # Apply weight decay
            weight_grad += self.weight_decay * self.weights[i]
            
            # Update with momentum
            self.weight_momentum[i] = (self.momentum * self.weight_momentum[i] - 
                                     self.learning_rate * weight_grad)
            self.bias_momentum[i] = (self.momentum * self.bias_momentum[i] - 
                                   self.learning_rate * bias_grad)
            
            self.weights[i] += self.weight_momentum[i]
            self.biases[i] += self.bias_momentum[i]
            
            # Propagate error for next iteration
            if i > 0:
                delta = np.dot(delta, self.weights[i].T)
                # Apply ReLU derivative
                delta = delta * (activations[i] > 0)
        
        return loss
    
    def predict(self, x: np.ndarray) -> np.ndarray:
        """Make predictions."""
        if len(x.shape) == 1:
            x = x.reshape(1, -1)
        return self.forward(x)
    
    def save(self, filepath: str) -> None:
        """Save network parameters."""
        params = {
            'weights': [w.tolist() for w in self.weights],
            'biases': [b.tolist() for b in self.biases],
            'input_dim': self.input_dim,
            'output_dim': self.output_dim,
            'hidden_dims': self.hidden_dims
        }
        
        with open(filepath, 'w') as f:
            json.dump(params, f)
    
    def load(self, filepath: str) -> None:
        """Load network parameters."""
        with open(filepath, 'r') as f:
            params = json.load(f)
        
        self.weights = [np.array(w) for w in params['weights']]
        self.biases = [np.array(b) for b in params['biases']]
        self.input_dim = params['input_dim']
        self.output_dim = params['output_dim']
        self.hidden_dims = params['hidden_dims']
        
        # Reinitialize momentum terms
        self.weight_momentum = [np.zeros_like(w) for w in self.weights]
        self.bias_momentum = [np.zeros_like(b) for b in self.biases]


class PolicyNetwork(BaseNetwork):
    """Policy network for action selection."""
    
    def __init__(self, state_dim: int, action_dim: int, hidden_dims: List[int] = None):
        hidden_dims = hidden_dims or [256, 128]
        super().__init__(state_dim, action_dim, hidden_dims)
        self.temperature = 1.0
    
    def forward(self, x: np.ndarray) -> np.ndarray:
        """Forward pass with softmax output."""
        logits = super().forward(x)
        
        # Apply temperature scaling
        logits = logits / self.temperature
        
        # Softmax
        exp_logits = np.exp(logits - np.max(logits, axis=-1, keepdims=True))
        probabilities = exp_logits / np.sum(exp_logits, axis=-1, keepdims=True)
        
        return probabilities
    
    def select_action(self, state: np.ndarray, deterministic: bool = False) -> Tuple[int, float]:
        """Select action from policy."""
        if len(state.shape) == 1:
            state = state.reshape(1, -1)
        
        probabilities = self.forward(state)[0]
        
        if deterministic:
            action = np.argmax(probabilities)
            prob = probabilities[action]
        else:
            action = np.random.choice(len(probabilities), p=probabilities)
            prob = probabilities[action]
        
        return action, prob
    
    def log_prob(self, state: np.ndarray, action: int) -> float:
        """Calculate log probability of action given state."""
        probabilities = self.forward(state)
        if len(probabilities.shape) == 2:
            probabilities = probabilities[0]
        
        prob = probabilities[action]
        return np.log(prob + 1e-8)  # Add small epsilon for numerical stability


class QNetwork(BaseNetwork):
    """Q-value network for action-value estimation."""
    
    def __init__(self, state_dim: int, action_dim: int, hidden_dims: List[int] = None):
        hidden_dims = hidden_dims or [256, 128, 64]
        super().__init__(state_dim, action_dim, hidden_dims)
    
    def get_q_values(self, state: np.ndarray) -> np.ndarray:
        """Get Q-values for all actions."""
        return self.forward(state)
    
    def get_q_value(self, state: np.ndarray, action: int) -> float:
        """Get Q-value for specific state-action pair."""
        q_values = self.get_q_values(state)
        if len(q_values.shape) == 2:
            return q_values[0, action]
        return q_values[action]
    
    def get_best_action(self, state: np.ndarray) -> Tuple[int, float]:
        """Get action with highest Q-value."""
        q_values = self.get_q_values(state)
        if len(q_values.shape) == 2:
            q_values = q_values[0]
        
        best_action = np.argmax(q_values)
        best_q_value = q_values[best_action]
        
        return best_action, best_q_value


class ValueNetwork(BaseNetwork):
    """State value network."""
    
    def __init__(self, state_dim: int, hidden_dims: List[int] = None):
        hidden_dims = hidden_dims or [256, 128]
        super().__init__(state_dim, 1, hidden_dims)  # Output dim is 1 for value
    
    def get_value(self, state: np.ndarray) -> float:
        """Get state value."""
        value = self.forward(state)
        if len(value.shape) == 2:
            return value[0, 0]
        return value[0]


class DuelingQNetwork(BaseNetwork):
    """Dueling Q-network architecture."""
    
    def __init__(self, state_dim: int, action_dim: int, hidden_dims: List[int] = None):
        hidden_dims = hidden_dims or [256, 128]
        super().__init__(state_dim, action_dim + 1, hidden_dims)  # +1 for value stream
        self.action_dim = action_dim
    
    def forward(self, x: np.ndarray) -> np.ndarray:
        """Forward pass with dueling streams."""
        features = super().forward(x)
        
        # Split into value and advantage streams
        value = features[..., 0:1]  # Value stream (1 output)
        advantage = features[..., 1:]  # Advantage stream (action_dim outputs)
        
        # Combine streams: Q(s,a) = V(s) + A(s,a) - mean(A(s,a'))
        advantage_mean = np.mean(advantage, axis=-1, keepdims=True)
        q_values = value + advantage - advantage_mean
        
        return q_values
    
    def get_q_values(self, state: np.ndarray) -> np.ndarray:
        """Get Q-values for all actions."""
        return self.forward(state)
    
    def get_value_advantage(self, state: np.ndarray) -> Tuple[float, np.ndarray]:
        """Get separate value and advantage estimates."""
        features = super().forward(state)
        
        if len(features.shape) == 2:
            features = features[0]
        
        value = features[0]
        advantage = features[1:]
        
        return value, advantage


class EnsembleQNetwork:
    """Ensemble of Q-networks for uncertainty estimation."""
    
    def __init__(self, state_dim: int, action_dim: int, num_networks: int = 3, 
                 hidden_dims: List[int] = None):
        self.networks = []
        self.num_networks = num_networks
        
        for _ in range(num_networks):
            network = QNetwork(state_dim, action_dim, hidden_dims)
            self.networks.append(network)
    
    def get_q_values_ensemble(self, state: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """Get Q-values and uncertainty from ensemble."""
        all_q_values = []
        
        for network in self.networks:
            q_values = network.get_q_values(state)
            all_q_values.append(q_values)
        
        all_q_values = np.array(all_q_values)
        
        # Mean and standard deviation across ensemble
        mean_q = np.mean(all_q_values, axis=0)
        std_q = np.std(all_q_values, axis=0)
        
        return mean_q, std_q
    
    def get_best_action_with_uncertainty(self, state: np.ndarray) -> Tuple[int, float, float]:
        """Get best action with uncertainty estimate."""
        mean_q, std_q = self.get_q_values_ensemble(state)
        
        if len(mean_q.shape) == 2:
            mean_q = mean_q[0]
            std_q = std_q[0]
        
        best_action = np.argmax(mean_q)
        best_q_value = mean_q[best_action]
        uncertainty = std_q[best_action]
        
        return best_action, best_q_value, uncertainty
    
    def train_ensemble(self, states: np.ndarray, targets: np.ndarray, 
                      bootstrap: bool = True) -> List[float]:
        """Train ensemble with optional bootstrapping."""
        losses = []
        
        for i, network in enumerate(self.networks):
            if bootstrap:
                # Bootstrap sampling
                indices = np.random.choice(len(states), len(states), replace=True)
                batch_states = states[indices]
                batch_targets = targets[indices]
            else:
                batch_states = states
                batch_targets = targets
            
            loss = network.backward(batch_states, batch_targets)
            losses.append(loss)
        
        return losses
    
    def save_ensemble(self, filepath_prefix: str) -> None:
        """Save ensemble networks."""
        for i, network in enumerate(self.networks):
            filepath = f"{filepath_prefix}_network_{i}.json"
            network.save(filepath)
    
    def load_ensemble(self, filepath_prefix: str) -> None:
        """Load ensemble networks."""
        for i, network in enumerate(self.networks):
            filepath = f"{filepath_prefix}_network_{i}.json"
            try:
                network.load(filepath)
            except FileNotFoundError:
                logger.warning(f"Could not load network {i} from {filepath}")


class NoisyNetwork(BaseNetwork):
    """Noisy network for exploration."""
    
    def __init__(self, state_dim: int, action_dim: int, hidden_dims: List[int] = None,
                 noise_std: float = 0.1):
        super().__init__(state_dim, action_dim, hidden_dims)
        self.noise_std = noise_std
        self.training = True
    
    def forward(self, x: np.ndarray) -> np.ndarray:
        """Forward pass with optional noise."""
        if self.training:
            # Add noise to weights
            noisy_weights = []
            for weight in self.weights:
                noise = np.random.normal(0, self.noise_std, weight.shape)
                noisy_weights.append(weight + noise)
            
            # Forward with noisy weights
            activation = x
            for i, (weight, bias) in enumerate(zip(noisy_weights, self.biases)):
                activation = np.dot(activation, weight) + bias
                if i < len(self.weights) - 1:
                    activation = np.maximum(0, activation)
            
            return activation
        else:
            return super().forward(x)
    
    def set_training_mode(self, training: bool) -> None:
        """Set training mode for noise."""
        self.training = training