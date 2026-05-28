"""Trace Analyzer

Records execution traces and provides replay capabilities for workflow debugging.
Analyzes execution patterns, performance bottlenecks, and provides insights.
"""

import asyncio
import json
import logging
import time
import statistics
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Set, Tuple, Callable
from dataclasses import dataclass, asdict, field
from enum import Enum
import uuid
import copy
from collections import defaultdict, deque


logger = logging.getLogger(__name__)


class EventType(str, Enum):
    """Types of execution events"""
    EXECUTION_START = "execution_start"
    EXECUTION_END = "execution_end"
    NODE_ENTER = "node_enter"
    NODE_EXIT = "node_exit"
    NODE_SUCCESS = "node_success"
    NODE_ERROR = "node_error"
    BREAKPOINT_HIT = "breakpoint_hit"
    VARIABLE_CHANGE = "variable_change"
    CONDITION_EVALUATION = "condition_evaluation"
    CUSTOM = "custom"


class SeverityLevel(str, Enum):
    """Event severity levels"""
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class ExecutionEvent:
    """Represents a single execution event"""
    event_id: str
    event_type: EventType
    timestamp: datetime
    node_id: Optional[str] = None
    thread_id: Optional[str] = None
    severity: SeverityLevel = SeverityLevel.INFO
    message: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    duration_ms: Optional[float] = None
    memory_delta: Optional[int] = None
    
    def to_dict(self) -> Dict:
        data = asdict(self)
        data['timestamp'] = self.timestamp.isoformat()
        return data
        
    @classmethod
    def from_dict(cls, data: Dict) -> 'ExecutionEvent':
        if 'timestamp' in data:
            data['timestamp'] = datetime.fromisoformat(data['timestamp'])
        return cls(**data)


@dataclass
class ExecutionTrace:
    """Complete execution trace"""
    trace_id: str
    dag_id: str
    session_id: str
    start_time: datetime
    end_time: Optional[datetime] = None
    events: List[ExecutionEvent] = field(default_factory=list)
    total_duration_ms: Optional[float] = None
    success: bool = True
    error_message: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        data = asdict(self)
        data['start_time'] = self.start_time.isoformat()
        if self.end_time:
            data['end_time'] = self.end_time.isoformat()
        data['events'] = [event.to_dict() for event in self.events]
        return data
        
    @classmethod
    def from_dict(cls, data: Dict) -> 'ExecutionTrace':
        if 'start_time' in data:
            data['start_time'] = datetime.fromisoformat(data['start_time'])
        if 'end_time' in data and data['end_time']:
            data['end_time'] = datetime.fromisoformat(data['end_time'])
            
        events = []
        for event_data in data.get('events', []):
            events.append(ExecutionEvent.from_dict(event_data))
        data['events'] = events
        
        return cls(**data)


@dataclass
class TraceAnalysis:
    """Analysis results of an execution trace"""
    trace_id: str
    analysis_time: datetime
    total_duration_ms: float
    total_events: int
    
    # Performance analysis
    bottlenecks: List[Dict[str, Any]] = field(default_factory=list)
    critical_path: List[str] = field(default_factory=list)
    node_timings: Dict[str, float] = field(default_factory=dict)
    
    # Error analysis
    errors: List[Dict[str, Any]] = field(default_factory=list)
    anomalies: List[Dict[str, Any]] = field(default_factory=list)
    
    # Optimization suggestions
    suggestions: List[str] = field(default_factory=list)
    
    # Statistics
    statistics: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        data = asdict(self)
        data['analysis_time'] = self.analysis_time.isoformat()
        return data


@dataclass 
class ReplayState:
    """State for trace replay"""
    trace_id: str
    current_event_index: int
    replay_speed: float  # 1.0 = normal speed
    is_playing: bool
    is_paused: bool
    start_time: datetime
    variables: Dict[str, Any] = field(default_factory=dict)
    node_results: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        data = asdict(self)
        data['start_time'] = self.start_time.isoformat()
        return data


