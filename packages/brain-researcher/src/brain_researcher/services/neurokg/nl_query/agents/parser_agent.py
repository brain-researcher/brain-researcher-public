"""
Query Parser Agent for Natural Language Query Processing

Parses natural language queries to extract intent, entities, and constraints.
"""

import logging
import re
from typing import Dict, Any, List, Optional, Set, Tuple
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class QueryIntent(str, Enum):
    """Types of query intents"""
    SEARCH = "search"
    AGGREGATE = "aggregate"
    COMPARE = "compare"
    RELATE = "relate"
    EXPLAIN = "explain"
    VISUALIZE = "visualize"
    CORRELATE = "correlate"
    PREDICT = "predict"


class EntityType(str, Enum):
    """Types of entities in neuroimaging domain"""
    BRAIN_REGION = "brain_region"
    COGNITIVE_TASK = "cognitive_task"
    DATASET = "dataset"
    STUDY = "study"
    AUTHOR = "author"
    DISORDER = "disorder"
    GENE = "gene"
    DRUG = "drug"
    MODALITY = "modality"
    METRIC = "metric"
    COORDINATE = "coordinate"
    SUBJECT_GROUP = "subject_group"


@dataclass
class ExtractedEntity:
    """An entity extracted from the query"""
    text: str
    type: EntityType
    normalized_form: str
    position: int
    confidence: float


@dataclass
class QueryConstraint:
    """A constraint extracted from the query"""
    type: str  # 'temporal', 'spatial', 'numeric', 'categorical'
    field: str
    operator: str  # '>', '<', '=', 'contains', 'between'
    value: Any
    confidence: float


@dataclass
class ParsedQuery:
    """Result of parsing a natural language query"""
    original_query: str
    intent: QueryIntent
    entities: List[ExtractedEntity]
    constraints: List[QueryConstraint]
    modifiers: Dict[str, Any]  # limit, sort, group_by, etc.
    confidence_score: float
    ambiguities: List[str] = field(default_factory=list)


