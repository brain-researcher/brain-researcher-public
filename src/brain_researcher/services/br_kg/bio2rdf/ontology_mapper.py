"""
Ontology Mapping between BR-KG and Bio2RDF

Maps neuroimaging concepts to Bio2RDF ontologies and namespaces.
"""

import logging
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class OntologyNamespace(str, Enum):
    """Bio2RDF ontology namespaces"""

    # Anatomical ontologies
    MESH = "mesh"  # Medical Subject Headings
    UBERON = "uberon"  # Uber-anatomy ontology
    FMA = "fma"  # Foundational Model of Anatomy

    # Gene/Protein ontologies
    GO = "go"  # Gene Ontology
    UNIPROT = "uniprot"  # UniProt proteins
    HGNC = "hgnc"  # HUGO Gene Nomenclature

    # Drug/Chemical ontologies
    DRUGBANK = "drugbank"  # Drug database
    CHEMBL = "chembl"  # Chemical database
    CHEBI = "chebi"  # Chemical Entities of Biological Interest

    # Pathway ontologies
    KEGG = "kegg"  # Kyoto Encyclopedia of Genes and Genomes
    REACTOME = "reactome"  # Biological pathways

    # Disease ontologies
    OMIM = "omim"  # Online Mendelian Inheritance in Man
    DOID = "doid"  # Disease Ontology

    # Literature
    PUBMED = "pubmed"  # PubMed citations


@dataclass
class ConceptMapping:
    """Mapping between BR-KG concept and Bio2RDF entity"""

    br_kg_id: str
    br_kg_label: str
    br_kg_type: str
    bio2rdf_uri: str
    bio2rdf_namespace: OntologyNamespace
    bio2rdf_label: str
    confidence_score: float
    mapping_type: str  # 'exact', 'narrow', 'broad', 'related'


