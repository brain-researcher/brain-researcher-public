"""
Advanced Query Understanding Module for Brain Researcher Agent (AGENT-017)

This module implements enhanced NLP with context awareness and domain knowledge
for better query parsing, including entity extraction, domain term recognition,
query expansion with synonyms, and semantic similarity matching.
"""

import json
import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple, Union

import numpy as np
from langchain_core.language_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class EntityType(str, Enum):
    """Types of entities that can be extracted from queries."""
    
    BRAIN_REGION = "brain_region"
    TASK = "task"
    DATASET = "dataset"
    CONTRAST = "contrast"
    STATISTICAL_METHOD = "statistical_method"
    PREPROCESSING_STEP = "preprocessing_step"
    MODALITY = "modality"
    SUBJECT_GROUP = "subject_group"
    METRIC = "metric"
    COORDINATE = "coordinate"


class QueryIntent(str, Enum):
    """Possible intents for neuroscience queries."""
    
    ANALYSIS = "analysis"
    COMPARISON = "comparison"
    CORRELATION = "correlation"
    PREDICTION = "prediction"
    VISUALIZATION = "visualization"
    SEARCH = "search"
    PREPROCESSING = "preprocessing"
    META_ANALYSIS = "meta_analysis"
    QUALITY_CONTROL = "quality_control"
    DATA_EXTRACTION = "data_extraction"


