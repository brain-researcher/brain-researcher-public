#!/usr/bin/env python3
"""
Brain Researcher Auto-scaling System

This module provides intelligent auto-scaling capabilities for the Brain Researcher
platform, integrating with both Docker Swarm and Kubernetes environments.

Features:
- CPU and Memory based scaling
- Custom metrics integration (queue depth, response time)
- Predictive scaling using historical data
- Multi-tier scaling strategy
- Cost optimization
- Integration with existing load balancer
"""

import asyncio
import logging
import time
import statistics
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from enum import Enum
import json
import os

import docker
import redis
import psutil
from kubernetes import client, config
import numpy as np
from sklearn.linear_model import LinearRegression
from sklearn.preprocessing import StandardScaler

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class ScalingAction(str, Enum):
    """Scaling action types."""
    SCALE_UP = "scale_up"
    SCALE_DOWN = "scale_down" 
    MAINTAIN = "maintain"


class PlatformType(str, Enum):
    """Deployment platform types."""
    DOCKER_SWARM = "docker_swarm"
    KUBERNETES = "kubernetes"
    STANDALONE = "standalone"


@dataclass
class ServiceConfig:
    """Configuration for a service's scaling behavior."""
    name: str
    min_replicas: int = 1
    max_replicas: int = 10
    target_cpu_percent: int = 70
    target_memory_percent: int = 80
    scale_up_threshold: int = 80
    scale_down_threshold: int = 30
    cooldown_minutes: int = 5
    scale_up_increment: int = 1
    scale_down_increment: int = 1
    enable_predictive: bool = True
    custom_metrics: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MetricSample:
    """A single metric measurement."""
    timestamp: datetime
    cpu_percent: float
    memory_percent: float
    active_connections: int = 0
    response_time_ms: float = 0.0
    queue_depth: int = 0
    custom_metrics: Dict[str, float] = field(default_factory=dict)


@dataclass
class ScalingDecision:
    """Result of scaling analysis."""
    service_name: str
    action: ScalingAction
    current_replicas: int
    target_replicas: int
    confidence: float
    reason: str
    metrics_summary: Dict[str, Any] = field(default_factory=dict)


