"""
Domain Knowledge Module for Brain Researcher Agent (AGENT-017)

This module implements neuroimaging domain knowledge including ontology loading,
term mappings, abbreviation resolution, and concept relationships for enhanced
query understanding.
"""

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class DomainConcept:
    """Represents a domain concept with relationships."""

    name: str
    category: str
    synonyms: list[str] = field(default_factory=list)
    abbreviations: list[str] = field(default_factory=list)
    definitions: list[str] = field(default_factory=list)
    related_concepts: list[str] = field(default_factory=list)
    parent_concepts: list[str] = field(default_factory=list)
    child_concepts: list[str] = field(default_factory=list)
    coordinates: tuple[float, float, float] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class BrainRegion:
    """Represents a brain region with anatomical information."""

    name: str
    full_name: str
    abbreviations: list[str] = field(default_factory=list)
    hemispheres: list[str] = field(default_factory=list)  # left, right, bilateral
    coordinates: tuple[float, float, float] | None = None
    volume: int | None = None  # in mm³
    brodmann_areas: list[str] = field(default_factory=list)
    networks: list[str] = field(default_factory=list)
    functions: list[str] = field(default_factory=list)
    synonyms: list[str] = field(default_factory=list)


@dataclass
class Task:
    """Represents a cognitive task or paradigm."""

    name: str
    category: str
    description: str
    synonyms: list[str] = field(default_factory=list)
    contrasts: list[str] = field(default_factory=list)
    brain_regions: list[str] = field(default_factory=list)
    networks: list[str] = field(default_factory=list)
    cognitive_domains: list[str] = field(default_factory=list)


@dataclass
class StatisticalMethod:
    """Represents a statistical analysis method."""

    name: str
    full_name: str
    category: str
    description: str
    abbreviations: list[str] = field(default_factory=list)
    use_cases: list[str] = field(default_factory=list)
    requirements: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)