@dataclass
class ExtractedEntity:
    """Represents an extracted entity from a query."""
    
    text: str
    entity_type: EntityType
    confidence: float
    normalized_form: str
    context: str = ""
    aliases: List[str] = field(default_factory=list)
    coordinates: Optional[Tuple[float, float, float]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class QueryExpansion:
    """Represents query expansion with synonyms and related terms."""
    
    original_query: str
    expanded_terms: Dict[str, List[str]]
    synonyms: Dict[str, List[str]]
    related_concepts: List[str]
    domain_terms: List[str]
    confidence: float


@dataclass
class ParsedQuery:
    """Complete parsed query with all extracted information."""
    
    original_query: str
    normalized_query: str
    primary_intent: QueryIntent
    secondary_intents: List[QueryIntent] = field(default_factory=list)
    entities: List[ExtractedEntity] = field(default_factory=list)
    expansion: Optional[QueryExpansion] = None
    context_vector: Optional[np.ndarray] = None
    complexity_score: float = 0.0
    confidence: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def get_entities_by_type(self, entity_type: EntityType) -> List[ExtractedEntity]:
        """Get all entities of a specific type."""
        return [entity for entity in self.entities if entity.entity_type == entity_type]


class ContextManager:
    """Manages contextual information for query understanding."""
    
    def __init__(self):
        """Initialize the context manager."""
        self.conversation_history: List[str] = []
        self.session_context: Dict[str, Any] = {}
        self.user_preferences: Dict[str, Any] = {}
        self.domain_context: Dict[str, Any] = {}
    
    def update_context(
        self,
        query: str,
        session_data: Optional[Dict[str, Any]] = None,
        user_data: Optional[Dict[str, Any]] = None
    ):
        """
        Update context with new information.
        
        Args:
            query: Latest query
            session_data: Session-specific context
            user_data: User-specific preferences
        """
        # Add to conversation history
        self.conversation_history.append(query)
        
        # Keep only recent history
        if len(self.conversation_history) > 10:
            self.conversation_history = self.conversation_history[-10:]
        
        # Update session context
        if session_data:
            self.session_context.update(session_data)
        
        # Update user preferences
        if user_data:
            self.user_preferences.update(user_data)
    
    def get_contextual_information(self) -> Dict[str, Any]:
        """Get all contextual information for query understanding."""
        return {
            "conversation_history": self.conversation_history,
            "session_context": self.session_context,
            "user_preferences": self.user_preferences,
            "domain_context": self.domain_context,
            "recent_queries": self.conversation_history[-3:] if self.conversation_history else []
        }


class EntityExtractor:
    """Extracts neuroimaging entities from queries using patterns and LLM."""
    
    def __init__(self, llm: BaseChatModel, domain_knowledge=None):
        """
        Initialize the entity extractor.
        
        Args:
            llm: Language model for entity extraction
            domain_knowledge: Domain knowledge base
        """
        self.llm = llm
        self.domain_knowledge = domain_knowledge
        
        # Compile regex patterns for common entities
        self.patterns = self._compile_patterns()
    
    def _compile_patterns(self) -> Dict[EntityType, List[re.Pattern]]:
        """Compile regex patterns for entity extraction."""
        patterns = {
            EntityType.COORDINATE: [
                re.compile(r'(?:coordinates?|coords?)\s*:?\s*(?:\(|\[)?(-?\d+\.?\d*),?\s*(-?\d+\.?\d*),?\s*(-?\d+\.?\d*)(?:\)|\])?', re.IGNORECASE),
                re.compile(r'MNI\s*(?:coordinates?|coords?)?\s*:?\s*(?:\(|\[)?(-?\d+\.?\d*),?\s*(-?\d+\.?\d*),?\s*(-?\d+\.?\d*)(?:\)|\])?', re.IGNORECASE),
                re.compile(r'(?:\(|\[)(-?\d+\.?\d*),?\s*(-?\d+\.?\d*),?\s*(-?\d+\.?\d*)(?:\)|\])', re.IGNORECASE)
            ],
            EntityType.BRAIN_REGION: [
                re.compile(r'\b(?:anterior|posterior|left|right|bilateral)\s+(?:cingulate|cortex|gyrus|sulcus|lobe|area)\b', re.IGNORECASE),
                re.compile(r'\b(?:frontal|parietal|temporal|occipital)\s+(?:cortex|lobe|region)\b', re.IGNORECASE),
                re.compile(r'\b(?:amygdala|hippocampus|thalamus|caudate|putamen|nucleus accumbens|insula|cerebellum)\b', re.IGNORECASE),
                re.compile(r'\bBA\s*\d+\b', re.IGNORECASE),  # Brodmann areas
                re.compile(r'\bV\d+\b(?:\s+area)?', re.IGNORECASE)  # Visual areas
            ],
            EntityType.TASK: [
                re.compile(r'\b(?:n-back|oddball|stroop|go/no-go|stop signal|flanker|simon|attention|memory|language|motor|emotional|reward)\s*(?:task|paradigm)?\b', re.IGNORECASE),
                re.compile(r'\b(?:working memory|episodic memory|semantic memory|executive control|cognitive control)\b', re.IGNORECASE)
            ],
            EntityType.STATISTICAL_METHOD: [
                re.compile(r'\b(?:GLM|general linear model|t-test|ANOVA|correlation|regression|PCA|ICA|SVM|machine learning|classification|clustering)\b', re.IGNORECASE),
                re.compile(r'\b(?:FWE|FDR|Bonferroni|cluster correction|multiple comparison)\b', re.IGNORECASE)
            ],
            EntityType.PREPROCESSING_STEP: [
                re.compile(r'\b(?:skull stripping|motion correction|slice timing|normalization|smoothing|registration|segmentation)\b', re.IGNORECASE),
                re.compile(r'\b(?:fMRIPrep|SPM|FSL|AFNI|ANTs|FreeSurfer)\b', re.IGNORECASE)
            ],
            EntityType.MODALITY: [
                re.compile(r'\b(?:fMRI|sMRI|DTI|DWI|ASL|PET|EEG|MEG|BOLD|T1|T2|FLAIR)\b', re.IGNORECASE)
            ]
        }
        
        return patterns
    
    def extract_entities(self, query: str, context: Dict[str, Any]) -> List[ExtractedEntity]:
        """
        Extract entities from query using patterns and LLM.
        
        Args:
            query: Query text
            context: Contextual information
            
        Returns:
            List of extracted entities
        """
        entities = []
        
        # Extract using regex patterns
        pattern_entities = self._extract_with_patterns(query)
        entities.extend(pattern_entities)
        
        # Extract using LLM for complex entities
        llm_entities = self._extract_with_llm(query, context)
        entities.extend(llm_entities)
        
        # Remove duplicates and merge overlapping entities
        entities = self._merge_entities(entities)
        
        return entities
    
    def _extract_with_patterns(self, query: str) -> List[ExtractedEntity]:
        """Extract entities using regex patterns."""
        entities = []
        
        for entity_type, patterns in self.patterns.items():
            for pattern in patterns:
                matches = pattern.finditer(query)
                for match in matches:
                    if entity_type == EntityType.COORDINATE:
                        # Special handling for coordinates
                        coords = tuple(float(g) for g in match.groups() if g)
                        if len(coords) == 3:
                            entity = ExtractedEntity(
                                text=match.group(0),
                                entity_type=entity_type,
                                confidence=0.9,
                                normalized_form=f"[{coords[0]}, {coords[1]}, {coords[2]}]",
                                coordinates=coords
                            )
                            entities.append(entity)
                    else:
                        entity = ExtractedEntity(
                            text=match.group(0),
                            entity_type=entity_type,
                            confidence=0.8,
                            normalized_form=match.group(0).lower().strip(),
                            context=query[max(0, match.start()-20):match.end()+20]
                        )
                        entities.append(entity)
        
        return entities
    
    def _extract_with_llm(self, query: str, context: Dict[str, Any]) -> List[ExtractedEntity]:
        """Extract entities using LLM for complex cases."""
        if self.llm is None:
            return []
        try:
            extraction_prompt = ChatPromptTemplate.from_messages([
                ("system", """You are a neuroimaging entity extractor. 
                
                Extract entities from the query and classify them into these types:
                - brain_region: Brain regions, areas, networks
                - task: Cognitive tasks or paradigms
                - dataset: Dataset names or IDs
                - contrast: Statistical contrasts or comparisons
                - statistical_method: Statistical methods or analyses
                - preprocessing_step: Preprocessing steps or pipelines
                - modality: Imaging modalities
                - subject_group: Subject groups or populations
                - metric: Metrics or measures
                
                Return a JSON array of entities:
                [
                    {{
                        "text": "extracted text",
                        "type": "entity_type",
                        "confidence": 0.95,
                        "normalized": "normalized form"
                    }}
                ]"""),
                ("human", "Query: {query}\nContext: {context}")
            ])
            
            chain = extraction_prompt | self.llm
            response = chain.invoke({
                "query": query,
                "context": str(context)
            })
            
            # Parse response
            content = response.content
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]
            
            entities_data = json.loads(content)
            
            entities = []
            for entity_data in entities_data:
                try:
                    entity_type = EntityType(entity_data.get("type", "brain_region"))
                    entity = ExtractedEntity(
                        text=entity_data.get("text", ""),
                        entity_type=entity_type,
                        confidence=entity_data.get("confidence", 0.7),
                        normalized_form=entity_data.get("normalized", entity_data.get("text", "").lower())
                    )
                    entities.append(entity)
                except (ValueError, KeyError) as e:
                    logger.warning(f"Failed to parse entity: {entity_data}, error: {e}")
            
            return entities
            
        except Exception as e:
            logger.warning(f"LLM entity extraction failed: {e}")
            return []
    
    def _merge_entities(self, entities: List[ExtractedEntity]) -> List[ExtractedEntity]:
        """Merge overlapping or duplicate entities."""
        if not entities:
            return entities
        
        # Sort by text position (approximate)
        entities.sort(key=lambda x: len(x.text), reverse=True)
        
        merged = []
        used_texts = set()
        
        for entity in entities:
            # Skip if we've seen this text before
            if entity.text.lower() in used_texts:
                continue
            
            # Check for overlaps with existing entities
            is_overlapping = False
            for existing in merged:
                if (entity.text.lower() in existing.text.lower() or 
                    existing.text.lower() in entity.text.lower()):
                    # Keep the one with higher confidence
                    if entity.confidence > existing.confidence:
                        merged.remove(existing)
                        merged.append(entity)
                        used_texts.add(entity.text.lower())
                    is_overlapping = True
                    break
            
            if not is_overlapping:
                merged.append(entity)
                used_texts.add(entity.text.lower())
        
        return merged


