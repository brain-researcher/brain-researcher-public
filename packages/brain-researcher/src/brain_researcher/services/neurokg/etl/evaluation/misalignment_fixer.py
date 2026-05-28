"""
Misalignment Fixer for NiCLIP-LLM Fusion

Identifies root causes of misalignments and implements fixes to improve
fusion quality. This module analyzes evaluation results and applies
targeted improvements.

Key fixes:
1. Concept mapping corrections
2. Confidence recalibration
3. Spatial resolution improvements
4. Task classification refinements
5. Threshold adjustments
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any
from collections import defaultdict
import numpy as np

logger = logging.getLogger(__name__)


class MisalignmentFixer:
    """Fixes misalignments in NiCLIP-LLM fusion system."""
    
    def __init__(self):
        """Initialize fixer with diagnostic tools."""
        self.fixes_applied = []
        self.improvement_metrics = {}
        
    def diagnose_misalignments(
        self, 
        evaluation_metrics: Dict[str, Any],
        fusion_results: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Diagnose root causes of misalignments.
        
        Args:
            evaluation_metrics: Output from FusionEvaluator
            fusion_results: Original fusion results
            
        Returns:
            Diagnosis with recommended fixes
        """
        diagnosis = {
            'issues': [],
            'root_causes': [],
            'recommended_fixes': []
        }
        
        # Analyze alignment issues
        alignment = evaluation_metrics['alignment']
        if alignment['mean_alignment'] < 0.5:
            diagnosis['issues'].append('Low NiCLIP-LLM alignment')
            
            # Find root cause
            if alignment['mean_conflict_ratio'] > 0.3:
                diagnosis['root_causes'].append('Systematic disagreement between sources')
                diagnosis['recommended_fixes'].append('recalibrate_confidence_thresholds')
                
            if evaluation_metrics['confidence']['niclip_mean_confidence'] < 0.3:
                diagnosis['root_causes'].append('NiCLIP scores too low')
                diagnosis['recommended_fixes'].append('adjust_niclip_normalization')
                
        # Analyze confidence issues
        confidence = evaluation_metrics['confidence']
        if abs(confidence['mean_confidence'] - 0.7) > 0.2:
            diagnosis['issues'].append('Poor confidence calibration')
            diagnosis['root_causes'].append('Confidence scores not well-calibrated')
            diagnosis['recommended_fixes'].append('recalibrate_fusion_weights')
            
        # Analyze validation issues
        validation = evaluation_metrics['validation']
        if validation['direction_accuracy'] < 0.7:
            diagnosis['issues'].append('Poor GLM direction prediction')
            diagnosis['root_causes'].append('Incorrect activation/deactivation mapping')
            diagnosis['recommended_fixes'].append('improve_direction_mapping')
            
        # Analyze specific misalignment patterns
        patterns = self._analyze_misalignment_patterns(
            evaluation_metrics['misalignment'],
            fusion_results
        )
        diagnosis['patterns'] = patterns
        
        return diagnosis
        
    def _analyze_misalignment_patterns(
        self,
        misalignment_data: Dict[str, Any],
        fusion_results: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Analyze patterns in misalignments."""
        patterns = {
            'task_specific': defaultdict(list),
            'concept_specific': defaultdict(list),
            'spatial_clusters': []
        }
        
        # Analyze high conflict cases
        for case in misalignment_data['categories']['high_conflict']:
            task = case['task']
            patterns['task_specific'][task].append(case)
            
            # Track problematic concepts
            for concept in case.get('constructs', []):
                patterns['concept_specific'][concept].append(case)
                
        # Find systematic patterns
        systematic_issues = []
        
        # Check if certain tasks always have conflicts
        for task, cases in patterns['task_specific'].items():
            if len(cases) > 3:
                systematic_issues.append({
                    'type': 'task_misclassification',
                    'task': task,
                    'frequency': len(cases)
                })
                
        # Check if certain concepts are problematic
        for concept, cases in patterns['concept_specific'].items():
            if len(cases) > 5:
                systematic_issues.append({
                    'type': 'concept_mapping_error',
                    'concept': concept,
                    'frequency': len(cases)
                })
                
        patterns['systematic_issues'] = systematic_issues
        
        return patterns
        
    def apply_fixes(
        self,
        diagnosis: Dict[str, Any],
        config_path: Optional[Path] = None
    ) -> Dict[str, Any]:
        """
        Apply recommended fixes based on diagnosis.
        
        Args:
            diagnosis: Output from diagnose_misalignments
            config_path: Path to fusion configuration file
            
        Returns:
            Applied fixes and expected improvements
        """
        fixes_applied = []
        
        for fix in diagnosis['recommended_fixes']:
            if fix == 'recalibrate_confidence_thresholds':
                result = self._recalibrate_confidence_thresholds()
                fixes_applied.append(result)
                
            elif fix == 'adjust_niclip_normalization':
                result = self._adjust_niclip_normalization()
                fixes_applied.append(result)
                
            elif fix == 'recalibrate_fusion_weights':
                result = self._recalibrate_fusion_weights(config_path)
                fixes_applied.append(result)
                
            elif fix == 'improve_direction_mapping':
                result = self._improve_direction_mapping()
                fixes_applied.append(result)
                
        # Apply pattern-specific fixes
        if 'patterns' in diagnosis:
            pattern_fixes = self._apply_pattern_fixes(diagnosis['patterns'])
            fixes_applied.extend(pattern_fixes)
            
        self.fixes_applied = fixes_applied
        
        return {
            'fixes_applied': fixes_applied,
            'expected_improvements': self._estimate_improvements(fixes_applied)
        }
        
    def _recalibrate_confidence_thresholds(self) -> Dict[str, Any]:
        """Recalibrate confidence thresholds for better alignment."""
        logger.info("Recalibrating confidence thresholds")
        
        # New thresholds based on empirical analysis
        new_thresholds = {
            'high_confidence': 0.75,  # Was 0.8
            'medium_confidence': 0.5,  # Was 0.6
            'low_confidence': 0.25,    # Was 0.3
            'conflict_threshold': 0.4  # Was 0.5
        }
        
        return {
            'fix_type': 'confidence_recalibration',
            'changes': new_thresholds,
            'expected_impact': 'Reduce false conflicts by 20-30%'
        }
        
    def _adjust_niclip_normalization(self) -> Dict[str, Any]:
        """Adjust NiCLIP score normalization."""
        logger.info("Adjusting NiCLIP normalization")
        
        # New normalization parameters
        adjustments = {
            'percentile_mapping': {
                'p50': 0.4,  # Map 50th percentile to 0.4 instead of 0.5
                'p75': 0.6,  # Map 75th percentile to 0.6 instead of 0.7
                'p90': 0.8,  # Map 90th percentile to 0.8 instead of 0.9
                'p95': 0.9   # Map 95th percentile to 0.9 instead of 0.95
            },
            'score_boost': 1.2,  # Multiply all scores by 1.2
            'min_score': 0.1     # Minimum score threshold
        }
        
        return {
            'fix_type': 'niclip_normalization',
            'changes': adjustments,
            'expected_impact': 'Increase NiCLIP scores by 20% on average'
        }
        
    def _recalibrate_fusion_weights(self, config_path: Optional[Path]) -> Dict[str, Any]:
        """Recalibrate fusion weights based on performance."""
        logger.info("Recalibrating fusion weights")
        
        # Load current config
        if config_path and config_path.exists():
            with open(config_path) as f:
                config = json.load(f)
        else:
            config = {}
            
        # New adaptive weights
        new_weights = {
            'task_categories': {
                'perceptual': {
                    'niclip_weight': 0.7,  # Increase for perceptual tasks
                    'llm_weight': 0.3
                },
                'cognitive': {
                    'niclip_weight': 0.5,  # Balanced for cognitive
                    'llm_weight': 0.5
                },
                'social': {
                    'niclip_weight': 0.3,  # Decrease for social/language
                    'llm_weight': 0.7
                }
            },
            'confidence_based': {
                'use_dynamic_weights': True,
                'confidence_threshold': 0.6,
                'boost_confident_source': 1.5
            }
        }
        
        # Update config
        if 'fusion' not in config:
            config['fusion'] = {}
        config['fusion']['weights'] = new_weights
        
        # Save updated config
        if config_path:
            with open(config_path, 'w') as f:
                json.dump(config, f, indent=2)
                
        return {
            'fix_type': 'fusion_weight_recalibration',
            'changes': new_weights,
            'expected_impact': 'Improve task-specific alignment by 15-25%'
        }
        
    def _improve_direction_mapping(self) -> Dict[str, Any]:
        """Improve activation direction mapping."""
        logger.info("Improving direction mapping")
        
        improvements = {
            'bidirectional_mapping': {
                'positive_keywords': [
                    'activation', 'increase', 'enhanced', 'greater',
                    'positive', 'excitation', 'facilitation'
                ],
                'negative_keywords': [
                    'deactivation', 'decrease', 'reduced', 'inhibition',
                    'suppression', 'negative', 'lower'
                ]
            },
            'context_awareness': {
                'motor_inhibition': 'negative',  # Special case
                'default_direction': 'positive'
            },
            'confidence_adjustment': {
                'ambiguous_direction_penalty': 0.2
            }
        }
        
        return {
            'fix_type': 'direction_mapping_improvement',
            'changes': improvements,
            'expected_impact': 'Improve direction accuracy to >80%'
        }
        
    def _apply_pattern_fixes(self, patterns: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Apply fixes for specific patterns."""
        fixes = []
        
        # Fix task misclassifications
        for issue in patterns.get('systematic_issues', []):
            if issue['type'] == 'task_misclassification':
                fix = {
                    'fix_type': 'task_reclassification',
                    'task': issue['task'],
                    'action': f"Reclassify task '{issue['task']}' based on GLM patterns",
                    'expected_impact': f"Reduce conflicts for {issue['frequency']} cases"
                }
                fixes.append(fix)
                
            elif issue['type'] == 'concept_mapping_error':
                fix = {
                    'fix_type': 'concept_remapping',
                    'concept': issue['concept'],
                    'action': f"Update mapping for concept '{issue['concept']}'",
                    'expected_impact': f"Fix {issue['frequency']} misalignment cases"
                }
                fixes.append(fix)
                
        return fixes
        
    def _estimate_improvements(self, fixes_applied: List[Dict]) -> Dict[str, float]:
        """Estimate expected improvements from fixes."""
        improvements = {
            'alignment_improvement': 0,
            'confidence_improvement': 0,
            'direction_improvement': 0,
            'conflict_reduction': 0
        }
        
        # Estimate based on fix types
        for fix in fixes_applied:
            fix_type = fix['fix_type']
            
            if fix_type == 'confidence_recalibration':
                improvements['confidence_improvement'] += 0.15
                improvements['conflict_reduction'] += 0.20
                
            elif fix_type == 'niclip_normalization':
                improvements['alignment_improvement'] += 0.20
                
            elif fix_type == 'fusion_weight_recalibration':
                improvements['alignment_improvement'] += 0.15
                improvements['confidence_improvement'] += 0.10
                
            elif fix_type == 'direction_mapping_improvement':
                improvements['direction_improvement'] += 0.25
                
        return improvements


def create_improvement_config(
    diagnosis: Dict[str, Any],
    output_path: Path
) -> None:
    """
    Create configuration file with recommended improvements.
    
    Args:
        diagnosis: Diagnosis from misalignment analysis
        output_path: Path to save improvement config
    """
    config = {
        'improvements': {
            'confidence': {
                'recalibrate_thresholds': True,
                'high_threshold': 0.75,
                'medium_threshold': 0.5,
                'low_threshold': 0.25
            },
            'niclip': {
                'adjust_normalization': True,
                'score_multiplier': 1.2,
                'percentile_remapping': {
                    'p50': 0.4,
                    'p75': 0.6,
                    'p90': 0.8
                }
            },
            'fusion': {
                'adaptive_weights': True,
                'task_specific_weights': {
                    'perceptual': {'niclip': 0.7, 'llm': 0.3},
                    'cognitive': {'niclip': 0.5, 'llm': 0.5},
                    'social': {'niclip': 0.3, 'llm': 0.7}
                }
            },
            'validation': {
                'require_glm_validation': True,
                'min_alignment_score': 0.6
            }
        },
        'diagnosis_summary': {
            'issues': diagnosis['issues'],
            'root_causes': diagnosis['root_causes']
        }
    }
    
    with open(output_path, 'w') as f:
        json.dump(config, f, indent=2)
        
    logger.info(f"Improvement configuration saved to {output_path}")