class ReplayEngine:
    """Engine for replaying execution traces"""
    
    def __init__(self):
        self.active_replays: Dict[str, ReplayState] = {}
        self.replay_callbacks: Dict[str, List[Callable]] = defaultdict(list)
        
    async def start_replay(self, 
                          trace: ExecutionTrace, 
                          speed: float = 1.0) -> str:
        """Start replaying a trace"""
        replay_id = f"replay_{trace.trace_id}_{int(time.time())}"
        
        replay_state = ReplayState(
            trace_id=trace.trace_id,
            current_event_index=0,
            replay_speed=speed,
            is_playing=True,
            is_paused=False,
            start_time=datetime.utcnow()
        )
        
        self.active_replays[replay_id] = replay_state
        
        # Start replay task
        asyncio.create_task(self._replay_loop(replay_id, trace))
        
        return replay_id
        
    async def pause_replay(self, replay_id: str) -> bool:
        """Pause a replay"""
        if replay_id in self.active_replays:
            self.active_replays[replay_id].is_paused = True
            return True
        return False
        
    async def resume_replay(self, replay_id: str) -> bool:
        """Resume a paused replay"""
        if replay_id in self.active_replays:
            self.active_replays[replay_id].is_paused = False
            return True
        return False
        
    async def stop_replay(self, replay_id: str) -> bool:
        """Stop a replay"""
        if replay_id in self.active_replays:
            self.active_replays[replay_id].is_playing = False
            del self.active_replays[replay_id]
            return True
        return False
        
    async def set_replay_speed(self, replay_id: str, speed: float) -> bool:
        """Set replay speed"""
        if replay_id in self.active_replays:
            self.active_replays[replay_id].replay_speed = speed
            return True
        return False
        
    def add_replay_callback(self, replay_id: str, callback: Callable):
        """Add callback for replay events"""
        self.replay_callbacks[replay_id].append(callback)
        
    async def _replay_loop(self, replay_id: str, trace: ExecutionTrace):
        """Main replay loop"""
        try:
            replay_state = self.active_replays[replay_id]
            
            while (replay_state.is_playing and 
                   replay_state.current_event_index < len(trace.events)):
                
                # Check if paused
                while replay_state.is_paused and replay_state.is_playing:
                    await asyncio.sleep(0.1)
                    
                if not replay_state.is_playing:
                    break
                    
                # Get current event
                event = trace.events[replay_state.current_event_index]
                
                # Calculate delay based on speed
                if replay_state.current_event_index > 0:
                    prev_event = trace.events[replay_state.current_event_index - 1]
                    time_diff = (event.timestamp - prev_event.timestamp).total_seconds()
                    delay = time_diff / replay_state.replay_speed
                    
                    if delay > 0:
                        await asyncio.sleep(delay)
                        
                # Process event
                await self._process_replay_event(replay_id, event, replay_state)
                
                # Move to next event
                replay_state.current_event_index += 1
                
            # Replay completed
            if replay_id in self.active_replays:
                del self.active_replays[replay_id]
                
        except Exception as e:
            logger.error(f"Replay {replay_id} failed: {e}")
            if replay_id in self.active_replays:
                del self.active_replays[replay_id]
                
    async def _process_replay_event(self, 
                                  replay_id: str, 
                                  event: ExecutionEvent,
                                  replay_state: ReplayState):
        """Process a single replay event"""
        try:
            # Update replay state based on event
            if event.event_type == EventType.VARIABLE_CHANGE:
                var_name = event.metadata.get('variable_name')
                var_value = event.metadata.get('new_value')
                if var_name and var_value is not None:
                    replay_state.variables[var_name] = var_value
                    
            elif event.event_type == EventType.NODE_SUCCESS:
                node_id = event.node_id
                result = event.metadata.get('result')
                if node_id and result is not None:
                    replay_state.node_results[node_id] = result
                    
            # Call callbacks
            for callback in self.replay_callbacks.get(replay_id, []):
                try:
                    if asyncio.iscoroutinefunction(callback):
                        await callback(replay_id, event, replay_state)
                    else:
                        callback(replay_id, event, replay_state)
                except Exception as e:
                    logger.warning(f"Replay callback failed: {e}")
                    
        except Exception as e:
            logger.error(f"Failed to process replay event: {e}")
            
    def get_replay_state(self, replay_id: str) -> Optional[Dict]:
        """Get current replay state"""
        if replay_id in self.active_replays:
            return self.active_replays[replay_id].to_dict()
        return None