class QueryExpander:
    """Expands queries with synonyms and related terms."""
    
    def __init__(self, domain_knowledge=None):
        """
        Initialize the query expander.
        
        Args:
            domain_knowledge: Domain knowledge base
        """
        self.domain_knowledge = domain_knowledge
        self.synonym_cache = {}
        
        # Load built-in synonym mappings
        self.built_in_synonyms = self._load_built_in_synonyms()
    
    def _load_built_in_synonyms(self) -> Dict[str, List[str]]:
        """Load built-in neuroimaging synonyms."""
        return {
            "fmri": ["functional mri", "functional magnetic resonance imaging", "bold fmri"],
            "dmn": ["default mode network", "default network", "resting state network"],
            "roi": ["region of interest", "regions of interest"],
            "glm": ["general linear model", "general linear models"],
            "svm": ["support vector machine", "support vector machines"],
            "pca": ["principal component analysis", "principal components analysis"],
            "ica": ["independent component analysis", "independent components analysis"],
            "bold": ["blood oxygen level dependent", "blood oxygenation level dependent"],
            "preprocessing": ["pre-processing", "data preprocessing"],
            "connectivity": ["functional connectivity", "effective connectivity", "structural connectivity"],
            "activation": ["brain activation", "neural activation", "cortical activation"],
            "contrast": ["statistical contrast", "contrasts", "comparison"],
            "cluster": ["brain cluster", "activation cluster", "statistical cluster"],
            "threshold": ["statistical threshold", "significance threshold"],
            "correction": ["multiple comparison correction", "multiple comparisons correction"],
        }
    
    def expand_query(
        self, 
        query: str, 
        entities: List[ExtractedEntity],
        context: Dict[str, Any]
    ) -> QueryExpansion:
        """
        Expand query with synonyms and related terms.
        
        Args:
            query: Original query
            entities: Extracted entities
            context: Contextual information
            
        Returns:
            Query expansion with synonyms and related terms
        """
        expanded_terms = {}
        synonyms = {}
        related_concepts = []
        domain_terms = []
        
        # Get synonyms for extracted entities
        for entity in entities:
            entity_synonyms = self._get_synonyms(entity.normalized_form)
            if entity_synonyms:
                synonyms[entity.text] = entity_synonyms
                expanded_terms[entity.text] = entity_synonyms
        
        # Get synonyms for key terms in query
        words = query.lower().split()
        for word in words:
            if word in self.built_in_synonyms:
                synonyms[word] = self.built_in_synonyms[word]
                expanded_terms[word] = self.built_in_synonyms[word]
        
        # Get related concepts from domain knowledge
        if self.domain_knowledge:
            related_concepts = self.domain_knowledge.get_related_concepts(query)
            domain_terms = self.domain_knowledge.get_domain_terms(query)
        
        # Calculate expansion confidence
        confidence = self._calculate_expansion_confidence(
            expanded_terms, synonyms, related_concepts
        )
        
        return QueryExpansion(
            original_query=query,
            expanded_terms=expanded_terms,
            synonyms=synonyms,
            related_concepts=related_concepts,
            domain_terms=domain_terms,
            confidence=confidence
        )
    
    def _get_synonyms(self, term: str) -> List[str]:
        """Get synonyms for a term."""
        term = term.lower().strip()
        
        # Check built-in synonyms
        if term in self.built_in_synonyms:
            return self.built_in_synonyms[term]
        
        # Check cache
        if term in self.synonym_cache:
            return self.synonym_cache[term]
        
        # Check domain knowledge
        if self.domain_knowledge:
            synonyms = self.domain_knowledge.get_synonyms(term)
            self.synonym_cache[term] = synonyms
            return synonyms
        
        return []
    
    def _calculate_expansion_confidence(
        self,
        expanded_terms: Dict[str, List[str]],
        synonyms: Dict[str, List[str]],
        related_concepts: List[str]
    ) -> float:
        """Calculate confidence score for query expansion."""
        if not expanded_terms and not related_concepts:
            return 0.0
        
        # Base confidence on number of expansions found
        expansion_score = min(len(expanded_terms) / 5.0, 1.0)  # Max 5 expansions
        concept_score = min(len(related_concepts) / 10.0, 0.3)  # Max 10 concepts, 30% weight
        
        return min(expansion_score + concept_score, 1.0)