class MetricsCollector:
    """Collects metrics from various sources."""
    
    def __init__(self, redis_url: str = "redis://localhost:6379"):
        """Initialize metrics collector.
        
        Args:
            redis_url: Redis connection URL for storing metrics
        """
        self.redis_client = redis.from_url(redis_url)
        self.docker_client = None
        self.k8s_client = None
        
        # Initialize platform clients
        self._init_platform_clients()
    
    def _init_platform_clients(self):
        """Initialize platform-specific clients."""
        try:
            self.docker_client = docker.from_env()
            logger.info("Docker client initialized")
        except Exception as e:
            logger.warning(f"Docker client initialization failed: {e}")
        
        try:
            config.load_incluster_config()
            self.k8s_client = client.AppsV1Api()
            logger.info("Kubernetes client initialized")
        except Exception:
            try:
                config.load_kube_config()
                self.k8s_client = client.AppsV1Api()
                logger.info("Kubernetes client initialized from config")
            except Exception as e:
                logger.warning(f"Kubernetes client initialization failed: {e}")
    
    async def collect_system_metrics(self) -> Dict[str, Any]:
        """Collect system-wide metrics."""
        metrics = {
            'timestamp': datetime.utcnow(),
            'cpu_percent': psutil.cpu_percent(interval=1),
            'memory_percent': psutil.virtual_memory().percent,
            'disk_usage': psutil.disk_usage('/').percent,
            'network_io': psutil.net_io_counters()._asdict(),
            'load_average': os.getloadavg() if hasattr(os, 'getloadavg') else [0, 0, 0]
        }
        
        return metrics
    
    async def collect_service_metrics_docker(self, service_name: str) -> List[MetricSample]:
        """Collect metrics for Docker Swarm service."""
        if not self.docker_client:
            return []
        
        samples = []
        try:
            service = self.docker_client.services.get(service_name)
            tasks = service.tasks()
            
            for task in tasks:
                if task['Status']['State'] == 'running':
                    container_id = task['Status']['ContainerStatus']['ContainerID']
                    container = self.docker_client.containers.get(container_id)
                    
                    # Get container stats
                    stats = container.stats(stream=False)
                    
                    # Calculate CPU usage
                    cpu_delta = (stats['cpu_stats']['cpu_usage']['total_usage'] - 
                               stats['precpu_stats']['cpu_usage']['total_usage'])
                    system_delta = (stats['cpu_stats']['system_cpu_usage'] - 
                                  stats['precpu_stats']['system_cpu_usage'])
                    cpu_percent = (cpu_delta / system_delta) * 100.0 if system_delta > 0 else 0
                    
                    # Calculate memory usage
                    memory_usage = stats['memory_stats']['usage']
                    memory_limit = stats['memory_stats']['limit']
                    memory_percent = (memory_usage / memory_limit) * 100.0 if memory_limit > 0 else 0
                    
                    sample = MetricSample(
                        timestamp=datetime.utcnow(),
                        cpu_percent=cpu_percent,
                        memory_percent=memory_percent
                    )
                    samples.append(sample)
                    
        except Exception as e:
            logger.error(f"Error collecting Docker metrics for {service_name}: {e}")
        
        return samples
    
    async def collect_service_metrics_k8s(self, service_name: str, namespace: str = "default") -> List[MetricSample]:
        """Collect metrics for Kubernetes deployment."""
        if not self.k8s_client:
            return []
        
        samples = []
        try:
            # Get deployment
            deployment = self.k8s_client.read_namespaced_deployment(service_name, namespace)
            
            # Get pods
            label_selector = f"app={service_name}"
            v1 = client.CoreV1Api()
            pods = v1.list_namespaced_pod(namespace, label_selector=label_selector)
            
            # Collect metrics from metrics server (requires metrics-server)
            custom_api = client.CustomObjectsApi()
            
            for pod in pods.items:
                if pod.status.phase == 'Running':
                    try:
                        # Get pod metrics from metrics server
                        pod_metrics = custom_api.get_namespaced_custom_object(
                            group="metrics.k8s.io",
                            version="v1beta1",
                            namespace=namespace,
                            plural="pods",
                            name=pod.metadata.name
                        )
                        
                        # Parse CPU and memory metrics
                        container_metrics = pod_metrics['containers'][0]
                        cpu_usage = self._parse_cpu_usage(container_metrics['usage']['cpu'])
                        memory_usage = self._parse_memory_usage(container_metrics['usage']['memory'])
                        
                        # Get resource limits for percentage calculation
                        container = pod.spec.containers[0]
                        cpu_limit = self._parse_cpu_usage(container.resources.limits.get('cpu', '100m'))
                        memory_limit = self._parse_memory_usage(container.resources.limits.get('memory', '128Mi'))
                        
                        cpu_percent = (cpu_usage / cpu_limit) * 100.0 if cpu_limit > 0 else 0
                        memory_percent = (memory_usage / memory_limit) * 100.0 if memory_limit > 0 else 0
                        
                        sample = MetricSample(
                            timestamp=datetime.utcnow(),
                            cpu_percent=cpu_percent,
                            memory_percent=memory_percent
                        )
                        samples.append(sample)
                        
                    except Exception as e:
                        logger.warning(f"Error collecting metrics for pod {pod.metadata.name}: {e}")
                        
        except Exception as e:
            logger.error(f"Error collecting Kubernetes metrics for {service_name}: {e}")
        
        return samples
    
    def _parse_cpu_usage(self, cpu_string: str) -> float:
        """Parse CPU usage string to millicores."""
        if cpu_string.endswith('n'):
            return float(cpu_string[:-1]) / 1000000
        elif cpu_string.endswith('u'):
            return float(cpu_string[:-1]) / 1000
        elif cpu_string.endswith('m'):
            return float(cpu_string[:-1])
        else:
            return float(cpu_string) * 1000
    
    def _parse_memory_usage(self, memory_string: str) -> float:
        """Parse memory usage string to bytes."""
        if memory_string.endswith('Ki'):
            return float(memory_string[:-2]) * 1024
        elif memory_string.endswith('Mi'):
            return float(memory_string[:-2]) * 1024 * 1024
        elif memory_string.endswith('Gi'):
            return float(memory_string[:-2]) * 1024 * 1024 * 1024
        else:
            return float(memory_string)
    
    async def collect_custom_metrics(self, service_name: str) -> Dict[str, float]:
        """Collect custom application metrics."""
        metrics = {}
        
        try:
            # Collect from Redis (job queue depths, etc.)
            queue_depth = self.redis_client.llen(f"queue:{service_name}")
            metrics['queue_depth'] = float(queue_depth)
            
            # Collect response time metrics
            response_times_key = f"metrics:response_times:{service_name}"
            response_times = self.redis_client.lrange(response_times_key, -100, -1)
            if response_times:
                avg_response_time = statistics.mean([float(rt) for rt in response_times])
                metrics['avg_response_time_ms'] = avg_response_time
            
            # Collect connection counts
            connections_key = f"metrics:connections:{service_name}"
            active_connections = self.redis_client.get(connections_key)
            if active_connections:
                metrics['active_connections'] = float(active_connections)
            
            # Collect error rates
            errors_key = f"metrics:errors:{service_name}"
            error_count = self.redis_client.get(errors_key)
            if error_count:
                metrics['error_rate'] = float(error_count)
                
        except Exception as e:
            logger.error(f"Error collecting custom metrics for {service_name}: {e}")
        
        return metrics