class ExecutionStatistics:
    """Calculates various execution statistics"""
    
    def calculate_node_statistics(self, events: List[ExecutionEvent]) -> Dict[str, Any]:
        """Calculate statistics per node"""
        node_stats = defaultdict(lambda: {
            'enter_count': 0,
            'success_count': 0,
            'error_count': 0,
            'total_time_ms': 0.0,
            'min_time_ms': float('inf'),
            'max_time_ms': 0.0,
            'execution_times': []
        })
        
        # Track node entry/exit times
        node_times = {}
        
        for event in events:
            if not event.node_id:
                continue
                
            stats = node_stats[event.node_id]
            
            if event.event_type == EventType.NODE_ENTER:
                stats['enter_count'] += 1
                node_times[event.node_id] = event.timestamp
                
            elif event.event_type == EventType.NODE_EXIT:
                if event.node_id in node_times:
                    duration = (event.timestamp - node_times[event.node_id]).total_seconds() * 1000
                    stats['execution_times'].append(duration)
                    stats['total_time_ms'] += duration
                    stats['min_time_ms'] = min(stats['min_time_ms'], duration)
                    stats['max_time_ms'] = max(stats['max_time_ms'], duration)
                    
            elif event.event_type == EventType.NODE_SUCCESS:
                stats['success_count'] += 1
                
            elif event.event_type == EventType.NODE_ERROR:
                stats['error_count'] += 1
                
        # Calculate averages and clean up
        for node_id, stats in node_stats.items():
            if stats['execution_times']:
                stats['avg_time_ms'] = statistics.mean(stats['execution_times'])
                stats['median_time_ms'] = statistics.median(stats['execution_times'])
                if len(stats['execution_times']) > 1:
                    stats['std_dev_ms'] = statistics.stdev(stats['execution_times'])
                else:
                    stats['std_dev_ms'] = 0.0
            else:
                stats['avg_time_ms'] = 0.0
                stats['median_time_ms'] = 0.0
                stats['std_dev_ms'] = 0.0
                
            if stats['min_time_ms'] == float('inf'):
                stats['min_time_ms'] = 0.0
                
            # Calculate success rate
            total_executions = stats['success_count'] + stats['error_count']
            stats['success_rate'] = (stats['success_count'] / total_executions * 100 
                                   if total_executions > 0 else 0.0)
                
        return dict(node_stats)
        
    def calculate_overall_statistics(self, trace: ExecutionTrace) -> Dict[str, Any]:
        """Calculate overall trace statistics"""
        if not trace.events:
            return {}
            
        total_events = len(trace.events)
        
        # Count events by type
        event_type_counts = defaultdict(int)
        for event in trace.events:
            event_type_counts[event.event_type.value] += 1
            
        # Count events by severity
        severity_counts = defaultdict(int)
        for event in trace.events:
            severity_counts[event.severity.value] += 1
            
        # Time analysis
        start_time = trace.start_time
        end_time = trace.end_time or datetime.utcnow()
        total_duration = (end_time - start_time).total_seconds() * 1000
        
        # Event frequency
        event_frequency = total_events / (total_duration / 1000) if total_duration > 0 else 0
        
        return {
            'total_events': total_events,
            'total_duration_ms': total_duration,
            'event_frequency_per_second': event_frequency,
            'event_type_counts': dict(event_type_counts),
            'severity_counts': dict(severity_counts),
            'success_rate': ((event_type_counts.get('node_success', 0) / 
                             max(1, event_type_counts.get('node_success', 0) + 
                                 event_type_counts.get('node_error', 0))) * 100)
        }