class AdvancedQueryParser:
    """
    Advanced query parser with context awareness and domain knowledge.
    
    Features:
    - Context-aware entity extraction
    - Domain term recognition (>90% accuracy target)
    - Query expansion with synonyms
    - Semantic similarity matching
    - Multi-intent query support
    """
    
    def __init__(self, domain_kb=None, embeddings=None, llm=None):
        """
        Initialize the advanced query parser.
        
        Args:
            domain_kb: Domain knowledge base
            embeddings: Embedding model for semantic similarity
            llm: Language model for complex parsing
        """
        self.domain_knowledge = domain_kb
        self.embeddings = embeddings
        self.llm = llm
        
        # Initialize components
        # Always enable regex-based extraction; LLM extraction is optional.
        self.entity_extractor = EntityExtractor(llm, domain_kb)
        self.context_manager = ContextManager()
        self.query_expander = QueryExpander(domain_kb)
        
        # Intent classification patterns
        self.intent_patterns = self._compile_intent_patterns()
        
        logger.info("Advanced Query Parser initialized")
    
    def _compile_intent_patterns(self) -> Dict[QueryIntent, List[re.Pattern]]:
        """Compile regex patterns for intent classification."""
        return {
            QueryIntent.ANALYSIS: [
                re.compile(r'\b(?:analyze|analysis|examine|investigate|study|explore)\b', re.IGNORECASE),
                re.compile(r'\b(?:glm|statistical|statistics|test|model)\b', re.IGNORECASE)
            ],
            QueryIntent.COMPARISON: [
                re.compile(r'\b(?:compare|comparison|versus|vs|between|difference|contrast)\b', re.IGNORECASE),
                re.compile(r'\b(?:group|condition|task).*(?:difference|compare|contrast)\b', re.IGNORECASE)
            ],
            QueryIntent.CORRELATION: [
                re.compile(r'\b(?:correlat|relationship|association|connect|link)\b', re.IGNORECASE),
                re.compile(r'\b(?:connectivity|network|functional connectivity)\b', re.IGNORECASE)
            ],
            QueryIntent.PREDICTION: [
                re.compile(r'\b(?:predict|prediction|classify|classification|machine learning|svm|random forest)\b', re.IGNORECASE)
            ],
            QueryIntent.VISUALIZATION: [
                re.compile(r'\b(?:visualiz|plot|display|show|render|image|figure)\b', re.IGNORECASE),
                re.compile(r'\b(?:brain map|activation map|statistical map)\b', re.IGNORECASE)
            ],
            QueryIntent.SEARCH: [
                re.compile(r'\b(?:search|find|locate|identify|discover|look for)\b', re.IGNORECASE)
            ],
            QueryIntent.PREPROCESSING: [
                re.compile(r'\b(?:preprocess|preprocessing|normalize|smooth|register|skull strip)\b', re.IGNORECASE)
            ],
            QueryIntent.META_ANALYSIS: [
                re.compile(r'\b(?:meta.analysis|coordinate.based|activation likelihood)\b', re.IGNORECASE)
            ]
        }
    
    def parse(self, query: str, context: Optional[Dict[str, Any]] = None) -> ParsedQuery:
        """
        Parse a query with advanced NLP and context awareness.
        
        Args:
            query: Query text to parse
            context: Additional context for parsing
            
        Returns:
            Comprehensive parsed query object
        """
        context = context or {}
        
        # Update context manager
        self.context_manager.update_context(query, context)
        full_context = self.context_manager.get_contextual_information()
        
        # Normalize query
        normalized_query = self._normalize_query(query)
        
        # Extract intent(s)
        primary_intent, secondary_intents = self._classify_intent(query)
        
        # Extract entities
        entities = []
        if self.entity_extractor:
            entities = self.entity_extractor.extract_entities(query, full_context)
        
        # Expand query
        expansion = self.query_expander.expand_query(query, entities, full_context)
        
        # Compute embeddings if available
        context_vector = None
        if self.embeddings:
            context_vector = self._compute_context_vector(query, expansion)
        
        # Calculate complexity score
        complexity_score = self._calculate_complexity(query, entities, secondary_intents)
        
        # Calculate overall confidence
        confidence = self._calculate_confidence(
            entities, expansion, primary_intent, complexity_score
        )
        
        # Create parsed query
        parsed_query = ParsedQuery(
            original_query=query,
            normalized_query=normalized_query,
            primary_intent=primary_intent,
            secondary_intents=secondary_intents,
            entities=entities,
            expansion=expansion,
            context_vector=context_vector,
            complexity_score=complexity_score,
            confidence=confidence,
            metadata={
                "context_used": bool(context),
                "entity_count": len(entities),
                "expansion_terms": len(expansion.expanded_terms) if expansion else 0,
                "has_coordinates": any(e.entity_type == EntityType.COORDINATE for e in entities)
            }
        )
        
        logger.info(
            f"Parsed query with {len(entities)} entities, "
            f"intent: {primary_intent.value}, confidence: {confidence:.3f}"
        )
        
        return parsed_query
    
    def _normalize_query(self, query: str) -> str:
        """Normalize query text."""
        # Remove extra whitespace
        normalized = re.sub(r'\s+', ' ', query.strip())
        
        # Expand common abbreviations
        abbreviations = {
            r'\bfmri\b': 'functional MRI',
            r'\broi\b': 'region of interest',
            r'\bdmn\b': 'default mode network',
            r'\bglm\b': 'general linear model',
            r'\bsvm\b': 'support vector machine',
            r'\bpca\b': 'principal component analysis',
            r'\bica\b': 'independent component analysis'
        }
        
        for abbrev, expansion in abbreviations.items():
            normalized = re.sub(abbrev, expansion, normalized, flags=re.IGNORECASE)
        
        return normalized
    
    def _classify_intent(self, query: str) -> Tuple[QueryIntent, List[QueryIntent]]:
        """Classify the primary and secondary intents of a query."""
        intent_scores = {}
        
        # Score each intent based on pattern matches
        for intent, patterns in self.intent_patterns.items():
            score = 0
            for pattern in patterns:
                matches = pattern.findall(query)
                score += len(matches)
            intent_scores[intent] = score
        
        # Get primary intent (highest score)
        if intent_scores:
            primary_intent = max(intent_scores, key=intent_scores.get)
        else:
            primary_intent = QueryIntent.ANALYSIS  # Default
        
        # Get secondary intents (score > 0 and != primary)
        secondary_intents = [
            intent for intent, score in intent_scores.items()
            if score > 0 and intent != primary_intent
        ]
        
        return primary_intent, secondary_intents
    
    def _compute_context_vector(
        self, 
        query: str, 
        expansion: QueryExpansion
    ) -> Optional[np.ndarray]:
        """Compute context vector for semantic similarity."""
        if not self.embeddings:
            return None
        
        try:
            # Combine original query with expansions
            expanded_text = query
            if expansion and expansion.expanded_terms:
                for term, synonyms in expansion.expanded_terms.items():
                    expanded_text += " " + " ".join(synonyms[:3])  # Add top 3 synonyms
            
            # Compute embedding
            vector = self.embeddings.embed_query(expanded_text)
            return np.array(vector)
            
        except Exception as e:
            logger.warning(f"Failed to compute context vector: {e}")
            return None
    
    def _calculate_complexity(
        self, 
        query: str, 
        entities: List[ExtractedEntity], 
        secondary_intents: List[QueryIntent]
    ) -> float:
        """Calculate query complexity score (0-1)."""
        complexity_factors = [
            len(query.split()) / 50.0,  # Length factor (max 50 words = 1.0)
            len(entities) / 10.0,  # Entity factor (max 10 entities = 1.0)
            len(secondary_intents) / 3.0,  # Multi-intent factor (max 3 = 1.0)
            query.count('?') / 3.0,  # Question factor (max 3 questions = 1.0)
            query.count(' and ') / 5.0,  # Conjunction factor (max 5 = 1.0)
            query.count(' or ') / 5.0,  # Disjunction factor (max 5 = 1.0)
        ]
        
        # Weighted average
        weights = [0.2, 0.3, 0.2, 0.1, 0.1, 0.1]
        complexity = sum(f * w for f, w in zip(complexity_factors, weights))
        
        return min(complexity, 1.0)
    
    def _calculate_confidence(
        self,
        entities: List[ExtractedEntity],
        expansion: QueryExpansion,
        primary_intent: QueryIntent,
        complexity_score: float
    ) -> float:
        """Calculate overall parsing confidence."""
        factors = []
        
        # Entity extraction confidence
        if entities:
            entity_confidence = sum(e.confidence for e in entities) / len(entities)
            factors.append(entity_confidence * 0.4)  # 40% weight
        
        # Query expansion confidence
        if expansion:
            factors.append(expansion.confidence * 0.3)  # 30% weight
        
        # Intent classification confidence (heuristic)
        intent_confidence = 0.8 if primary_intent != QueryIntent.ANALYSIS else 0.6
        factors.append(intent_confidence * 0.2)  # 20% weight
        
        # Complexity penalty (simpler queries are more reliable)
        complexity_penalty = 1.0 - (complexity_score * 0.3)
        factors.append(complexity_penalty * 0.1)  # 10% weight
        
        if not factors:
            return 0.5  # Neutral confidence if no factors
        
        return min(sum(factors), 1.0)
    
    def get_semantic_similarity(self, query1: str, query2: str) -> float:
        """
        Calculate semantic similarity between two queries.
        
        Args:
            query1: First query
            query2: Second query
            
        Returns:
            Similarity score (0-1)
        """
        if not self.embeddings:
            # Fallback to simple text similarity
            words1 = set(query1.lower().split())
            words2 = set(query2.lower().split())
            if not words1 or not words2:
                return 0.0
            return len(words1.intersection(words2)) / len(words1.union(words2))
        
        try:
            # Parse both queries
            parsed1 = self.parse(query1)
            parsed2 = self.parse(query2)
            
            # Compute cosine similarity of context vectors
            if parsed1.context_vector is not None and parsed2.context_vector is not None:
                dot_product = np.dot(parsed1.context_vector, parsed2.context_vector)
                norm1 = np.linalg.norm(parsed1.context_vector)
                norm2 = np.linalg.norm(parsed2.context_vector)
                
                if norm1 > 0 and norm2 > 0:
                    return dot_product / (norm1 * norm2)
            
            return 0.0
            
        except Exception as e:
            logger.warning(f"Failed to calculate semantic similarity: {e}")
            return 0.0


# Factory function
def create_advanced_parser(
    domain_knowledge=None,
    embeddings=None,
    llm=None
) -> AdvancedQueryParser:
    """
    Create an advanced query parser instance.
    
    Args:
        domain_knowledge: Domain knowledge base
        embeddings: Embedding model
        llm: Language model
        
    Returns:
        Configured advanced query parser
    """
    return AdvancedQueryParser(domain_knowledge, embeddings, llm)