class OntologyMapper:
    """
    Maps between BR-KG neuroimaging concepts and Bio2RDF biological ontologies
    """

    # Brain region mappings to MeSH/UBERON
    BRAIN_REGION_MAPPINGS = {
        "hippocampus": [
            ("mesh:D006624", "Hippocampus", "exact"),
            ("uberon:0001954", "hippocampus proper", "exact"),
            ("go:0021766", "hippocampus development", "related"),
        ],
        "amygdala": [
            ("mesh:D000679", "Amygdala", "exact"),
            ("uberon:0001876", "amygdala", "exact"),
            ("go:0021764", "amygdala development", "related"),
        ],
        "prefrontal_cortex": [
            ("mesh:D017397", "Prefrontal Cortex", "exact"),
            ("uberon:0000451", "prefrontal cortex", "exact"),
            ("go:0021769", "prefrontal cortex development", "related"),
        ],
        "motor_cortex": [
            ("mesh:D009044", "Motor Cortex", "exact"),
            ("uberon:0001384", "primary motor cortex", "narrow"),
            ("go:0021767", "motor cortex development", "related"),
        ],
        "visual_cortex": [
            ("mesh:D014793", "Visual Cortex", "exact"),
            ("uberon:0000411", "visual cortex", "exact"),
            ("go:0021768", "visual cortex development", "related"),
        ],
        "thalamus": [
            ("mesh:D013788", "Thalamus", "exact"),
            ("uberon:0000124", "thalamus", "exact"),
            ("go:0021761", "thalamus development", "related"),
        ],
        "cerebellum": [
            ("mesh:D002531", "Cerebellum", "exact"),
            ("uberon:0002037", "cerebellum", "exact"),
            ("go:0021549", "cerebellum development", "related"),
        ],
    }

    # Cognitive task mappings to GO biological processes
    COGNITIVE_TASK_MAPPINGS = {
        "working_memory": [
            ("go:0008306", "associative learning", "broad"),
            ("go:0007613", "memory", "broad"),
            ("go:0050890", "cognition", "broad"),
        ],
        "attention": [
            ("go:0007611", "learning or memory", "broad"),
            ("go:0050890", "cognition", "broad"),
            ("mesh:D001288", "Attention", "exact"),
        ],
        "emotion": [
            ("go:0007610", "behavior", "broad"),
            ("go:0032318", "regulation of stress response", "related"),
            ("mesh:D004644", "Emotions", "exact"),
        ],
        "language": [
            ("go:0007608", "sensory perception of sound", "related"),
            ("go:0050890", "cognition", "broad"),
            ("mesh:D007802", "Language", "exact"),
        ],
        "decision_making": [
            ("go:0050890", "cognition", "broad"),
            ("go:0007610", "behavior", "broad"),
            ("mesh:D003657", "Decision Making", "exact"),
        ],
        "reward_processing": [
            ("go:0035094", "response to drug", "related"),
            ("go:0048148", "behavioral response to drug", "related"),
            ("mesh:D012201", "Reward", "exact"),
        ],
    }

    # Neurotransmitter/neurochemical mappings
    NEUROCHEMICAL_MAPPINGS = {
        "dopamine": [
            ("drugbank:DB00988", "Dopamine", "exact"),
            ("chebi:18243", "dopamine", "exact"),
            ("mesh:D004298", "Dopamine", "exact"),
        ],
        "serotonin": [
            ("drugbank:DB08839", "Serotonin", "exact"),
            ("chebi:28790", "serotonin", "exact"),
            ("mesh:D012701", "Serotonin", "exact"),
        ],
        "glutamate": [
            ("drugbank:DB00142", "Glutamic acid", "exact"),
            ("chebi:16015", "L-glutamate", "exact"),
            ("mesh:D018698", "Glutamic Acid", "exact"),
        ],
        "gaba": [
            ("drugbank:DB02530", "Gamma-Aminobutyric acid", "exact"),
            ("chebi:16865", "gamma-aminobutyric acid", "exact"),
            ("mesh:D005680", "gamma-Aminobutyric Acid", "exact"),
        ],
        "acetylcholine": [
            ("drugbank:DB03128", "Acetylcholine", "exact"),
            ("chebi:15355", "acetylcholine", "exact"),
            ("mesh:D000109", "Acetylcholine", "exact"),
        ],
    }

    # Disease/disorder mappings
    DISORDER_MAPPINGS = {
        "alzheimer": [
            ("mesh:D000544", "Alzheimer Disease", "exact"),
            ("doid:10652", "Alzheimer disease", "exact"),
            ("omim:104300", "Alzheimer Disease", "exact"),
        ],
        "parkinson": [
            ("mesh:D010300", "Parkinson Disease", "exact"),
            ("doid:14330", "Parkinson disease", "exact"),
            ("omim:168600", "Parkinson Disease", "exact"),
        ],
        "schizophrenia": [
            ("mesh:D012559", "Schizophrenia", "exact"),
            ("doid:5419", "schizophrenia", "exact"),
            ("omim:181500", "Schizophrenia", "exact"),
        ],
        "depression": [
            ("mesh:D003866", "Depressive Disorder", "exact"),
            ("doid:1596", "major depressive disorder", "narrow"),
            ("omim:608516", "Major Depressive Disorder", "narrow"),
        ],
        "autism": [
            ("mesh:D000067877", "Autism Spectrum Disorder", "exact"),
            ("doid:0060041", "autism spectrum disorder", "exact"),
            ("omim:209850", "Autism", "exact"),
        ],
    }

    def __init__(self):
        """Initialize the ontology mapper"""
        self._mapping_cache = {}
        self._initialize_mappings()

    def _initialize_mappings(self):
        """Initialize the mapping tables"""
        # Combine all mappings into a single lookup
        self.all_mappings = {
            "brain_region": self.BRAIN_REGION_MAPPINGS,
            "cognitive_task": self.COGNITIVE_TASK_MAPPINGS,
            "neurochemical": self.NEUROCHEMICAL_MAPPINGS,
            "disorder": self.DISORDER_MAPPINGS,
        }

    def map_concept(
        self, concept: str, concept_type: str, fuzzy: bool = True
    ) -> list[ConceptMapping]:
        """
        Map a BR-KG concept to Bio2RDF entities

        Args:
            concept: The concept to map
            concept_type: Type of concept ('brain_region', 'cognitive_task', etc.)
            fuzzy: Whether to use fuzzy matching

        Returns:
            List of potential mappings
        """
        cache_key = f"{concept}:{concept_type}"
        if cache_key in self._mapping_cache:
            return self._mapping_cache[cache_key]

        mappings = []
        concept_lower = concept.lower().replace(" ", "_").replace("-", "_")

        # Get exact matches first
        if concept_type in self.all_mappings:
            mapping_dict = self.all_mappings[concept_type]

            if concept_lower in mapping_dict:
                for bio2rdf_uri, bio2rdf_label, mapping_type in mapping_dict[
                    concept_lower
                ]:
                    namespace = self._extract_namespace(bio2rdf_uri)
                    mappings.append(
                        ConceptMapping(
                            br_kg_id=f"br_kg:{concept_lower}",
                            br_kg_label=concept,
                            br_kg_type=concept_type,
                            bio2rdf_uri=bio2rdf_uri,
                            bio2rdf_namespace=namespace,
                            bio2rdf_label=bio2rdf_label,
                            confidence_score=1.0 if mapping_type == "exact" else 0.8,
                            mapping_type=mapping_type,
                        )
                    )

            # Try fuzzy matching if enabled
            elif fuzzy:
                for key, values in mapping_dict.items():
                    similarity = self._string_similarity(concept_lower, key)
                    if similarity > 0.7:  # Threshold for fuzzy match
                        for bio2rdf_uri, bio2rdf_label, mapping_type in values:
                            namespace = self._extract_namespace(bio2rdf_uri)
                            mappings.append(
                                ConceptMapping(
                                    br_kg_id=f"br_kg:{concept_lower}",
                                    br_kg_label=concept,
                                    br_kg_type=concept_type,
                                    bio2rdf_uri=bio2rdf_uri,
                                    bio2rdf_namespace=namespace,
                                    bio2rdf_label=bio2rdf_label,
                                    confidence_score=similarity * 0.8,
                                    mapping_type="related",
                                )
                            )

        self._mapping_cache[cache_key] = mappings
        return mappings

    def _extract_namespace(self, uri: str) -> OntologyNamespace:
        """Extract namespace from Bio2RDF URI"""
        for namespace in OntologyNamespace:
            if namespace.value + ":" in uri.lower():
                return namespace
        return OntologyNamespace.MESH  # Default

    def _string_similarity(self, s1: str, s2: str) -> float:
        """Calculate string similarity using Levenshtein distance"""
        if s1 == s2:
            return 1.0

        # Simple character-based similarity
        s1_set = set(s1)
        s2_set = set(s2)
        intersection = s1_set.intersection(s2_set)
        union = s1_set.union(s2_set)

        if not union:
            return 0.0

        return len(intersection) / len(union)

    def get_namespace_prefix(self, namespace: OntologyNamespace) -> str:
        """Get the Bio2RDF URI prefix for a namespace"""
        prefixes = {
            OntologyNamespace.MESH: "http://bio2rdf.org/mesh:",
            OntologyNamespace.UBERON: "http://bio2rdf.org/uberon:",
            OntologyNamespace.GO: "http://bio2rdf.org/go:",
            OntologyNamespace.DRUGBANK: "http://bio2rdf.org/drugbank:",
            OntologyNamespace.CHEMBL: "http://bio2rdf.org/chembl:",
            OntologyNamespace.KEGG: "http://bio2rdf.org/kegg:",
            OntologyNamespace.PUBMED: "http://bio2rdf.org/pubmed:",
            OntologyNamespace.UNIPROT: "http://bio2rdf.org/uniprot:",
            OntologyNamespace.CHEBI: "http://bio2rdf.org/chebi:",
            OntologyNamespace.REACTOME: "http://bio2rdf.org/reactome:",
            OntologyNamespace.OMIM: "http://bio2rdf.org/omim:",
            OntologyNamespace.DOID: "http://bio2rdf.org/doid:",
        }
        return prefixes.get(namespace, "http://bio2rdf.org/")

    def generate_mapping_sparql(self, mappings: list[ConceptMapping]) -> str:
        """
        Generate SPARQL query to link BR-KG and Bio2RDF entities

        Args:
            mappings: List of concept mappings

        Returns:
            SPARQL CONSTRUCT query for creating links
        """
        if not mappings:
            return ""

        # Generate SPARQL CONSTRUCT query
        construct_patterns = []
        where_patterns = []

        for mapping in mappings:
            br_kg_uri = f"<{mapping.br_kg_id}>"
            bio2rdf_uri = f"<{mapping.bio2rdf_uri}>"

            construct_patterns.append(f"{br_kg_uri} owl:sameAs {bio2rdf_uri} .")
            construct_patterns.append(f"{br_kg_uri} skos:exactMatch {bio2rdf_uri} .")

            where_patterns.append(
                f"OPTIONAL {{ {bio2rdf_uri} rdfs:label ?label_{mapping.bio2rdf_namespace.value} }}"
            )

        query = f"""
        PREFIX owl: <http://www.w3.org/2002/07/owl#>
        PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

        CONSTRUCT {{
            {' '.join(construct_patterns)}
        }}
        WHERE {{
            {' '.join(where_patterns)}
        }}
        """

        return query


def create_ontology_mapper() -> OntologyMapper:
    """Factory function to create ontology mapper"""
    return OntologyMapper()