class TraceAnalyzer:
    """Main trace analyzer"""
    
    def __init__(self, max_events: int = 10000):
        self.max_events = max_events
        self.traces: Dict[str, ExecutionTrace] = {}
        self.replay_engine = ReplayEngine()
        self.statistics_calculator = ExecutionStatistics()
        
        # Analysis cache
        self.analysis_cache: Dict[str, TraceAnalysis] = {}
        
        logger.info(f"Trace analyzer initialized with max {max_events} events per trace")
        
    async def start_trace(self, dag_id: str, session_id: str) -> str:
        """Start a new execution trace"""
        trace_id = f"trace_{dag_id}_{int(time.time())}_{uuid.uuid4().hex[:8]}"
        
        trace = ExecutionTrace(
            trace_id=trace_id,
            dag_id=dag_id,
            session_id=session_id,
            start_time=datetime.utcnow()
        )
        
        self.traces[trace_id] = trace
        
        logger.info(f"Started trace {trace_id} for DAG {dag_id}")
        return trace_id
        
    async def end_trace(self, trace_id: str, success: bool = True, error_message: str = None):
        """End an execution trace"""
        if trace_id not in self.traces:
            return False
            
        trace = self.traces[trace_id]
        trace.end_time = datetime.utcnow()
        trace.success = success
        trace.error_message = error_message
        
        if trace.start_time and trace.end_time:
            trace.total_duration_ms = (trace.end_time - trace.start_time).total_seconds() * 1000
            
        logger.info(f"Ended trace {trace_id} - Success: {success}")
        return True
        
    async def record_event(self, event: ExecutionEvent, trace_id: str = None) -> bool:
        """Record an execution event"""
        
        # If no trace_id specified, try to find active trace
        if not trace_id:
            # Use the most recent active trace
            active_traces = [
                t for t in self.traces.values() 
                if t.end_time is None
            ]
            
            if not active_traces:
                logger.warning("No active trace to record event")
                return False
                
            trace = max(active_traces, key=lambda t: t.start_time)
        else:
            if trace_id not in self.traces:
                logger.warning(f"Trace {trace_id} not found")
                return False
            trace = self.traces[trace_id]
            
        # Add event to trace
        trace.events.append(event)
        
        # Trim events if exceeding max
        if len(trace.events) > self.max_events:
            trace.events = trace.events[-self.max_events // 2:]
            logger.warning(f"Trimmed trace {trace.trace_id} to {len(trace.events)} events")
            
        return True
        
    async def get_trace(self, trace_id: str) -> Optional[ExecutionTrace]:
        """Get a trace by ID"""
        return self.traces.get(trace_id)
        
    async def get_all_traces(self) -> List[ExecutionTrace]:
        """Get all traces"""
        return list(self.traces.values())
        
    async def delete_trace(self, trace_id: str) -> bool:
        """Delete a trace"""
        if trace_id in self.traces:
            del self.traces[trace_id]
            
            # Remove from analysis cache
            if trace_id in self.analysis_cache:
                del self.analysis_cache[trace_id]
                
            logger.info(f"Deleted trace {trace_id}")
            return True
        return False
        
    async def analyze_trace(self, trace_id: str) -> Optional[TraceAnalysis]:
        """Analyze a trace for bottlenecks and insights"""
        
        # Check cache first
        if trace_id in self.analysis_cache:
            return self.analysis_cache[trace_id]
            
        if trace_id not in self.traces:
            return None
            
        trace = self.traces[trace_id]
        
        # Calculate statistics
        overall_stats = self.statistics_calculator.calculate_overall_statistics(trace)
        node_stats = self.statistics_calculator.calculate_node_statistics(trace.events)
        
        # Find bottlenecks
        bottlenecks = []
        if node_stats:
            # Sort nodes by average execution time
            sorted_nodes = sorted(
                node_stats.items(),
                key=lambda x: x[1]['avg_time_ms'],
                reverse=True
            )
            
            # Top 3 slowest nodes are bottlenecks
            for node_id, stats in sorted_nodes[:3]:
                if stats['avg_time_ms'] > 0:
                    bottlenecks.append({
                        'node_id': node_id,
                        'avg_time_ms': stats['avg_time_ms'],
                        'percentage_of_total': (stats['total_time_ms'] / 
                                              max(1, overall_stats.get('total_duration_ms', 1)) * 100),
                        'reason': f"Average execution time: {stats['avg_time_ms']:.2f}ms"
                    })
                    
        # Find critical path (simplified)
        critical_path = []
        if node_stats:
            # Critical path is the sequence of nodes with longest total execution time
            sorted_by_total = sorted(
                node_stats.items(),
                key=lambda x: x[1]['total_time_ms'],
                reverse=True
            )
            critical_path = [node_id for node_id, _ in sorted_by_total[:5]]
            
        # Find errors and anomalies
        errors = []
        anomalies = []
        
        for event in trace.events:
            if event.event_type == EventType.NODE_ERROR:
                errors.append({
                    'node_id': event.node_id,
                    'timestamp': event.timestamp.isoformat(),
                    'message': event.message,
                    'metadata': event.metadata
                })
                
            # Detect anomalies (e.g., unusually long execution times)
            if (event.duration_ms and event.duration_ms > 10000):  # > 10 seconds
                anomalies.append({
                    'node_id': event.node_id,
                    'type': 'long_execution',
                    'duration_ms': event.duration_ms,
                    'timestamp': event.timestamp.isoformat()
                })
                
        # Generate suggestions
        suggestions = []
        
        if bottlenecks:
            suggestions.append(f"Consider optimizing {bottlenecks[0]['node_id']} - it accounts for "
                             f"{bottlenecks[0]['percentage_of_total']:.1f}% of execution time")
                             
        if len(errors) > 0:
            suggestions.append(f"Fix {len(errors)} error(s) to improve reliability")
            
        if len(anomalies) > 0:
            suggestions.append(f"Investigate {len(anomalies)} performance anomaly(ies)")
            
        # Create analysis
        analysis = TraceAnalysis(
            trace_id=trace_id,
            analysis_time=datetime.utcnow(),
            total_duration_ms=overall_stats.get('total_duration_ms', 0.0),
            total_events=overall_stats.get('total_events', 0),
            bottlenecks=bottlenecks,
            critical_path=critical_path,
            node_timings={node_id: stats['avg_time_ms'] for node_id, stats in node_stats.items()},
            errors=errors,
            anomalies=anomalies,
            suggestions=suggestions,
            statistics={
                'overall': overall_stats,
                'nodes': node_stats
            }
        )
        
        # Cache analysis
        self.analysis_cache[trace_id] = analysis
        
        return analysis
        
    async def compare_traces(self, trace_ids: List[str]) -> Dict[str, Any]:
        """Compare multiple traces"""
        if len(trace_ids) < 2:
            return {"error": "At least 2 traces required for comparison"}
            
        traces = []
        for trace_id in trace_ids:
            if trace_id in self.traces:
                traces.append(self.traces[trace_id])
            else:
                return {"error": f"Trace {trace_id} not found"}
                
        # Compare durations
        durations = [
            (trace.end_time - trace.start_time).total_seconds() * 1000
            for trace in traces if trace.end_time
        ]
        
        # Compare event counts
        event_counts = [len(trace.events) for trace in traces]
        
        # Compare success rates
        success_rates = []
        for trace in traces:
            success_events = len([e for e in trace.events if e.event_type == EventType.NODE_SUCCESS])
            error_events = len([e for e in trace.events if e.event_type == EventType.NODE_ERROR])
            total = success_events + error_events
            success_rate = (success_events / total * 100) if total > 0 else 100.0
            success_rates.append(success_rate)
            
        return {
            'trace_count': len(traces),
            'duration_comparison': {
                'durations_ms': durations,
                'min_duration_ms': min(durations) if durations else 0,
                'max_duration_ms': max(durations) if durations else 0,
                'avg_duration_ms': statistics.mean(durations) if durations else 0,
                'improvement_pct': ((max(durations) - min(durations)) / max(durations) * 100) if durations else 0
            },
            'event_count_comparison': {
                'event_counts': event_counts,
                'min_events': min(event_counts),
                'max_events': max(event_counts),
                'avg_events': statistics.mean(event_counts)
            },
            'success_rate_comparison': {
                'success_rates': success_rates,
                'min_success_rate': min(success_rates),
                'max_success_rate': max(success_rates),
                'avg_success_rate': statistics.mean(success_rates)
            }
        }
        
    async def replay_trace(self, trace_id: str, speed: float = 1.0) -> Optional[str]:
        """Start replaying a trace"""
        if trace_id not in self.traces:
            return None
            
        trace = self.traces[trace_id]
        replay_id = await self.replay_engine.start_replay(trace, speed)
        
        return replay_id
        
    async def control_replay(self, 
                           replay_id: str, 
                           action: str, 
                           **kwargs) -> bool:
        """Control trace replay"""
        if action == "pause":
            return await self.replay_engine.pause_replay(replay_id)
        elif action == "resume":
            return await self.replay_engine.resume_replay(replay_id)
        elif action == "stop":
            return await self.replay_engine.stop_replay(replay_id)
        elif action == "speed":
            speed = kwargs.get('speed', 1.0)
            return await self.replay_engine.set_replay_speed(replay_id, speed)
        else:
            return False
            
    def get_trace_summary(self) -> Dict[str, Any]:
        """Get summary of all traces"""
        total_traces = len(self.traces)
        completed_traces = len([t for t in self.traces.values() if t.end_time])
        successful_traces = len([t for t in self.traces.values() if t.success])
        
        return {
            'total_traces': total_traces,
            'completed_traces': completed_traces,
            'successful_traces': successful_traces,
            'success_rate': (successful_traces / max(1, completed_traces) * 100),
            'active_traces': total_traces - completed_traces,
            'cache_size': len(self.analysis_cache)
        }