class NeuroImagingOntology:
    """
    Comprehensive neuroimaging ontology with domain knowledge.

    Features:
    - Brain region hierarchies and relationships
    - Cognitive task categorization
    - Statistical method classifications
    - Abbreviation and synonym resolution
    - Coordinate-based spatial knowledge
    """

    def __init__(self):
        """Initialize the neuroimaging ontology."""
        self.concepts: dict[str, DomainConcept] = {}
        self.brain_regions: dict[str, BrainRegion] = {}
        self.tasks: dict[str, Task] = {}
        self.statistical_methods: dict[str, StatisticalMethod] = {}

        # Lookup indexes for fast access
        self.synonym_index: dict[str, str] = {}
        self.abbreviation_index: dict[str, str] = {}
        self.coordinate_index: dict[str, tuple[float, float, float]] = {}

        # Initialize with built-in knowledge
        self._load_brain_regions()
        self._load_tasks()
        self._load_statistical_methods()
        self._load_general_concepts()
        self._build_indexes()

        logger.info(
            f"Ontology loaded: {len(self.brain_regions)} regions, "
            f"{len(self.tasks)} tasks, {len(self.statistical_methods)} methods"
        )

    def _load_brain_regions(self):
        """Load brain region knowledge."""
        regions_data = [
            {
                "name": "prefrontal_cortex",
                "full_name": "Prefrontal Cortex",
                "abbreviations": ["PFC", "pfc"],
                "hemispheres": ["left", "right", "bilateral"],
                "coordinates": (0, 50, 20),
                "brodmann_areas": ["BA9", "BA10", "BA11", "BA46", "BA47"],
                "networks": ["central_executive", "frontoparietal"],
                "functions": ["executive_control", "working_memory", "decision_making"],
                "synonyms": ["frontal cortex", "frontal lobe"],
            },
            {
                "name": "anterior_cingulate_cortex",
                "full_name": "Anterior Cingulate Cortex",
                "abbreviations": ["ACC", "acc"],
                "hemispheres": ["bilateral"],
                "coordinates": (0, 32, 20),
                "brodmann_areas": ["BA24", "BA32", "BA33"],
                "networks": ["salience", "default_mode"],
                "functions": ["conflict_monitoring", "emotion_regulation", "attention"],
                "synonyms": ["anterior cingulate", "ACC"],
            },
            {
                "name": "posterior_cingulate_cortex",
                "full_name": "Posterior Cingulate Cortex",
                "abbreviations": ["PCC", "pcc"],
                "hemispheres": ["bilateral"],
                "coordinates": (0, -52, 26),
                "brodmann_areas": ["BA23", "BA31"],
                "networks": ["default_mode"],
                "functions": [
                    "self_referential_thinking",
                    "memory",
                    "spatial_navigation",
                ],
                "synonyms": ["posterior cingulate", "PCC"],
            },
            {
                "name": "amygdala",
                "full_name": "Amygdala",
                "abbreviations": ["amy", "amyg"],
                "hemispheres": ["left", "right", "bilateral"],
                "coordinates": (20, -5, -18),
                "networks": ["limbic"],
                "functions": ["fear_processing", "emotion", "memory_consolidation"],
                "synonyms": ["amygdaloid complex"],
            },
            {
                "name": "hippocampus",
                "full_name": "Hippocampus",
                "abbreviations": ["hipp", "hpc"],
                "hemispheres": ["left", "right", "bilateral"],
                "coordinates": (28, -21, -18),
                "networks": ["limbic", "default_mode"],
                "functions": ["memory_formation", "spatial_navigation", "learning"],
                "synonyms": ["hippocampal formation"],
            },
            {
                "name": "insula",
                "full_name": "Insula",
                "abbreviations": ["ins"],
                "hemispheres": ["left", "right", "bilateral"],
                "coordinates": (38, 0, 0),
                "networks": ["salience", "interoceptive"],
                "functions": ["interoception", "emotion", "empathy", "self_awareness"],
                "synonyms": ["insular cortex"],
            },
            {
                "name": "thalamus",
                "full_name": "Thalamus",
                "abbreviations": ["thal"],
                "hemispheres": ["left", "right", "bilateral"],
                "coordinates": (0, -20, 0),
                "networks": ["subcortical"],
                "functions": ["sensory_relay", "attention", "consciousness"],
                "synonyms": ["thalamic nuclei"],
            },
            {
                "name": "caudate",
                "full_name": "Caudate Nucleus",
                "abbreviations": ["caud"],
                "hemispheres": ["left", "right", "bilateral"],
                "coordinates": (13, 15, 9),
                "networks": ["basal_ganglia"],
                "functions": ["motor_control", "learning", "reward"],
                "synonyms": ["caudate nucleus"],
            },
            {
                "name": "putamen",
                "full_name": "Putamen",
                "abbreviations": ["put"],
                "hemispheres": ["left", "right", "bilateral"],
                "coordinates": (25, 5, 0),
                "networks": ["basal_ganglia"],
                "functions": ["motor_control", "learning", "habit_formation"],
                "synonyms": ["putaminal"],
            },
        ]

        for region_data in regions_data:
            region = BrainRegion(
                name=region_data["name"],
                full_name=region_data["full_name"],
                abbreviations=region_data.get("abbreviations", []),
                hemispheres=region_data.get("hemispheres", []),
                coordinates=region_data.get("coordinates"),
                brodmann_areas=region_data.get("brodmann_areas", []),
                networks=region_data.get("networks", []),
                functions=region_data.get("functions", []),
                synonyms=region_data.get("synonyms", []),
            )
            self.brain_regions[region.name] = region

    def _load_tasks(self):
        """Load cognitive task knowledge."""
        tasks_data = [
            {
                "name": "n_back",
                "category": "working_memory",
                "description": "Working memory task requiring monitoring and updating of information",
                "synonyms": ["n-back", "nback", "n back task"],
                "contrasts": ["2back_vs_0back", "3back_vs_1back", "load_effect"],
                "brain_regions": ["prefrontal_cortex", "parietal_cortex"],
                "networks": ["frontoparietal", "central_executive"],
                "cognitive_domains": [
                    "working_memory",
                    "attention",
                    "executive_control",
                ],
            },
            {
                "name": "stroop",
                "category": "cognitive_control",
                "description": "Conflict monitoring task measuring response inhibition",
                "synonyms": ["stroop task", "color-word stroop"],
                "contrasts": ["incongruent_vs_congruent", "conflict_effect"],
                "brain_regions": ["anterior_cingulate_cortex", "prefrontal_cortex"],
                "networks": ["salience", "central_executive"],
                "cognitive_domains": ["cognitive_control", "attention", "inhibition"],
            },
            {
                "name": "oddball",
                "category": "attention",
                "description": "Attention task using infrequent target stimuli",
                "synonyms": ["oddball paradigm", "p300 task"],
                "contrasts": ["target_vs_standard", "novelty_effect"],
                "brain_regions": ["prefrontal_cortex", "parietal_cortex", "cingulate"],
                "networks": ["salience", "attention"],
                "cognitive_domains": ["attention", "target_detection"],
            },
            {
                "name": "go_no_go",
                "category": "inhibition",
                "description": "Response inhibition task requiring withholding responses",
                "synonyms": ["go/no-go", "go nogo", "response inhibition"],
                "contrasts": ["no_go_vs_go", "inhibition_effect"],
                "brain_regions": ["prefrontal_cortex", "anterior_cingulate_cortex"],
                "networks": ["central_executive"],
                "cognitive_domains": [
                    "inhibition",
                    "motor_control",
                    "executive_control",
                ],
            },
            {
                "name": "flanker",
                "category": "cognitive_control",
                "description": "Attention task measuring interference resolution",
                "synonyms": ["flanker task", "eriksen flanker"],
                "contrasts": ["incongruent_vs_congruent", "flanker_effect"],
                "brain_regions": ["anterior_cingulate_cortex", "prefrontal_cortex"],
                "networks": ["salience", "central_executive"],
                "cognitive_domains": ["attention", "cognitive_control", "interference"],
            },
            {
                "name": "emotional_faces",
                "category": "emotion",
                "description": "Emotion processing task using facial expressions",
                "synonyms": ["face processing", "emotion faces", "facial emotion"],
                "contrasts": [
                    "fearful_vs_neutral",
                    "happy_vs_sad",
                    "emotion_vs_neutral",
                ],
                "brain_regions": ["amygdala", "prefrontal_cortex", "fusiform_gyrus"],
                "networks": ["limbic", "emotion"],
                "cognitive_domains": [
                    "emotion_processing",
                    "face_recognition",
                    "social_cognition",
                ],
            },
        ]

        for task_data in tasks_data:
            task = Task(
                name=task_data["name"],
                category=task_data["category"],
                description=task_data["description"],
                synonyms=task_data.get("synonyms", []),
                contrasts=task_data.get("contrasts", []),
                brain_regions=task_data.get("brain_regions", []),
                networks=task_data.get("networks", []),
                cognitive_domains=task_data.get("cognitive_domains", []),
            )
            self.tasks[task.name] = task

    def _load_statistical_methods(self):
        """Load statistical method knowledge."""
        methods_data = [
            {
                "name": "glm",
                "full_name": "General Linear Model",
                "abbreviations": ["GLM", "glm"],
                "category": "univariate",
                "description": "Statistical framework for modeling relationships between variables",
                "use_cases": [
                    "activation_analysis",
                    "group_comparison",
                    "regression_analysis",
                ],
                "requirements": ["design_matrix", "contrast_vectors"],
                "outputs": ["statistical_maps", "parameter_estimates", "residuals"],
            },
            {
                "name": "svm",
                "full_name": "Support Vector Machine",
                "abbreviations": ["SVM", "svm"],
                "category": "machine_learning",
                "description": "Classification algorithm for pattern recognition",
                "use_cases": ["classification", "decoding", "prediction"],
                "requirements": [
                    "training_data",
                    "feature_selection",
                    "cross_validation",
                ],
                "outputs": ["accuracy", "decision_values", "feature_weights"],
            },
            {
                "name": "pca",
                "full_name": "Principal Component Analysis",
                "abbreviations": ["PCA", "pca"],
                "category": "dimensionality_reduction",
                "description": "Dimensionality reduction technique using eigendecomposition",
                "use_cases": [
                    "dimensionality_reduction",
                    "data_exploration",
                    "noise_reduction",
                ],
                "requirements": ["standardized_data"],
                "outputs": ["principal_components", "explained_variance", "loadings"],
            },
            {
                "name": "ica",
                "full_name": "Independent Component Analysis",
                "abbreviations": ["ICA", "ica"],
                "category": "signal_separation",
                "description": "Signal separation technique for identifying independent sources",
                "use_cases": [
                    "artifact_removal",
                    "network_identification",
                    "source_separation",
                ],
                "requirements": ["mixed_signals"],
                "outputs": ["independent_components", "mixing_matrix", "time_courses"],
            },
            {
                "name": "connectivity",
                "full_name": "Functional Connectivity",
                "abbreviations": ["FC", "fc", "conn"],
                "category": "connectivity",
                "description": "Analysis of temporal correlations between brain regions",
                "use_cases": [
                    "network_analysis",
                    "brain_connectivity",
                    "resting_state",
                ],
                "requirements": ["time_series_data", "roi_definition"],
                "outputs": [
                    "correlation_matrix",
                    "connectivity_maps",
                    "network_metrics",
                ],
            },
        ]

        for method_data in methods_data:
            method = StatisticalMethod(
                name=method_data["name"],
                full_name=method_data["full_name"],
                abbreviations=method_data.get("abbreviations", []),
                category=method_data["category"],
                description=method_data["description"],
                use_cases=method_data.get("use_cases", []),
                requirements=method_data.get("requirements", []),
                outputs=method_data.get("outputs", []),
            )
            self.statistical_methods[method.name] = method

    def _load_general_concepts(self):
        """Load general neuroimaging concepts."""
        general_concepts = [
            {
                "name": "fmri",
                "category": "modality",
                "synonyms": [
                    "functional MRI",
                    "functional magnetic resonance imaging",
                    "BOLD fMRI",
                ],
                "abbreviations": ["fMRI", "FMRI"],
                "definitions": [
                    "Neuroimaging technique measuring brain activity via blood flow changes"
                ],
                "related_concepts": ["bold", "hemodynamic_response", "t2_star"],
            },
            {
                "name": "bold",
                "category": "signal",
                "synonyms": ["blood oxygen level dependent", "BOLD signal"],
                "abbreviations": ["BOLD"],
                "definitions": [
                    "Physiological signal measured in fMRI reflecting neural activity"
                ],
                "related_concepts": [
                    "fmri",
                    "hemodynamic_response",
                    "neurovascular_coupling",
                ],
            },
            {
                "name": "preprocessing",
                "category": "analysis_step",
                "synonyms": ["pre-processing", "data preprocessing"],
                "abbreviations": ["prep"],
                "definitions": [
                    "Initial data processing steps to prepare for analysis"
                ],
                "related_concepts": ["motion_correction", "normalization", "smoothing"],
            },
            {
                "name": "activation",
                "category": "brain_response",
                "synonyms": [
                    "brain activation",
                    "neural activation",
                    "cortical activation",
                ],
                "definitions": [
                    "Increased neural activity in response to stimuli or tasks"
                ],
                "related_concepts": ["bold", "contrast", "statistical_map"],
            },
            {
                "name": "network",
                "category": "brain_organization",
                "synonyms": ["brain network", "neural network", "functional network"],
                "definitions": ["Set of brain regions with similar temporal dynamics"],
                "related_concepts": [
                    "connectivity",
                    "resting_state",
                    "default_mode_network",
                ],
            },
        ]

        for concept_data in general_concepts:
            concept = DomainConcept(
                name=concept_data["name"],
                category=concept_data["category"],
                synonyms=concept_data.get("synonyms", []),
                abbreviations=concept_data.get("abbreviations", []),
                definitions=concept_data.get("definitions", []),
                related_concepts=concept_data.get("related_concepts", []),
            )
            self.concepts[concept.name] = concept

    def _build_indexes(self):
        """Build lookup indexes for fast access."""
        # Build synonym index
        for region_name, region in self.brain_regions.items():
            self.synonym_index[region.full_name.lower()] = region_name
            for synonym in region.synonyms:
                self.synonym_index[synonym.lower()] = region_name
            for abbrev in region.abbreviations:
                self.abbreviation_index[abbrev.lower()] = region_name
            if region.coordinates:
                self.coordinate_index[region_name] = region.coordinates

        for task_name, task in self.tasks.items():
            for synonym in task.synonyms:
                self.synonym_index[synonym.lower()] = task_name

        for method_name, method in self.statistical_methods.items():
            self.synonym_index[method.full_name.lower()] = method_name
            for abbrev in method.abbreviations:
                self.abbreviation_index[abbrev.lower()] = method_name

        for concept_name, concept in self.concepts.items():
            for synonym in concept.synonyms:
                self.synonym_index[synonym.lower()] = concept_name
            for abbrev in concept.abbreviations:
                self.abbreviation_index[abbrev.lower()] = concept_name

    def resolve_term(self, term: str) -> str | None:
        """
        Resolve a term to its canonical form.

        Args:
            term: Term to resolve

        Returns:
            Canonical form of the term, or None if not found
        """
        term_lower = term.lower()

        # Check direct match
        if term_lower in self.brain_regions:
            return term_lower
        if term_lower in self.tasks:
            return term_lower
        if term_lower in self.statistical_methods:
            return term_lower
        if term_lower in self.concepts:
            return term_lower

        # Check synonym index
        if term_lower in self.synonym_index:
            return self.synonym_index[term_lower]

        # Check abbreviation index
        if term_lower in self.abbreviation_index:
            return self.abbreviation_index[term_lower]

        return None

    def get_synonyms(self, term: str) -> list[str]:
        """
        Get synonyms for a term.

        Args:
            term: Term to find synonyms for

        Returns:
            List of synonyms
        """
        canonical = self.resolve_term(term)
        if not canonical:
            return []

        synonyms = []

        # Check brain regions
        if canonical in self.brain_regions:
            region = self.brain_regions[canonical]
            synonyms.extend(region.synonyms)
            synonyms.extend(region.abbreviations)
            synonyms.append(region.full_name)

        # Check tasks
        elif canonical in self.tasks:
            task = self.tasks[canonical]
            synonyms.extend(task.synonyms)

        # Check statistical methods
        elif canonical in self.statistical_methods:
            method = self.statistical_methods[canonical]
            synonyms.extend(method.abbreviations)
            synonyms.append(method.full_name)

        # Check general concepts
        elif canonical in self.concepts:
            concept = self.concepts[canonical]
            synonyms.extend(concept.synonyms)
            synonyms.extend(concept.abbreviations)

        # Remove duplicates and original term
        synonyms = list(set(synonyms))
        if term in synonyms:
            synonyms.remove(term)

        return synonyms

    def get_related_concepts(self, query: str) -> list[str]:
        """
        Get concepts related to the query.

        Args:
            query: Query to analyze

        Returns:
            List of related concepts
        """
        related = []
        query_lower = query.lower()

        # Find concepts mentioned in query
        mentioned_concepts = []
        for concept_name in self.concepts:
            if concept_name in query_lower:
                mentioned_concepts.append(concept_name)

        # Get related concepts
        for concept_name in mentioned_concepts:
            concept = self.concepts[concept_name]
            related.extend(concept.related_concepts)

        # Add task-related concepts
        for task_name, task in self.tasks.items():
            if task_name in query_lower or any(
                syn.lower() in query_lower for syn in task.synonyms
            ):
                related.extend(task.brain_regions)
                related.extend(task.networks)
                related.extend(task.cognitive_domains)

        # Remove duplicates
        related = list(set(related))

        return related[:10]  # Return top 10

    def get_domain_terms(self, query: str) -> list[str]:
        """
        Extract domain-specific terms from query.

        Args:
            query: Query to analyze

        Returns:
            List of domain terms found
        """
        domain_terms = []
        query_lower = query.lower()

        # Check for brain regions
        for region_name, region in self.brain_regions.items():
            if region_name in query_lower:
                domain_terms.append(region_name)
            elif region.full_name.lower() in query_lower:
                domain_terms.append(region_name)
            else:
                for synonym in region.synonyms:
                    if synonym.lower() in query_lower:
                        domain_terms.append(region_name)
                        break

        # Check for tasks
        for task_name, task in self.tasks.items():
            if task_name in query_lower:
                domain_terms.append(task_name)
            else:
                for synonym in task.synonyms:
                    if synonym.lower() in query_lower:
                        domain_terms.append(task_name)
                        break

        # Check for statistical methods
        for method_name, method in self.statistical_methods.items():
            if method_name in query_lower:
                domain_terms.append(method_name)
            elif method.full_name.lower() in query_lower:
                domain_terms.append(method_name)
            else:
                for abbrev in method.abbreviations:
                    if abbrev.lower() in query_lower:
                        domain_terms.append(method_name)
                        break

        # Check for general concepts
        for concept_name, concept in self.concepts.items():
            if concept_name in query_lower:
                domain_terms.append(concept_name)
            else:
                for synonym in concept.synonyms:
                    if synonym.lower() in query_lower:
                        domain_terms.append(concept_name)
                        break

        return list(set(domain_terms))

    def get_coordinates(self, region_name: str) -> tuple[float, float, float] | None:
        """
        Get MNI coordinates for a brain region.

        Args:
            region_name: Name of the brain region

        Returns:
            MNI coordinates as (x, y, z) tuple, or None if not found
        """
        canonical = self.resolve_term(region_name)
        if canonical and canonical in self.brain_regions:
            return self.brain_regions[canonical].coordinates
        return None

    def get_brain_networks(self, region_name: str) -> list[str]:
        """
        Get brain networks associated with a region.

        Args:
            region_name: Name of the brain region

        Returns:
            List of network names
        """
        canonical = self.resolve_term(region_name)
        if canonical and canonical in self.brain_regions:
            return self.brain_regions[canonical].networks
        return []

    def get_cognitive_domains(self, task_name: str) -> list[str]:
        """
        Get cognitive domains associated with a task.

        Args:
            task_name: Name of the task

        Returns:
            List of cognitive domain names
        """
        canonical = self.resolve_term(task_name)
        if canonical and canonical in self.tasks:
            return self.tasks[canonical].cognitive_domains
        return []


# Global ontology instance
_ontology_instance: NeuroImagingOntology | None = None


def get_domain_knowledge() -> NeuroImagingOntology:
    """
    Get or create the global neuroimaging ontology instance.

    Returns:
        Neuroimaging ontology instance
    """
    global _ontology_instance

    if _ontology_instance is None:
        _ontology_instance = NeuroImagingOntology()

    return _ontology_instance
