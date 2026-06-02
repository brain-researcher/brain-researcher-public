"""
Multi-Language Templates for Natural Language Generation

This module provides structured templates for generating natural language responses
in multiple languages with different explanation levels. Supports:
- Multiple languages (English, Spanish, French, German, Chinese)
- Technical vs. layman explanation modes
- Structured response templates
- Context-aware template selection
- Citation and reference formatting
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger(__name__)


class Language(Enum):
    """Supported languages"""

    ENGLISH = "en"
    SPANISH = "es"
    FRENCH = "fr"
    GERMAN = "de"
    CHINESE = "zh"


class ExplanationLevel(Enum):
    """Explanation complexity levels"""

    TECHNICAL = "technical"
    LAYMAN = "layman"
    STRUCTURED = "structured"
    SUMMARY = "summary"


class TemplateCategory(Enum):
    """Template categories for different types of responses"""

    ANALYSIS_COMPLETE = "analysis_complete"
    ANALYSIS_FAILED = "analysis_failed"
    PREPROCESSING_COMPLETE = "preprocessing_complete"
    STATISTICAL_RESULTS = "statistical_results"
    VISUALIZATION_READY = "visualization_ready"
    ERROR_OCCURRED = "error_occurred"
    PROGRESS_UPDATE = "progress_update"
    RECOMMENDATION = "recommendation"
    CITATION = "citation"
    METHODOLOGY = "methodology"
    BEHAVIOR_POLICY = "behavior_policy"


@dataclass
class TemplateContent:
    """Content for a specific template variant"""

    text: str
    fields: List[str]  # Required fields for template substitution
    example_values: Dict[str, Any] = None  # Example values for documentation


@dataclass
class Template:
    """Multi-language, multi-level template"""

    category: TemplateCategory
    content: Dict[Language, Dict[ExplanationLevel, TemplateContent]]
    metadata: Dict[str, Any] = None

    def get_content(
        self, language: Language, level: ExplanationLevel
    ) -> Optional[TemplateContent]:
        """Get template content for specific language and level"""
        lang_content = self.content.get(language)
        if not lang_content:
            # Fallback to English
            lang_content = self.content.get(Language.ENGLISH)

        if lang_content:
            return lang_content.get(level)
        return None


class LanguageTemplates:
    """Repository of language templates for NLG"""

    def __init__(self):
        self.templates: Dict[TemplateCategory, Template] = {}
        self._initialize_templates()

    def _initialize_templates(self):
        """Initialize all templates"""
        self._create_analysis_templates()
        self._create_error_templates()
        self._create_progress_templates()
        self._create_statistical_templates()
        self._create_methodology_templates()
        self._create_behavior_policy_templates()
        self._create_citation_templates()

    def _create_analysis_templates(self):
        """Create analysis completion templates"""

        # Analysis Complete Template
        analysis_complete = Template(
            category=TemplateCategory.ANALYSIS_COMPLETE,
            content={
                Language.ENGLISH: {
                    ExplanationLevel.TECHNICAL: TemplateContent(
                        text="Analysis completed using {method} with {n_subjects} subjects. "
                        "Significant clusters found at p < {threshold} ({correction} correction). "
                        "Peak activation: {peak_coords} (t={t_value}, p={p_value}). "
                        "Total cluster volume: {cluster_volume} voxels.",
                        fields=[
                            "method",
                            "n_subjects",
                            "threshold",
                            "correction",
                            "peak_coords",
                            "t_value",
                            "p_value",
                            "cluster_volume",
                        ],
                    ),
                    ExplanationLevel.LAYMAN: TemplateContent(
                        text="We analyzed brain activity from {n_subjects} people and found {num_regions} "
                        "brain regions that show significant activity. The strongest signal was in the "
                        "{region_name}, which is associated with {function}. This means {interpretation}.",
                        fields=[
                            "n_subjects",
                            "num_regions",
                            "region_name",
                            "function",
                            "interpretation",
                        ],
                    ),
                    ExplanationLevel.STRUCTURED: TemplateContent(
                        text="## Analysis Summary\n"
                        "**Method**: {method}\n"
                        "**Subjects**: {n_subjects}\n"
                        "**Key Finding**: {main_finding}\n"
                        "**Significance**: {significance}\n"
                        "**Clinical Relevance**: {clinical_relevance}",
                        fields=[
                            "method",
                            "n_subjects",
                            "main_finding",
                            "significance",
                            "clinical_relevance",
                        ],
                    ),
                },
                Language.SPANISH: {
                    ExplanationLevel.TECHNICAL: TemplateContent(
                        text="Análisis completado usando {method} con {n_subjects} sujetos. "
                        "Clusters significativos encontrados a p < {threshold} (corrección {correction}). "
                        "Activación máxima: {peak_coords} (t={t_value}, p={p_value}). "
                        "Volumen total del cluster: {cluster_volume} vóxeles.",
                        fields=[
                            "method",
                            "n_subjects",
                            "threshold",
                            "correction",
                            "peak_coords",
                            "t_value",
                            "p_value",
                            "cluster_volume",
                        ],
                    ),
                    ExplanationLevel.LAYMAN: TemplateContent(
                        text="Analizamos la actividad cerebral de {n_subjects} personas y encontramos {num_regions} "
                        "regiones cerebrales que muestran actividad significativa. La señal más fuerte estaba en "
                        "{region_name}, que está asociada con {function}. Esto significa {interpretation}.",
                        fields=[
                            "n_subjects",
                            "num_regions",
                            "region_name",
                            "function",
                            "interpretation",
                        ],
                    ),
                },
                Language.FRENCH: {
                    ExplanationLevel.TECHNICAL: TemplateContent(
                        text="Analyse complétée utilisant {method} avec {n_subjects} sujets. "
                        "Clusters significatifs trouvés à p < {threshold} (correction {correction}). "
                        "Activation maximale: {peak_coords} (t={t_value}, p={p_value}). "
                        "Volume total du cluster: {cluster_volume} voxels.",
                        fields=[
                            "method",
                            "n_subjects",
                            "threshold",
                            "correction",
                            "peak_coords",
                            "t_value",
                            "p_value",
                            "cluster_volume",
                        ],
                    ),
                    ExplanationLevel.LAYMAN: TemplateContent(
                        text="Nous avons analysé l'activité cérébrale de {n_subjects} personnes et trouvé {num_regions} "
                        "régions du cerveau qui montrent une activité significative. Le signal le plus fort était dans "
                        "{region_name}, qui est associé à {function}. Cela signifie {interpretation}.",
                        fields=[
                            "n_subjects",
                            "num_regions",
                            "region_name",
                            "function",
                            "interpretation",
                        ],
                    ),
                },
                Language.GERMAN: {
                    ExplanationLevel.TECHNICAL: TemplateContent(
                        text="Analyse abgeschlossen mit {method} und {n_subjects} Probanden. "
                        "Signifikante Cluster gefunden bei p < {threshold} ({correction} Korrektur). "
                        "Maximale Aktivierung: {peak_coords} (t={t_value}, p={p_value}). "
                        "Gesamtes Cluster-Volumen: {cluster_volume} Voxel.",
                        fields=[
                            "method",
                            "n_subjects",
                            "threshold",
                            "correction",
                            "peak_coords",
                            "t_value",
                            "p_value",
                            "cluster_volume",
                        ],
                    ),
                    ExplanationLevel.LAYMAN: TemplateContent(
                        text="Wir haben die Gehirnaktivität von {n_subjects} Personen analysiert und {num_regions} "
                        "Gehirnregionen gefunden, die signifikante Aktivität zeigen. Das stärkste Signal war in "
                        "{region_name}, welches mit {function} assoziiert ist. Das bedeutet {interpretation}.",
                        fields=[
                            "n_subjects",
                            "num_regions",
                            "region_name",
                            "function",
                            "interpretation",
                        ],
                    ),
                },
                Language.CHINESE: {
                    ExplanationLevel.TECHNICAL: TemplateContent(
                        text="使用{method}方法完成分析，包含{n_subjects}名受试者。"
                        "在p < {threshold}水平下发现显著激活团块（{correction}校正）。"
                        "峰值激活位置：{peak_coords}（t={t_value}, p={p_value}）。"
                        "激活团块总体积：{cluster_volume}个体素。",
                        fields=[
                            "method",
                            "n_subjects",
                            "threshold",
                            "correction",
                            "peak_coords",
                            "t_value",
                            "p_value",
                            "cluster_volume",
                        ],
                    ),
                    ExplanationLevel.LAYMAN: TemplateContent(
                        text="我们分析了{n_subjects}个人的大脑活动，发现了{num_regions}个显示显著活动的脑区。"
                        "最强的信号出现在{region_name}，这个区域与{function}相关。这表明{interpretation}。",
                        fields=[
                            "n_subjects",
                            "num_regions",
                            "region_name",
                            "function",
                            "interpretation",
                        ],
                    ),
                },
            },
        )
        self.templates[TemplateCategory.ANALYSIS_COMPLETE] = analysis_complete

    def _create_error_templates(self):
        """Create error and failure templates"""

        error_occurred = Template(
            category=TemplateCategory.ERROR_OCCURRED,
            content={
                Language.ENGLISH: {
                    ExplanationLevel.TECHNICAL: TemplateContent(
                        text="Processing failed: {error_type}. Error details: {error_message}. "
                        "Stack trace: {stack_trace}. Suggested fix: {suggested_fix}.",
                        fields=[
                            "error_type",
                            "error_message",
                            "stack_trace",
                            "suggested_fix",
                        ],
                    ),
                    ExplanationLevel.LAYMAN: TemplateContent(
                        text="We encountered an issue while processing your data: {error_summary}. "
                        "This usually happens when {common_cause}. "
                        "To fix this, please try: {user_action}.",
                        fields=["error_summary", "common_cause", "user_action"],
                    ),
                    ExplanationLevel.STRUCTURED: TemplateContent(
                        text="## Error Report\n"
                        "**Error Type**: {error_type}\n"
                        "**Description**: {error_message}\n"
                        "**Possible Causes**: {possible_causes}\n"
                        "**Recommended Actions**: {recommended_actions}\n"
                        "**Need Help?**: Contact support with error ID {error_id}",
                        fields=[
                            "error_type",
                            "error_message",
                            "possible_causes",
                            "recommended_actions",
                            "error_id",
                        ],
                    ),
                },
                Language.SPANISH: {
                    ExplanationLevel.LAYMAN: TemplateContent(
                        text="Encontramos un problema al procesar sus datos: {error_summary}. "
                        "Esto usualmente sucede cuando {common_cause}. "
                        "Para solucionarlo, por favor intente: {user_action}.",
                        fields=["error_summary", "common_cause", "user_action"],
                    )
                },
                Language.FRENCH: {
                    ExplanationLevel.LAYMAN: TemplateContent(
                        text="Nous avons rencontré un problème lors du traitement de vos données: {error_summary}. "
                        "Cela arrive généralement quand {common_cause}. "
                        "Pour résoudre cela, veuillez essayer: {user_action}.",
                        fields=["error_summary", "common_cause", "user_action"],
                    )
                },
            },
        )
        self.templates[TemplateCategory.ERROR_OCCURRED] = error_occurred

    def _create_progress_templates(self):
        """Create progress update templates"""

        progress_update = Template(
            category=TemplateCategory.PROGRESS_UPDATE,
            content={
                Language.ENGLISH: {
                    ExplanationLevel.TECHNICAL: TemplateContent(
                        text="Processing step {current_step}/{total_steps}: {step_name}. "
                        "Elapsed time: {elapsed_time}. Estimated remaining: {eta}. "
                        "Resource usage: CPU {cpu_usage}%, Memory {memory_usage}%.",
                        fields=[
                            "current_step",
                            "total_steps",
                            "step_name",
                            "elapsed_time",
                            "eta",
                            "cpu_usage",
                            "memory_usage",
                        ],
                    ),
                    ExplanationLevel.LAYMAN: TemplateContent(
                        text="Currently working on: {step_description} ({progress_percentage}% complete). "
                        "This should take about {estimated_duration} more. "
                        "Everything is running smoothly!",
                        fields=[
                            "step_description",
                            "progress_percentage",
                            "estimated_duration",
                        ],
                    ),
                    ExplanationLevel.SUMMARY: TemplateContent(
                        text="{progress_percentage}% complete - {current_task}",
                        fields=["progress_percentage", "current_task"],
                    ),
                },
                Language.SPANISH: {
                    ExplanationLevel.LAYMAN: TemplateContent(
                        text="Trabajando actualmente en: {step_description} ({progress_percentage}% completo). "
                        "Esto debería tomar aproximadamente {estimated_duration} más. "
                        "¡Todo está funcionando sin problemas!",
                        fields=[
                            "step_description",
                            "progress_percentage",
                            "estimated_duration",
                        ],
                    )
                },
            },
        )
        self.templates[TemplateCategory.PROGRESS_UPDATE] = progress_update

    def _create_statistical_templates(self):
        """Create statistical results templates"""

        statistical_results = Template(
            category=TemplateCategory.STATISTICAL_RESULTS,
            content={
                Language.ENGLISH: {
                    ExplanationLevel.TECHNICAL: TemplateContent(
                        text="Statistical analysis revealed {effect_type} with effect size {effect_size} "
                        "(Cohen's d = {cohens_d}). Confidence interval: [{ci_lower}, {ci_upper}]. "
                        "Power analysis: {power} with alpha = {alpha}. "
                        "Multiple comparisons correction: {correction_method}.",
                        fields=[
                            "effect_type",
                            "effect_size",
                            "cohens_d",
                            "ci_lower",
                            "ci_upper",
                            "power",
                            "alpha",
                            "correction_method",
                        ],
                    ),
                    ExplanationLevel.LAYMAN: TemplateContent(
                        text="Our statistical analysis shows {plain_language_finding}. "
                        "The effect is {effect_magnitude} (we can be {confidence_level}% confident). "
                        "In practical terms, this means {practical_interpretation}.",
                        fields=[
                            "plain_language_finding",
                            "effect_magnitude",
                            "confidence_level",
                            "practical_interpretation",
                        ],
                    ),
                    ExplanationLevel.STRUCTURED: TemplateContent(
                        text="## Statistical Results\n"
                        "**Main Finding**: {main_finding}\n"
                        "**Effect Size**: {effect_size} ({magnitude_interpretation})\n"
                        "**Confidence**: {confidence_interval}\n"
                        "**Statistical Power**: {power_analysis}\n"
                        "**Interpretation**: {interpretation}",
                        fields=[
                            "main_finding",
                            "effect_size",
                            "magnitude_interpretation",
                            "confidence_interval",
                            "power_analysis",
                            "interpretation",
                        ],
                    ),
                }
            },
        )
        self.templates[TemplateCategory.STATISTICAL_RESULTS] = statistical_results

    def _create_methodology_templates(self):
        """Create methodology explanation templates"""

        methodology = Template(
            category=TemplateCategory.METHODOLOGY,
            content={
                Language.ENGLISH: {
                    ExplanationLevel.TECHNICAL: TemplateContent(
                        text="Methodology: {analysis_type} using {software_packages}. "
                        "Preprocessing: {preprocessing_steps}. "
                        "Statistical model: {statistical_model} with {n_regressors} regressors. "
                        "Thresholding: {threshold_method} at {threshold_value}. "
                        "Multiple comparisons: {correction_method}.",
                        fields=[
                            "analysis_type",
                            "software_packages",
                            "preprocessing_steps",
                            "statistical_model",
                            "n_regressors",
                            "threshold_method",
                            "threshold_value",
                            "correction_method",
                        ],
                    ),
                    ExplanationLevel.LAYMAN: TemplateContent(
                        text="Here's how we analyzed your data: {simple_methodology}. "
                        "We used established methods that are widely accepted in neuroscience. "
                        "The key steps were: {key_steps}. "
                        "This approach helps ensure our results are reliable and meaningful.",
                        fields=["simple_methodology", "key_steps"],
                    ),
                    ExplanationLevel.STRUCTURED: TemplateContent(
                        text="## Methodology Overview\n"
                        "**Analysis Type**: {analysis_type}\n"
                        "**Data Processing**: {data_processing}\n"
                        "**Statistical Approach**: {statistical_approach}\n"
                        "**Quality Control**: {quality_control}\n"
                        "**Validation**: {validation_methods}",
                        fields=[
                            "analysis_type",
                            "data_processing",
                            "statistical_approach",
                            "quality_control",
                            "validation_methods",
                        ],
                    ),
                }
            },
        )
        self.templates[TemplateCategory.METHODOLOGY] = methodology

    def _create_behavior_policy_templates(self):
        """Templates to surface behavior outlier policy options."""
        behavior_policy = Template(
            category=TemplateCategory.BEHAVIOR_POLICY,
            content={
                Language.ENGLISH: {
                    ExplanationLevel.STRUCTURED: TemplateContent(
                        text=(
                            "Behavioral outlier policy options:\\n"
                            "{policy_table}\\n"
                            "Pick a policy_id and pass it to behavior.qc_scan (policy_path) "
                            "or behavior.export_bids (policy_id). Default: behavior_default_v1."
                        ),
                        fields=["policy_table"],
                    )
                }
            },
            metadata={"intent": "behavior_policy_selection"},
        )
        self.templates[TemplateCategory.BEHAVIOR_POLICY] = behavior_policy

    def _create_citation_templates(self):
        """Create citation and reference templates"""

        citation = Template(
            category=TemplateCategory.CITATION,
            content={
                Language.ENGLISH: {
                    ExplanationLevel.TECHNICAL: TemplateContent(
                        text="Analysis based on: {primary_citation}. "
                        "Additional references: {additional_references}. "
                        "Software citations: {software_citations}. "
                        "Methodology follows: {methodology_reference}.",
                        fields=[
                            "primary_citation",
                            "additional_references",
                            "software_citations",
                            "methodology_reference",
                        ],
                    ),
                    ExplanationLevel.LAYMAN: TemplateContent(
                        text="This analysis is based on established scientific methods. "
                        "Key research that supports our approach: {key_reference}. "
                        "For more details, see: {additional_reading}.",
                        fields=["key_reference", "additional_reading"],
                    ),
                    ExplanationLevel.STRUCTURED: TemplateContent(
                        text="## References\n"
                        "**Primary Method**: {primary_reference}\n"
                        "**Software Used**: {software_references}\n"
                        "**Related Work**: {related_references}\n"
                        "**For Further Reading**: {further_reading}",
                        fields=[
                            "primary_reference",
                            "software_references",
                            "related_references",
                            "further_reading",
                        ],
                    ),
                }
            },
        )
        self.templates[TemplateCategory.CITATION] = citation

    def get_template(
        self,
        category: TemplateCategory,
        language: Language = Language.ENGLISH,
        level: ExplanationLevel = ExplanationLevel.TECHNICAL,
    ) -> Optional[TemplateContent]:
        """Get template content for specific category, language, and level"""
        template = self.templates.get(category)
        if template:
            return template.get_content(language, level)
        return None

    def format_template(
        self,
        category: TemplateCategory,
        values: Dict[str, Any],
        language: Language = Language.ENGLISH,
        level: ExplanationLevel = ExplanationLevel.TECHNICAL,
    ) -> Optional[str]:
        """Format template with provided values"""
        template_content = self.get_template(category, language, level)
        if not template_content:
            logger.warning(
                f"Template not found: {category.value}, {language.value}, {level.value}"
            )
            return None

        try:
            # Check for missing required fields
            missing_fields = [
                field for field in template_content.fields if field not in values
            ]
            if missing_fields:
                logger.warning(
                    f"Missing required fields for template: {missing_fields}"
                )
                # Fill missing fields with placeholders
                for field in missing_fields:
                    values[field] = f"[{field}]"

            # Format the template
            formatted_text = template_content.text.format(**values)
            return formatted_text

        except KeyError as e:
            logger.error(f"Template formatting error: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected template formatting error: {e}")
            return None

    def get_available_templates(self) -> Dict[str, List[str]]:
        """Get list of available templates by category"""
        result = {}
        for category in TemplateCategory:
            template = self.templates.get(category)
            if template:
                languages = list(template.content.keys())
                result[category.value] = [lang.value for lang in languages]
        return result

    def get_template_fields(
        self,
        category: TemplateCategory,
        language: Language = Language.ENGLISH,
        level: ExplanationLevel = ExplanationLevel.TECHNICAL,
    ) -> List[str]:
        """Get required fields for a template"""
        template_content = self.get_template(category, language, level)
        if template_content:
            return template_content.fields
        return []

    def validate_template_values(
        self,
        category: TemplateCategory,
        values: Dict[str, Any],
        language: Language = Language.ENGLISH,
        level: ExplanationLevel = ExplanationLevel.TECHNICAL,
    ) -> List[str]:
        """Validate that all required fields are provided for a template"""
        required_fields = self.get_template_fields(category, language, level)
        missing_fields = [field for field in required_fields if field not in values]
        return missing_fields


# Specialized template generators
class NeuroimagingTemplates:
    """Specialized templates for neuroimaging results"""

    @staticmethod
    def create_activation_summary(
        coordinates: List[float],
        region: str,
        t_value: float,
        language: Language = Language.ENGLISH,
    ) -> str:
        """Create activation summary text"""
        templates = {
            Language.ENGLISH: f"Peak activation in {region} at coordinates {coordinates} (t={t_value:.2f})",
            Language.SPANISH: f"Activación máxima en {region} en coordenadas {coordinates} (t={t_value:.2f})",
            Language.FRENCH: f"Activation maximale dans {region} aux coordonnées {coordinates} (t={t_value:.2f})",
            Language.GERMAN: f"Maximale Aktivierung in {region} bei Koordinaten {coordinates} (t={t_value:.2f})",
            Language.CHINESE: f"{region}区域峰值激活，坐标{coordinates}（t={t_value:.2f}）",
        }
        return templates.get(language, templates[Language.ENGLISH])


class StatisticalTemplates:
    """Specialized templates for statistical results"""

    @staticmethod
    def create_significance_statement(
        p_value: float, alpha: float = 0.05, language: Language = Language.ENGLISH
    ) -> str:
        """Create significance statement"""
        is_significant = p_value < alpha

        templates = {
            Language.ENGLISH: {
                True: f"The result is statistically significant (p = {p_value:.4f}, α = {alpha})",
                False: f"The result is not statistically significant (p = {p_value:.4f}, α = {alpha})",
            },
            Language.SPANISH: {
                True: f"El resultado es estadísticamente significativo (p = {p_value:.4f}, α = {alpha})",
                False: f"El resultado no es estadísticamente significativo (p = {p_value:.4f}, α = {alpha})",
            },
        }

        lang_templates = templates.get(language, templates[Language.ENGLISH])
        return lang_templates[is_significant]


if __name__ == "__main__":
    # Test the template system
    templates = LanguageTemplates()

    # Test analysis complete template
    values = {
        "method": "GLM analysis",
        "n_subjects": 25,
        "threshold": 0.001,
        "correction": "FWE",
        "peak_coords": "[42, -58, 46]",
        "t_value": 5.67,
        "p_value": 0.0001,
        "cluster_volume": 1247,
        "num_regions": 3,
        "region_name": "visual cortex",
        "function": "visual processing",
        "interpretation": "the visual system is more active during the task",
    }

    # Test different languages and levels
    for lang in [Language.ENGLISH, Language.SPANISH, Language.FRENCH]:
        for level in [ExplanationLevel.TECHNICAL, ExplanationLevel.LAYMAN]:
            result = templates.format_template(
                TemplateCategory.ANALYSIS_COMPLETE, values, lang, level
            )
            if result:
                print(f"\n{lang.value.upper()} - {level.value.upper()}:")
                print(result)

    # Test template validation
    missing = templates.validate_template_values(
        TemplateCategory.ANALYSIS_COMPLETE,
        {"method": "GLM"},
        Language.ENGLISH,
        ExplanationLevel.TECHNICAL,
    )
    print(f"\nMissing fields: {missing}")

    # Test available templates
    available = templates.get_available_templates()
    print(f"\nAvailable templates: {list(available.keys())}")
