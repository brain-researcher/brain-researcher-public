"""Online learner for continuous adaptation from user interactions."""

import json
import logging
from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

import numpy as np

from .drift_detector import DriftDetection, DriftType, MultimodalDriftDetector
from .experience_replay import Experience, ExperienceReplay, PrioritizedExperienceReplay
from .model_updater import ModelUpdater, UpdateConfig, UpdateStrategy, UpdateTrigger

logger = logging.getLogger(__name__)


@dataclass
class LearningSession:
    """Learning session information."""

    session_id: str
    user_id: str
    start_time: datetime
    end_time: Optional[datetime]
    interactions: int
    rewards_collected: int
    performance_improvement: float
    feedback_received: int
    drift_detections: int


@dataclass
class FeedbackSample:
    """User feedback sample."""

    user_id: str
    session_id: str
    task_context: Dict[str, Any]
    system_response: Any
    feedback_type: str  # "rating", "correction", "preference", "binary"
    feedback_value: Any
    timestamp: datetime
    metadata: Dict[str, Any]


class OnlineLearner:
    """Online learning system that continuously adapts from user interactions."""

    def __init__(
        self,
        base_model: Any,
        experience_buffer_size: int = 10000,
        update_frequency: int = 100,
        learning_rate: float = 0.01,
        use_prioritized_replay: bool = True,
        drift_detection: bool = True,
        performance_metric: Optional[Callable] = None,
    ):
        self.base_model = base_model
        self.update_frequency = update_frequency
        self.steps = 0

        # Experience replay
        if use_prioritized_replay:
            self.experience_buffer = PrioritizedExperienceReplay(
                capacity=experience_buffer_size, alpha=0.6, beta=0.4
            )
        else:
            self.experience_buffer = ExperienceReplay(capacity=experience_buffer_size)

        # Model updater
        update_config = UpdateConfig(
            strategy=UpdateStrategy.INCREMENTAL,
            trigger=UpdateTrigger.DATA_BASED,
            update_frequency=timedelta(minutes=15),
            batch_size=32,
            learning_rate=learning_rate,
            performance_threshold=0.05,
        )

        self.model_updater = ModelUpdater(
            model=base_model,
            config=update_config,
            performance_metric=performance_metric or self._default_performance_metric,
        )

        # Drift detection
        if drift_detection:
            self.drift_detector = MultimodalDriftDetector()
        else:
            self.drift_detector = None

        # Learning sessions
        self.current_session = None
        self.session_history = []

        # User feedback processing
        self.feedback_buffer = deque(maxlen=5000)
        self.feedback_processors = {
            "rating": self._process_rating_feedback,
            "correction": self._process_correction_feedback,
            "preference": self._process_preference_feedback,
            "binary": self._process_binary_feedback,
        }

        # Adaptation tracking
        self.learning_history = []
        self.performance_baseline = None
        self.adaptation_count = 0

        # User modeling
        self.user_profiles = {}
        self.personalization_enabled = True

        logger.info("Initialized OnlineLearner with continuous adaptation capabilities")

    def start_learning_session(
        self, user_id: str, session_id: Optional[str] = None
    ) -> str:
        """Start a new learning session."""
        if session_id is None:
            session_id = f"session_{user_id}_{int(datetime.utcnow().timestamp())}"

        # End current session if exists
        if self.current_session:
            self.end_learning_session()

        self.current_session = LearningSession(
            session_id=session_id,
            user_id=user_id,
            start_time=datetime.utcnow(),
            end_time=None,
            interactions=0,
            rewards_collected=0,
            performance_improvement=0.0,
            feedback_received=0,
            drift_detections=0,
        )

        # Initialize user profile if needed
        if user_id not in self.user_profiles:
            self._initialize_user_profile(user_id)

        logger.info(f"Started learning session {session_id} for user {user_id}")
        return session_id

    def end_learning_session(self) -> Optional[LearningSession]:
        """End current learning session."""
        if not self.current_session:
            return None

        self.current_session.end_time = datetime.utcnow()

        # Calculate session statistics
        session_duration = (
            self.current_session.end_time - self.current_session.start_time
        ).total_seconds() / 60

        logger.info(
            f"Ended learning session {self.current_session.session_id} "
            f"after {session_duration:.1f} minutes "
            f"({self.current_session.interactions} interactions)"
        )

        # Store session
        completed_session = self.current_session
        self.session_history.append(completed_session)
        self.current_session = None

        return completed_session

    def learn_from_interaction(
        self,
        state: Dict[str, Any],
        action: str,
        reward: float,
        next_state: Optional[Dict[str, Any]] = None,
        done: bool = False,
        feedback: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Learn from a single user interaction."""
        self.steps += 1

        # Add to experience buffer
        priority = abs(reward) + 0.1  # Higher priority for higher rewards
        self.experience_buffer.add(
            state=state,
            action=action,
            reward=reward,
            next_state=next_state,
            done=done,
            metadata=metadata or {},
            priority=priority,
        )

        # Process feedback if provided
        feedback_reward = 0.0
        if feedback:
            feedback_reward = self._process_textual_feedback(feedback, state, action)

        # Update current session
        if self.current_session:
            self.current_session.interactions += 1
            self.current_session.rewards_collected += 1 if reward > 0 else 0

        # Drift detection
        drift_detections = []
        if self.drift_detector:
            # Performance drift
            performance_detections = self.drift_detector.add_performance_sample(reward)
            drift_detections.extend(performance_detections)

            # Data distribution drift
            data_detections = self.drift_detector.add_data_sample(state)
            drift_detections.extend(data_detections)

            # Concept drift
            concept_detections = self.drift_detector.add_concept_sample(
                state, {"reward": reward}
            )
            drift_detections.extend(concept_detections)

            # Handle detected drifts
            for detection in drift_detections:
                if detection.drift_detected:
                    self._handle_drift_detection(detection)
                    if self.current_session:
                        self.current_session.drift_detections += 1

        # Trigger model update if needed
        update_result = None
        if self.steps % self.update_frequency == 0:
            update_result = self.incremental_update()

        learning_result = {
            "step": self.steps,
            "reward": reward,
            "feedback_reward": feedback_reward,
            "total_reward": reward + feedback_reward,
            "drift_detections": len([d for d in drift_detections if d.drift_detected]),
            "update_triggered": update_result is not None,
            "update_success": update_result.success if update_result else False,
            "buffer_size": len(self.experience_buffer),
        }

        return learning_result

    def process_user_feedback(
        self,
        user_id: str,
        task_context: Dict[str, Any],
        system_response: Any,
        feedback_type: str,
        feedback_value: Any,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> float:
        """Process structured user feedback."""
        feedback_sample = FeedbackSample(
            user_id=user_id,
            session_id=(
                self.current_session.session_id if self.current_session else "unknown"
            ),
            task_context=task_context,
            system_response=system_response,
            feedback_type=feedback_type,
            feedback_value=feedback_value,
            timestamp=datetime.utcnow(),
            metadata=metadata or {},
        )

        self.feedback_buffer.append(feedback_sample)

        # Process feedback
        reward = 0.0
        if feedback_type in self.feedback_processors:
            reward = self.feedback_processors[feedback_type](feedback_sample)
        else:
            logger.warning(f"Unknown feedback type: {feedback_type}")

        # Update user profile
        if self.personalization_enabled:
            self._update_user_profile(user_id, feedback_sample, reward)

        # Add to experience buffer as training signal
        self.experience_buffer.add(
            state=task_context,
            action=str(system_response),
            reward=reward,
            metadata={"feedback": True, "user_id": user_id},
        )

        if self.current_session:
            self.current_session.feedback_received += 1

        logger.debug(
            f"Processed {feedback_type} feedback from user {user_id}: reward={reward:.3f}"
        )

        return reward

    def incremental_update(self) -> Any:
        """Perform incremental model update."""
        if len(self.experience_buffer) < self.model_updater.config.batch_size:
            logger.debug("Insufficient data for incremental update")
            return None

        # Sample batch from experience buffer
        if hasattr(self.experience_buffer, "sample"):
            if isinstance(self.experience_buffer, PrioritizedExperienceReplay):
                batch, indices, weights = self.experience_buffer.sample(
                    self.model_updater.config.batch_size
                )
            else:
                batch = self.experience_buffer.sample(
                    self.model_updater.config.batch_size
                )
                indices = None
                weights = None
        else:
            batch = list(self.experience_buffer.buffer)[
                -self.model_updater.config.batch_size :
            ]
            indices = None
            weights = None

        # Add to model updater
        for experience in batch:
            self.model_updater.add_training_data(
                features=experience.state,
                labels={"action": experience.action, "reward": experience.reward},
                metadata=experience.metadata,
            )

        # Trigger update
        update_result = self.model_updater.trigger_update()

        # Update priorities for prioritized replay
        if indices is not None and hasattr(self.experience_buffer, "update_priorities"):
            # Calculate TD errors as priorities (simplified)
            td_errors = [abs(exp.reward) + 0.1 for exp in batch]
            self.experience_buffer.update_priorities(indices, np.array(td_errors))

        # Track adaptation
        if update_result.success:
            self.adaptation_count += 1
            self.learning_history.append(
                {
                    "timestamp": datetime.utcnow(),
                    "performance_change": update_result.performance_change,
                    "samples_used": len(batch),
                    "adaptation_count": self.adaptation_count,
                }
            )

            if self.current_session:
                self.current_session.performance_improvement += (
                    update_result.performance_change
                )

        logger.info(
            f"Incremental update: success={update_result.success}, "
            f"performance_change={update_result.performance_change:.4f}"
        )

        return update_result

    def get_personalized_prediction(
        self, user_id: str, context: Dict[str, Any]
    ) -> Tuple[Any, Dict[str, Any]]:
        """Get personalized prediction for user."""
        base_prediction = self._get_base_prediction(context)

        if not self.personalization_enabled or user_id not in self.user_profiles:
            return base_prediction, {"personalized": False}

        user_profile = self.user_profiles[user_id]

        # Apply user-specific adaptations
        personalized_prediction = self._apply_personalization(
            base_prediction, user_profile, context
        )

        personalization_info = {
            "personalized": True,
            "user_profile_data": len(user_profile.get("interactions", [])),
            "preference_strength": user_profile.get("preference_strength", 0.0),
            "adaptation_level": user_profile.get("adaptation_level", 0.0),
        }

        return personalized_prediction, personalization_info

    def get_learning_statistics(self) -> Dict[str, Any]:
        """Get comprehensive learning statistics."""
        stats = {
            "total_steps": self.steps,
            "adaptation_count": self.adaptation_count,
            "current_session": (
                asdict(self.current_session) if self.current_session else None
            ),
            "total_sessions": len(self.session_history),
            "experience_buffer": self.experience_buffer.get_statistics(),
            "model_updater": self.model_updater.get_statistics(),
            "feedback_buffer_size": len(self.feedback_buffer),
            "user_profiles": len(self.user_profiles),
            "personalization_enabled": self.personalization_enabled,
        }

        # Add drift detection stats if available
        if self.drift_detector:
            stats["drift_detection"] = self.drift_detector.get_overall_status()

        # Recent learning performance
        if self.learning_history:
            recent_learning = self.learning_history[-10:]
            stats["recent_performance"] = {
                "adaptations": len(recent_learning),
                "avg_performance_change": float(
                    np.mean([l["performance_change"] for l in recent_learning])
                ),
                "total_performance_improvement": float(
                    sum(l["performance_change"] for l in recent_learning)
                ),
            }

        # Session statistics
        if self.session_history:
            session_durations = [
                (s.end_time - s.start_time).total_seconds() / 60
                for s in self.session_history
                if s.end_time
            ]
            session_interactions = [s.interactions for s in self.session_history]

            stats["session_statistics"] = {
                "avg_duration_minutes": (
                    float(np.mean(session_durations)) if session_durations else 0
                ),
                "avg_interactions": (
                    float(np.mean(session_interactions)) if session_interactions else 0
                ),
                "total_interactions": sum(session_interactions),
                "avg_feedback_per_session": (
                    float(np.mean([s.feedback_received for s in self.session_history]))
                    if self.session_history
                    else 0
                ),
            }

        return stats

    def save_state(self, filepath: str) -> None:
        """Save learner state to file."""
        # Save experience buffer
        self.experience_buffer.save(f"{filepath}_experience.json")

        # Save main state
        state = {
            "steps": self.steps,
            "update_frequency": self.update_frequency,
            "adaptation_count": self.adaptation_count,
            "personalization_enabled": self.personalization_enabled,
            "learning_history": [
                {**entry, "timestamp": entry["timestamp"].isoformat()}
                for entry in self.learning_history
            ],
            "session_history": [
                {
                    **asdict(session),
                    "start_time": session.start_time.isoformat(),
                    "end_time": (
                        session.end_time.isoformat() if session.end_time else None
                    ),
                }
                for session in self.session_history
            ],
            "user_profiles": {
                user_id: {
                    **profile,
                    "last_interaction": profile.get(
                        "last_interaction", datetime.utcnow()
                    ).isoformat(),
                }
                for user_id, profile in self.user_profiles.items()
            },
        }

        with open(f"{filepath}_learner.json", "w") as f:
            json.dump(state, f, indent=2)

        logger.info(f"Saved online learner state to {filepath}")

    def load_state(self, filepath: str) -> None:
        """Load learner state from file."""
        # Load experience buffer
        self.experience_buffer.load(f"{filepath}_experience.json")

        # Load main state
        with open(f"{filepath}_learner.json", "r") as f:
            state = json.load(f)

        self.steps = state["steps"]
        self.update_frequency = state["update_frequency"]
        self.adaptation_count = state["adaptation_count"]
        self.personalization_enabled = state["personalization_enabled"]

        # Reconstruct learning history
        self.learning_history = []
        for entry in state["learning_history"]:
            entry["timestamp"] = datetime.fromisoformat(entry["timestamp"])
            self.learning_history.append(entry)

        # Reconstruct session history
        self.session_history = []
        for session_data in state["session_history"]:
            session_data["start_time"] = datetime.fromisoformat(
                session_data["start_time"]
            )
            if session_data["end_time"]:
                session_data["end_time"] = datetime.fromisoformat(
                    session_data["end_time"]
                )
            session = LearningSession(**session_data)
            self.session_history.append(session)

        # Reconstruct user profiles
        self.user_profiles = {}
        for user_id, profile in state["user_profiles"].items():
            if "last_interaction" in profile:
                profile["last_interaction"] = datetime.fromisoformat(
                    profile["last_interaction"]
                )
            self.user_profiles[user_id] = profile

        logger.info(f"Loaded online learner state from {filepath}")

    # Private methods

    def _default_performance_metric(self, prediction: Any, labels: Any) -> float:
        """Default performance metric."""
        if isinstance(labels, dict) and "reward" in labels:
            # Use reward as performance indicator
            return float(labels["reward"])
        return 0.0

    def _initialize_user_profile(self, user_id: str) -> None:
        """Initialize user profile."""
        self.user_profiles[user_id] = {
            "interactions": [],
            "preferences": {},
            "feedback_history": [],
            "performance_history": [],
            "preference_strength": 0.0,
            "adaptation_level": 0.0,
            "last_interaction": datetime.utcnow(),
        }

    def _update_user_profile(
        self, user_id: str, feedback_sample: FeedbackSample, reward: float
    ) -> None:
        """Update user profile with feedback information."""
        if user_id not in self.user_profiles:
            self._initialize_user_profile(user_id)

        profile = self.user_profiles[user_id]

        # Add interaction
        profile["interactions"].append(
            {
                "timestamp": feedback_sample.timestamp.isoformat(),
                "feedback_type": feedback_sample.feedback_type,
                "reward": reward,
            }
        )

        # Update preferences
        if feedback_sample.feedback_type == "preference":
            preference_key = str(feedback_sample.system_response)
            if preference_key not in profile["preferences"]:
                profile["preferences"][preference_key] = 0.0
            profile["preferences"][preference_key] += reward

        # Update statistics
        profile["feedback_history"].append(reward)
        profile["performance_history"].append(reward)

        # Calculate preference strength
        if profile["feedback_history"]:
            profile["preference_strength"] = float(
                np.std(profile["feedback_history"][-20:])
            )

        # Calculate adaptation level
        if len(profile["performance_history"]) > 10:
            recent_perf = profile["performance_history"][-10:]
            earlier_perf = (
                profile["performance_history"][-20:-10]
                if len(profile["performance_history"]) > 20
                else profile["performance_history"][:-10]
            )
            if earlier_perf:
                profile["adaptation_level"] = float(
                    np.mean(recent_perf) - np.mean(earlier_perf)
                )

        profile["last_interaction"] = feedback_sample.timestamp

        # Keep profile size manageable
        if len(profile["interactions"]) > 1000:
            profile["interactions"] = profile["interactions"][-500:]
        if len(profile["feedback_history"]) > 1000:
            profile["feedback_history"] = profile["feedback_history"][-500:]
        if len(profile["performance_history"]) > 1000:
            profile["performance_history"] = profile["performance_history"][-500:]

    def _process_rating_feedback(self, feedback: FeedbackSample) -> float:
        """Process rating feedback (1-5 scale)."""
        rating = float(feedback.feedback_value)
        # Normalize to [-1, 1] range
        normalized_rating = (rating - 3.0) / 2.0
        return normalized_rating

    def _process_correction_feedback(self, feedback: FeedbackSample) -> float:
        """Process correction feedback."""
        # Correction indicates system was wrong
        return -0.5

    def _process_preference_feedback(self, feedback: FeedbackSample) -> float:
        """Process preference feedback."""
        # Preference indicates positive/negative choice
        if feedback.feedback_value in ["positive", "like", "good", True]:
            return 0.8
        elif feedback.feedback_value in ["negative", "dislike", "bad", False]:
            return -0.8
        else:
            return 0.0

    def _process_binary_feedback(self, feedback: FeedbackSample) -> float:
        """Process binary feedback (thumbs up/down)."""
        if feedback.feedback_value in [1, "up", "positive", True]:
            return 1.0
        elif feedback.feedback_value in [0, "down", "negative", False]:
            return -1.0
        else:
            return 0.0

    def _process_textual_feedback(
        self, feedback_text: str, state: Dict, action: str
    ) -> float:
        """Process free-form textual feedback."""
        # Simple sentiment analysis
        positive_words = [
            "good",
            "great",
            "excellent",
            "helpful",
            "useful",
            "correct",
            "right",
        ]
        negative_words = ["bad", "wrong", "unhelpful", "useless", "incorrect", "error"]

        text_lower = feedback_text.lower()

        positive_count = sum(1 for word in positive_words if word in text_lower)
        negative_count = sum(1 for word in negative_words if word in text_lower)

        if positive_count > negative_count:
            return 0.5 * (positive_count - negative_count) / len(feedback_text.split())
        elif negative_count > positive_count:
            return -0.5 * (negative_count - positive_count) / len(feedback_text.split())
        else:
            return 0.0

    def _handle_drift_detection(self, detection: DriftDetection) -> None:
        """Handle detected drift."""
        logger.warning(
            f"Handling {detection.drift_type.value} drift: {detection.recommended_action}"
        )

        if detection.recommended_action == "retrain_model":
            # Trigger immediate model update
            self.incremental_update()
        elif detection.recommended_action == "adapt_model":
            # Increase update frequency temporarily
            self.update_frequency = max(10, self.update_frequency // 2)
        elif detection.recommended_action == "investigate_further":
            # Log for manual review
            logger.info(f"Drift detected but not handled automatically: {detection}")

    def _get_base_prediction(self, context: Dict[str, Any]) -> Any:
        """Get base prediction from model."""
        if hasattr(self.base_model, "predict"):
            return self.base_model.predict(context)
        else:
            # Fallback
            return context.get("default_action", "unknown")

    def _apply_personalization(
        self,
        base_prediction: Any,
        user_profile: Dict[str, Any],
        context: Dict[str, Any],
    ) -> Any:
        """Apply user-specific personalization to prediction."""
        # Simple personalization: adjust based on user preferences
        preferences = user_profile.get("preferences", {})

        if str(base_prediction) in preferences:
            preference_score = preferences[str(base_prediction)]

            # If user strongly dislikes this prediction, try alternative
            if preference_score < -1.0:
                # Find alternative with better preference
                best_alternative = None
                best_score = preference_score

                for alt_pred, alt_score in preferences.items():
                    if alt_score > best_score:
                        best_alternative = alt_pred
                        best_score = alt_score

                if best_alternative:
                    return best_alternative

        return base_prediction