class QueryParserAgent:
    """
    Agent responsible for parsing natural language queries.
    
    Extracts:
    - Query intent (what the user wants to do)
    - Entities (brain regions, tasks, datasets, etc.)
    - Constraints (filters, conditions)
    - Modifiers (sorting, limiting, grouping)
    """
    
    # Intent patterns
    INTENT_PATTERNS = {
        QueryIntent.SEARCH: [
            r'\b(find|search|get|show|list|retrieve)\b',
            r'\b(what|which|where)\b.*\?'
        ],
        QueryIntent.AGGREGATE: [
            r'\b(count|sum|average|mean|median|total|how many)\b',
            r'\b(statistics|stats)\b'
        ],
        QueryIntent.COMPARE: [
            r'\b(compare|versus|vs|difference|contrast)\b',
            r'\b(between|among)\b.*\band\b'
        ],
        QueryIntent.RELATE: [
            r'\b(relate|connect|associate|link)\b',
            r'\b(relationship|connection|association)\b'
        ],
        QueryIntent.EXPLAIN: [
            r'\b(explain|why|how|describe)\b',
            r'\b(meaning|significance)\b'
        ],
        QueryIntent.VISUALIZE: [
            r'\b(plot|graph|visualize|display|render|map)\b',
            r'\b(heatmap|network|brain)\b'
        ],
        QueryIntent.CORRELATE: [
            r'\b(correlate|correlation|coactivate|coactivation)\b',
            r'\b(predict|associated with)\b'
        ]
    }
    
    # Entity patterns for neuroimaging domain
    ENTITY_PATTERNS = {
        EntityType.BRAIN_REGION: [
            # Common brain regions
            r'\b(hippocampus|amygdala|thalamus|cortex|cerebellum)\b',
            r'\b(frontal|parietal|temporal|occipital)\s+\w+',
            r'\b(PFC|ACC|OFC|DLPFC|VMPFC|IFG|STG|MTG|ITG)\b',
            r'\b(BA\s?\d{1,2})\b',  # Brodmann areas
            r'\b(left|right|bilateral)\s+\w+',
        ],
        EntityType.COGNITIVE_TASK: [
            r'\b(working memory|attention|emotion|language|motor)\b',
            r'\b(n-back|stroop|go/no-go|oddball|flanker)\b',
            r'\b(face|word|object)\s+(processing|recognition)',
            r'\b(decision making|reward|punishment)\b'
        ],
        EntityType.DATASET: [
            r'\b(HCP|ABCD|ADNI|OpenNeuro|UK Biobank)\b',
            r'\bds\d{6}\b',  # OpenNeuro dataset IDs
            r'\b(dataset|study|cohort|sample)\b'
        ],
        EntityType.DISORDER: [
            r'\b(alzheimer|parkinson|schizophrenia|depression|autism)\b',
            r'\b(AD|PD|MDD|ASD|ADHD|OCD|PTSD)\b',
            r'\b(disorder|disease|syndrome|condition)\b'
        ],
        EntityType.MODALITY: [
            r'\b(fMRI|MRI|PET|EEG|MEG|DTI|DWI)\b',
            r'\b(BOLD|structural|functional|connectivity)\b',
            r'\b(resting.?state|task.?based)\b'
        ],
        EntityType.COORDINATE: [
            r'MNI:\s*\[?\s*(-?\d+),\s*(-?\d+),\s*(-?\d+)\s*\]?',
            r'TAL:\s*\[?\s*(-?\d+),\s*(-?\d+),\s*(-?\d+)\s*\]?',
            r'\[?\s*(-?\d+),\s*(-?\d+),\s*(-?\d+)\s*\]?\s*mm'
        ]
    }
    
    # Constraint patterns
    CONSTRAINT_PATTERNS = {
        'temporal': [
            r'(after|before|since|until|between)\s+(\d{4})',
            r'(last|past|recent)\s+(\d+)\s+(year|month|day)s?',
            r'(published|conducted)\s+(in|during)\s+(\d{4})'
        ],
        'numeric': [
            r'(more than|greater than|>)\s+(\d+)',
            r'(less than|fewer than|<)\s+(\d+)',
            r'(between|from)\s+(\d+)\s+(to|and)\s+(\d+)',
            r'(at least|minimum)\s+(\d+)',
            r'(at most|maximum)\s+(\d+)'
        ],
        'spatial': [
            r'within\s+(\d+)\s*mm\s+of',
            r'(anterior|posterior|superior|inferior|medial|lateral)\s+to'
        ]
    }
    
    def __init__(self):
        """Initialize the parser agent"""
        self._entity_cache = {}
        self._compile_patterns()
    
    def _compile_patterns(self):
        """Compile regex patterns for efficiency"""
        self._compiled_patterns = {
            'intent': {},
            'entity': {},
            'constraint': {}
        }
        
        # Compile intent patterns
        for intent, patterns in self.INTENT_PATTERNS.items():
            self._compiled_patterns['intent'][intent] = [
                re.compile(p, re.IGNORECASE) for p in patterns
            ]
        
        # Compile entity patterns  
        for entity_type, patterns in self.ENTITY_PATTERNS.items():
            self._compiled_patterns['entity'][entity_type] = [
                re.compile(p, re.IGNORECASE) for p in patterns
            ]
        
        # Compile constraint patterns
        for constraint_type, patterns in self.CONSTRAINT_PATTERNS.items():
            self._compiled_patterns['constraint'][constraint_type] = [
                re.compile(p, re.IGNORECASE) for p in patterns
            ]
    
    def parse(
        self,
        query: str,
        context: Optional[Dict[str, Any]] = None
    ) -> ParsedQuery:
        """
        Parse a natural language query
        
        Args:
            query: The natural language query string
            context: Optional context (user preferences, history, etc.)
            
        Returns:
            ParsedQuery object with extracted information
        """
        # Clean and normalize query
        query_normalized = self._normalize_query(query)
        
        # Extract intent
        intent, intent_confidence = self._extract_intent(query_normalized)
        
        # Extract entities
        entities = self._extract_entities(query_normalized)
        
        # Extract constraints
        constraints = self._extract_constraints(query_normalized)
        
        # Extract modifiers (limit, sort, etc.)
        modifiers = self._extract_modifiers(query_normalized)
        
        # Check for ambiguities
        ambiguities = self._detect_ambiguities(query_normalized, entities)
        
        # Calculate overall confidence
        confidence = self._calculate_confidence(
            intent_confidence,
            entities,
            constraints
        )
        
        return ParsedQuery(
            original_query=query,
            intent=intent,
            entities=entities,
            constraints=constraints,
            modifiers=modifiers,
            confidence_score=confidence,
            ambiguities=ambiguities
        )
    
    def _normalize_query(self, query: str) -> str:
        """Normalize the query text"""
        # Remove extra whitespace
        query = ' '.join(query.split())
        
        # Expand common abbreviations
        abbreviations = {
            "what's": "what is",
            "where's": "where is",
            "how's": "how is",
            "BA": "Brodmann area",
            "WM": "working memory",
            "RS": "resting state"
        }
        
        for abbr, full in abbreviations.items():
            query = re.sub(r'\b' + abbr + r'\b', full, query, flags=re.IGNORECASE)
        
        return query
    
    def _extract_intent(self, query: str) -> Tuple[QueryIntent, float]:
        """Extract the primary intent from the query"""
        intent_scores = {}
        
        for intent, patterns in self._compiled_patterns['intent'].items():
            score = 0.0
            for pattern in patterns:
                if pattern.search(query):
                    score += 1.0
            intent_scores[intent] = score
        
        # Get intent with highest score
        if intent_scores:
            best_intent = max(intent_scores, key=intent_scores.get)
            max_score = intent_scores[best_intent]
            
            # Calculate confidence based on score
            confidence = min(1.0, max_score / 2.0)  # Normalize to 0-1
            
            if confidence > 0:
                return best_intent, confidence
        
        # Default to SEARCH if no clear intent
        return QueryIntent.SEARCH, 0.5
    
    def _extract_entities(self, query: str) -> List[ExtractedEntity]:
        """Extract entities from the query"""
        entities = []
        
        for entity_type, patterns in self._compiled_patterns['entity'].items():
            for pattern in patterns:
                for match in pattern.finditer(query):
                    entity_text = match.group(0)
                    
                    # Skip if this text was already extracted as a different entity
                    if any(e.text == entity_text for e in entities):
                        continue
                    
                    entities.append(ExtractedEntity(
                        text=entity_text,
                        type=entity_type,
                        normalized_form=self._normalize_entity(entity_text, entity_type),
                        position=match.start(),
                        confidence=self._calculate_entity_confidence(entity_text, entity_type)
                    ))
        
        # Sort by position in query
        entities.sort(key=lambda e: e.position)
        
        return entities
    
    def _extract_constraints(self, query: str) -> List[QueryConstraint]:
        """Extract constraints from the query"""
        constraints = []
        
        for constraint_type, patterns in self._compiled_patterns['constraint'].items():
            for pattern in patterns:
                for match in pattern.finditer(query):
                    constraint = self._parse_constraint(
                        match,
                        constraint_type,
                        query
                    )
                    if constraint:
                        constraints.append(constraint)
        
        return constraints
    
    def _extract_modifiers(self, query: str) -> Dict[str, Any]:
        """Extract query modifiers (limit, sort, group by)"""
        modifiers = {}
        
        # Extract limit
        limit_match = re.search(r'\b(top|first|last)\s+(\d+)\b', query, re.IGNORECASE)
        if limit_match:
            modifiers['limit'] = int(limit_match.group(2))
            modifiers['order'] = limit_match.group(1).lower()
        
        # Extract sorting
        sort_match = re.search(
            r'\b(sort|order)\s+by\s+(\w+)(?:\s+(asc|desc|ascending|descending))?\b',
            query,
            re.IGNORECASE
        )
        if sort_match:
            modifiers['sort_by'] = sort_match.group(2)
            modifiers['sort_order'] = 'desc' if sort_match.group(3) and 'desc' in sort_match.group(3).lower() else 'asc'
        
        # Extract grouping
        group_match = re.search(r'\b(group|grouped)\s+by\s+(\w+)\b', query, re.IGNORECASE)
        if group_match:
            modifiers['group_by'] = group_match.group(2)
        
        # Extract output format preferences
        if re.search(r'\b(table|list)\b', query, re.IGNORECASE):
            modifiers['format'] = 'table'
        elif re.search(r'\b(graph|network|visualization)\b', query, re.IGNORECASE):
            modifiers['format'] = 'graph'
        elif re.search(r'\b(summary|summarize)\b', query, re.IGNORECASE):
            modifiers['format'] = 'summary'
        
        return modifiers
    
    def _normalize_entity(self, text: str, entity_type: EntityType) -> str:
        """Normalize entity text to standard form"""
        normalized = text.lower().strip()
        
        # Entity-specific normalization
        if entity_type == EntityType.BRAIN_REGION:
            # Standardize brain region names
            region_map = {
                'pfc': 'prefrontal_cortex',
                'acc': 'anterior_cingulate_cortex',
                'ofc': 'orbitofrontal_cortex',
                'dlpfc': 'dorsolateral_prefrontal_cortex',
                'vmpfc': 'ventromedial_prefrontal_cortex'
            }
            normalized = region_map.get(normalized, normalized)
        
        elif entity_type == EntityType.DISORDER:
            # Standardize disorder names
            disorder_map = {
                'ad': 'alzheimer_disease',
                'pd': 'parkinson_disease',
                'mdd': 'major_depressive_disorder',
                'asd': 'autism_spectrum_disorder'
            }
            normalized = disorder_map.get(normalized, normalized)
        
        return normalized.replace(' ', '_')
    
    def _parse_constraint(
        self,
        match: re.Match,
        constraint_type: str,
        query: str
    ) -> Optional[QueryConstraint]:
        """Parse a constraint from a regex match"""
        try:
            if constraint_type == 'temporal':
                # Parse temporal constraints
                groups = match.groups()
                if len(groups) >= 2:
                    operator = groups[0].lower()
                    value = groups[1]
                    
                    return QueryConstraint(
                        type='temporal',
                        field='date',
                        operator=operator,
                        value=value,
                        confidence=0.8
                    )
            
            elif constraint_type == 'numeric':
                # Parse numeric constraints
                text = match.group(0)
                
                # Extract numbers
                numbers = re.findall(r'\d+', text)
                if not numbers:
                    return None
                
                operator = 'eq'
                value = int(numbers[0])
                
                if 'more than' in text or 'greater than' in text or '>' in text:
                    operator = 'gt'
                elif 'less than' in text or 'fewer than' in text or '<' in text:
                    operator = 'lt'
                elif 'between' in text and len(numbers) >= 2:
                    operator = 'between'
                    value = (int(numbers[0]), int(numbers[1]))
                elif 'at least' in text or 'minimum' in text:
                    operator = 'gte'
                elif 'at most' in text or 'maximum' in text:
                    operator = 'lte'
                
                # Determine field based on context
                field = self._infer_constraint_field(query, match.start())
                
                return QueryConstraint(
                    type='numeric',
                    field=field,
                    operator=operator,
                    value=value,
                    confidence=0.7
                )
            
            elif constraint_type == 'spatial':
                # Parse spatial constraints
                text = match.group(0)
                
                distance_match = re.search(r'(\d+)\s*mm', text)
                if distance_match:
                    return QueryConstraint(
                        type='spatial',
                        field='distance',
                        operator='within',
                        value=int(distance_match.group(1)),
                        confidence=0.8
                    )
                
        except Exception as e:
            logger.debug(f"Failed to parse constraint: {e}")
        
        return None
    
    def _infer_constraint_field(self, query: str, position: int) -> str:
        """Infer the field that a constraint applies to"""
        # Look at nearby text to determine field
        context_window = 50
        start = max(0, position - context_window)
        end = min(len(query), position + context_window)
        context = query[start:end].lower()
        
        # Common field mappings
        field_keywords = {
            'subjects': ['subject', 'participant', 'patient'],
            'age': ['age', 'years old'],
            'voxels': ['voxel', 'cluster'],
            'activation': ['activation', 'signal', 'bold'],
            'correlation': ['correlation', 'r-value'],
            'significance': ['p-value', 'significance', 'threshold']
        }
        
        for field, keywords in field_keywords.items():
            for keyword in keywords:
                if keyword in context:
                    return field
        
        return 'value'  # Default field
    
    def _detect_ambiguities(
        self,
        query: str,
        entities: List[ExtractedEntity]
    ) -> List[str]:
        """Detect potential ambiguities in the query"""
        ambiguities = []
        
        # Check for ambiguous pronouns
        if re.search(r'\b(it|they|them|this|that|these|those)\b', query, re.IGNORECASE):
            ambiguities.append("Query contains pronouns that may be ambiguous")
        
        # Check for multiple entities of same type
        entity_types = {}
        for entity in entities:
            if entity.type not in entity_types:
                entity_types[entity.type] = []
            entity_types[entity.type].append(entity)
        
        for entity_type, entity_list in entity_types.items():
            if len(entity_list) > 2:
                ambiguities.append(
                    f"Multiple {entity_type.value} entities found - relationship may be unclear"
                )
        
        # Check for missing context
        question_words = ['what', 'which', 'where', 'when', 'why', 'how']
        has_question = any(word in query.lower() for word in question_words)
        
        if has_question and not entities:
            ambiguities.append("Question lacks specific entities to query")
        
        return ambiguities
    
    def _calculate_entity_confidence(
        self,
        text: str,
        entity_type: EntityType
    ) -> float:
        """Calculate confidence score for an extracted entity"""
        confidence = 0.5  # Base confidence
        
        # Increase confidence for exact matches in known vocabularies
        known_entities = {
            EntityType.BRAIN_REGION: [
                'hippocampus', 'amygdala', 'prefrontal_cortex', 'thalamus'
            ],
            EntityType.DISORDER: [
                'alzheimer', 'parkinson', 'schizophrenia', 'depression'
            ],
            EntityType.MODALITY: [
                'fmri', 'mri', 'pet', 'eeg', 'meg'
            ]
        }
        
        if entity_type in known_entities:
            if text.lower() in known_entities[entity_type]:
                confidence = 0.95
            elif any(known in text.lower() for known in known_entities[entity_type]):
                confidence = 0.8
        
        # Adjust confidence based on text length
        if len(text) < 3:
            confidence *= 0.7  # Very short entities are less reliable
        
        return min(1.0, confidence)
    
    def _calculate_confidence(
        self,
        intent_confidence: float,
        entities: List[ExtractedEntity],
        constraints: List[QueryConstraint]
    ) -> float:
        """Calculate overall parse confidence"""
        # Weighted average of component confidences
        weights = {
            'intent': 0.3,
            'entities': 0.5,
            'constraints': 0.2
        }
        
        # Calculate entity confidence
        entity_confidence = 0.5  # Default if no entities
        if entities:
            entity_confidence = sum(e.confidence for e in entities) / len(entities)
        
        # Calculate constraint confidence
        constraint_confidence = 0.7  # Default if no constraints
        if constraints:
            constraint_confidence = sum(c.confidence for c in constraints) / len(constraints)
        
        overall = (
            weights['intent'] * intent_confidence +
            weights['entities'] * entity_confidence +
            weights['constraints'] * constraint_confidence
        )
        
        return min(1.0, overall)