class PredictiveScaler:
    """Implements predictive scaling using machine learning."""
    
    def __init__(self, history_window_hours: int = 24):
        """Initialize predictive scaler.
        
        Args:
            history_window_hours: Hours of historical data to use for prediction
        """
        self.history_window_hours = history_window_hours
        self.models = {}
        self.scalers = {}
        self.last_training = {}
    
    def prepare_features(self, metrics_history: List[MetricSample]) -> Tuple[np.ndarray, np.ndarray]:
        """Prepare feature matrix and target values for ML model.
        
        Args:
            metrics_history: List of historical metric samples
            
        Returns:
            Tuple of (features, targets) numpy arrays
        """
        if len(metrics_history) < 10:
            return np.array([]), np.array([])
        
        features = []
        targets = []
        
        # Sort by timestamp
        sorted_metrics = sorted(metrics_history, key=lambda x: x.timestamp)
        
        for i in range(5, len(sorted_metrics)):
            # Use previous 5 samples as features
            feature_window = sorted_metrics[i-5:i]
            target_sample = sorted_metrics[i]
            
            # Extract feature values
            feature_vector = []
            for sample in feature_window:
                feature_vector.extend([
                    sample.cpu_percent,
                    sample.memory_percent,
                    sample.active_connections,
                    sample.response_time_ms,
                    sample.queue_depth,
                    sample.timestamp.hour,  # Time of day feature
                    sample.timestamp.weekday()  # Day of week feature
                ])
            
            features.append(feature_vector)
            
            # Target is the load score (combined CPU and memory pressure)
            load_score = (target_sample.cpu_percent * 0.6 + 
                         target_sample.memory_percent * 0.4)
            targets.append(load_score)
        
        return np.array(features), np.array(targets)
    
    def train_model(self, service_name: str, metrics_history: List[MetricSample]) -> bool:
        """Train predictive model for a service.
        
        Args:
            service_name: Name of the service
            metrics_history: Historical metrics data
            
        Returns:
            True if model was trained successfully
        """
        try:
            features, targets = self.prepare_features(metrics_history)
            
            if len(features) == 0:
                logger.warning(f"Insufficient data to train model for {service_name}")
                return False
            
            # Initialize scaler and model
            scaler = StandardScaler()
            model = LinearRegression()
            
            # Scale features
            features_scaled = scaler.fit_transform(features)
            
            # Train model
            model.fit(features_scaled, targets)
            
            # Store model and scaler
            self.models[service_name] = model
            self.scalers[service_name] = scaler
            self.last_training[service_name] = datetime.utcnow()
            
            # Calculate model score
            score = model.score(features_scaled, targets)
            logger.info(f"Trained predictive model for {service_name} with score: {score:.3f}")
            
            return True
            
        except Exception as e:
            logger.error(f"Error training model for {service_name}: {e}")
            return False
    
    def predict_load(self, service_name: str, recent_metrics: List[MetricSample], 
                     prediction_horizon_minutes: int = 15) -> Optional[float]:
        """Predict future load for a service.
        
        Args:
            service_name: Name of the service
            recent_metrics: Recent metrics (at least 5 samples)
            prediction_horizon_minutes: How far ahead to predict
            
        Returns:
            Predicted load score or None if prediction fails
        """
        if service_name not in self.models or len(recent_metrics) < 5:
            return None
        
        try:
            model = self.models[service_name]
            scaler = self.scalers[service_name]
            
            # Prepare feature vector from recent metrics
            sorted_metrics = sorted(recent_metrics[-5:], key=lambda x: x.timestamp)
            
            feature_vector = []
            for sample in sorted_metrics:
                feature_vector.extend([
                    sample.cpu_percent,
                    sample.memory_percent,
                    sample.active_connections,
                    sample.response_time_ms,
                    sample.queue_depth,
                    sample.timestamp.hour,
                    sample.timestamp.weekday()
                ])
            
            # Scale features
            features_scaled = scaler.transform([feature_vector])
            
            # Make prediction
            predicted_load = model.predict(features_scaled)[0]
            
            return max(0.0, min(100.0, predicted_load))  # Clamp to [0, 100]
            
        except Exception as e:
            logger.error(f"Error predicting load for {service_name}: {e}")
            return None


class AutoScaler:
    """Main auto-scaling coordinator."""
    
    def __init__(self, 
                 platform: PlatformType = PlatformType.DOCKER_SWARM,
                 redis_url: str = "redis://localhost:6379",
                 config_file: Optional[str] = None):
        """Initialize auto-scaler.
        
        Args:
            platform: Deployment platform
            redis_url: Redis connection URL
            config_file: Path to configuration file
        """
        self.platform = platform
        self.metrics_collector = MetricsCollector(redis_url)
        self.predictive_scaler = PredictiveScaler()
        
        # Service configurations
        self.service_configs: Dict[str, ServiceConfig] = {}
        self.last_scale_action: Dict[str, datetime] = {}
        self.metrics_history: Dict[str, List[MetricSample]] = {}
        
        # Platform clients
        self.docker_client = None
        self.k8s_client = None
        
        self._init_platform_clients()
        self._load_configuration(config_file)
    
    def _init_platform_clients(self):
        """Initialize platform-specific clients."""
        if self.platform == PlatformType.DOCKER_SWARM:
            try:
                self.docker_client = docker.from_env()
                logger.info("Docker Swarm client initialized")
            except Exception as e:
                logger.error(f"Failed to initialize Docker client: {e}")
        
        elif self.platform == PlatformType.KUBERNETES:
            try:
                config.load_incluster_config()
                self.k8s_client = client.AppsV1Api()
                logger.info("Kubernetes client initialized")
            except Exception:
                try:
                    config.load_kube_config()
                    self.k8s_client = client.AppsV1Api()
                    logger.info("Kubernetes client initialized from config")
                except Exception as e:
                    logger.error(f"Failed to initialize Kubernetes client: {e}")
    
    def _load_configuration(self, config_file: Optional[str]):
        """Load service configurations."""
        if config_file and os.path.exists(config_file):
            try:
                with open(config_file, 'r') as f:
                    config_data = json.load(f)
                
                for service_config in config_data.get('services', []):
                    name = service_config['name']
                    self.service_configs[name] = ServiceConfig(**service_config)
                    
                logger.info(f"Loaded configuration for {len(self.service_configs)} services")
                
            except Exception as e:
                logger.error(f"Error loading configuration: {e}")
        
        # Default configurations for Brain Researcher services
        if not self.service_configs:
            self._load_default_configurations()
    
    def _load_default_configurations(self):
        """Load default service configurations."""
        default_services = [
            {
                'name': 'orchestrator',
                'min_replicas': 3,
                'max_replicas': 12,
                'target_cpu_percent': 65,
                'target_memory_percent': 70,
                'cooldown_minutes': 5
            },
            {
                'name': 'neurokg',
                'min_replicas': 2,
                'max_replicas': 8,
                'target_cpu_percent': 70,
                'target_memory_percent': 75,
                'cooldown_minutes': 3
            },
            {
                'name': 'agent',
                'min_replicas': 2,
                'max_replicas': 6,
                'target_cpu_percent': 80,
                'target_memory_percent': 85,
                'cooldown_minutes': 10  # Longer cooldown for LLM services
            },
            {
                'name': 'web-ui',
                'min_replicas': 2,
                'max_replicas': 8,
                'target_cpu_percent': 70,
                'target_memory_percent': 80,
                'cooldown_minutes': 3
            },
        ]
        
        for service_data in default_services:
            name = service_data['name']
            self.service_configs[name] = ServiceConfig(**service_data)
        
        logger.info(f"Loaded default configurations for {len(self.service_configs)} services")
    
    async def collect_metrics_for_service(self, service_name: str) -> List[MetricSample]:
        """Collect current metrics for a service."""
        if self.platform == PlatformType.DOCKER_SWARM:
            samples = await self.metrics_collector.collect_service_metrics_docker(service_name)
        elif self.platform == PlatformType.KUBERNETES:
            samples = await self.metrics_collector.collect_service_metrics_k8s(service_name)
        else:
            samples = []
        
        # Add custom metrics to samples
        custom_metrics = await self.metrics_collector.collect_custom_metrics(service_name)
        
        for sample in samples:
            sample.custom_metrics = custom_metrics
            if 'queue_depth' in custom_metrics:
                sample.queue_depth = int(custom_metrics['queue_depth'])
            if 'avg_response_time_ms' in custom_metrics:
                sample.response_time_ms = custom_metrics['avg_response_time_ms']
            if 'active_connections' in custom_metrics:
                sample.active_connections = int(custom_metrics['active_connections'])
        
        return samples
    
    def analyze_scaling_decision(self, service_name: str, 
                                current_samples: List[MetricSample],
                                current_replicas: int) -> ScalingDecision:
        """Analyze metrics and decide on scaling action."""
        config = self.service_configs.get(service_name)
        if not config:
            return ScalingDecision(
                service_name=service_name,
                action=ScalingAction.MAINTAIN,
                current_replicas=current_replicas,
                target_replicas=current_replicas,
                confidence=0.0,
                reason="No configuration found"
            )
        
        if not current_samples:
            return ScalingDecision(
                service_name=service_name,
                action=ScalingAction.MAINTAIN,
                current_replicas=current_replicas,
                target_replicas=current_replicas,
                confidence=0.0,
                reason="No metrics available"
            )
        
        # Calculate average metrics
        avg_cpu = statistics.mean([s.cpu_percent for s in current_samples])
        avg_memory = statistics.mean([s.memory_percent for s in current_samples])
        avg_response_time = statistics.mean([s.response_time_ms for s in current_samples])
        total_queue_depth = sum([s.queue_depth for s in current_samples])
        
        # Composite load score
        load_score = (avg_cpu * 0.4 + avg_memory * 0.3 + 
                     min(avg_response_time / 1000, 10) * 0.2 + 
                     min(total_queue_depth / 100, 10) * 0.1)
        
        # Get predictive score if available
        predictive_score = None
        if config.enable_predictive and service_name in self.metrics_history:
            predictive_score = self.predictive_scaler.predict_load(
                service_name, 
                self.metrics_history[service_name][-10:]
            )
        
        # Determine scaling action
        action = ScalingAction.MAINTAIN
        target_replicas = current_replicas
        confidence = 0.8
        reason = f"Load score: {load_score:.1f}, CPU: {avg_cpu:.1f}%, Memory: {avg_memory:.1f}%"
        
        # Scale up conditions
        if (avg_cpu > config.scale_up_threshold or 
            avg_memory > config.scale_up_threshold or
            total_queue_depth > 50 or
            (predictive_score and predictive_score > config.scale_up_threshold)):
            
            if current_replicas < config.max_replicas:
                action = ScalingAction.SCALE_UP
                target_replicas = min(
                    current_replicas + config.scale_up_increment,
                    config.max_replicas
                )
                reason = f"High load detected - {reason}"
                
                if predictive_score:
                    reason += f", Predicted: {predictive_score:.1f}%"
                    confidence = 0.9
        
        # Scale down conditions
        elif (avg_cpu < config.scale_down_threshold and 
              avg_memory < config.scale_down_threshold and
              total_queue_depth < 10 and
              (not predictive_score or predictive_score < config.scale_down_threshold)):
            
            if current_replicas > config.min_replicas:
                action = ScalingAction.SCALE_DOWN
                target_replicas = max(
                    current_replicas - config.scale_down_increment,
                    config.min_replicas
                )
                reason = f"Low load detected - {reason}"
                confidence = 0.7
        
        return ScalingDecision(
            service_name=service_name,
            action=action,
            current_replicas=current_replicas,
            target_replicas=target_replicas,
            confidence=confidence,
            reason=reason,
            metrics_summary={
                'avg_cpu': avg_cpu,
                'avg_memory': avg_memory,
                'avg_response_time': avg_response_time,
                'queue_depth': total_queue_depth,
                'load_score': load_score,
                'predictive_score': predictive_score
            }
        )
    
    async def execute_scaling_decision(self, decision: ScalingDecision) -> bool:
        """Execute a scaling decision."""
        if decision.action == ScalingAction.MAINTAIN:
            return True
        
        # Check cooldown period
        last_action = self.last_scale_action.get(decision.service_name)
        if last_action:
            config = self.service_configs[decision.service_name]
            cooldown_delta = timedelta(minutes=config.cooldown_minutes)
            if datetime.utcnow() - last_action < cooldown_delta:
                logger.info(f"Scaling action for {decision.service_name} skipped due to cooldown")
                return False
        
        success = False
        
        try:
            if self.platform == PlatformType.DOCKER_SWARM:
                success = await self._scale_docker_service(decision)
            elif self.platform == PlatformType.KUBERNETES:
                success = await self._scale_k8s_deployment(decision)
            
            if success:
                self.last_scale_action[decision.service_name] = datetime.utcnow()
                logger.info(
                    f"Successfully scaled {decision.service_name} "
                    f"{decision.action.value} from {decision.current_replicas} "
                    f"to {decision.target_replicas} replicas. "
                    f"Reason: {decision.reason}"
                )
            
        except Exception as e:
            logger.error(f"Error executing scaling decision for {decision.service_name}: {e}")
        
        return success
    
    async def _scale_docker_service(self, decision: ScalingDecision) -> bool:
        """Scale a Docker Swarm service."""
        if not self.docker_client:
            return False
        
        try:
            service = self.docker_client.services.get(decision.service_name)
            service.scale(decision.target_replicas)
            return True
            
        except Exception as e:
            logger.error(f"Error scaling Docker service {decision.service_name}: {e}")
            return False
    
    async def _scale_k8s_deployment(self, decision: ScalingDecision, namespace: str = "default") -> bool:
        """Scale a Kubernetes deployment."""
        if not self.k8s_client:
            return False
        
        try:
            # Update deployment replicas
            deployment = self.k8s_client.read_namespaced_deployment(decision.service_name, namespace)
            deployment.spec.replicas = decision.target_replicas
            
            self.k8s_client.patch_namespaced_deployment(
                name=decision.service_name,
                namespace=namespace,
                body=deployment
            )
            
            return True
            
        except Exception as e:
            logger.error(f"Error scaling Kubernetes deployment {decision.service_name}: {e}")
            return False
    
    def get_current_replicas(self, service_name: str) -> int:
        """Get current replica count for a service."""
        try:
            if self.platform == PlatformType.DOCKER_SWARM and self.docker_client:
                service = self.docker_client.services.get(service_name)
                return len(service.tasks())
            
            elif self.platform == PlatformType.KUBERNETES and self.k8s_client:
                deployment = self.k8s_client.read_namespaced_deployment(service_name, "default")
                return deployment.status.ready_replicas or 0
            
        except Exception as e:
            logger.error(f"Error getting replica count for {service_name}: {e}")
        
        return 1  # Default fallback
    
    async def run_scaling_cycle(self):
        """Run one complete scaling cycle for all services."""
        logger.info("Starting scaling cycle")
        
        for service_name, config in self.service_configs.items():
            try:
                # Collect current metrics
                current_samples = await self.collect_metrics_for_service(service_name)
                
                # Store metrics history
                if service_name not in self.metrics_history:
                    self.metrics_history[service_name] = []
                
                self.metrics_history[service_name].extend(current_samples)
                
                # Keep only recent history (last 24 hours)
                cutoff_time = datetime.utcnow() - timedelta(hours=24)
                self.metrics_history[service_name] = [
                    s for s in self.metrics_history[service_name] 
                    if s.timestamp > cutoff_time
                ]
                
                # Train predictive model if needed
                if (config.enable_predictive and 
                    len(self.metrics_history[service_name]) > 50 and
                    (service_name not in self.predictive_scaler.last_training or
                     datetime.utcnow() - self.predictive_scaler.last_training[service_name] > timedelta(hours=6))):
                    
                    self.predictive_scaler.train_model(service_name, self.metrics_history[service_name])
                
                # Get current replica count
                current_replicas = self.get_current_replicas(service_name)
                
                # Analyze scaling decision
                decision = self.analyze_scaling_decision(service_name, current_samples, current_replicas)
                
                # Execute scaling decision
                if decision.action != ScalingAction.MAINTAIN:
                    await self.execute_scaling_decision(decision)
                else:
                    logger.debug(f"No scaling needed for {service_name}: {decision.reason}")
                
            except Exception as e:
                logger.error(f"Error in scaling cycle for {service_name}: {e}")
        
        logger.info("Scaling cycle completed")
    
    async def run_continuous(self, interval_seconds: int = 60):
        """Run continuous auto-scaling loop."""
        logger.info(f"Starting continuous auto-scaling with {interval_seconds}s interval")
        
        while True:
            try:
                await self.run_scaling_cycle()
                await asyncio.sleep(interval_seconds)
                
            except KeyboardInterrupt:
                logger.info("Auto-scaling stopped by user")
                break
            except Exception as e:
                logger.error(f"Error in auto-scaling loop: {e}")
                await asyncio.sleep(interval_seconds)


async def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Brain Researcher Auto-scaler")
    parser.add_argument("--platform", choices=["docker_swarm", "kubernetes"], 
                       default="docker_swarm", help="Deployment platform")
    parser.add_argument("--config", type=str, help="Configuration file path")
    parser.add_argument("--interval", type=int, default=60, 
                       help="Scaling check interval in seconds")
    parser.add_argument("--redis-url", default="redis://localhost:6379",
                       help="Redis connection URL")
    parser.add_argument("--once", action="store_true", 
                       help="Run once instead of continuously")
    
    args = parser.parse_args()
    
    # Initialize auto-scaler
    platform = PlatformType(args.platform)
    autoscaler = AutoScaler(
        platform=platform,
        redis_url=args.redis_url,
        config_file=args.config
    )
    
    if args.once:
        await autoscaler.run_scaling_cycle()
    else:
        await autoscaler.run_continuous(args.interval)


if __name__ == "__main__":
    asyncio.run(main())
