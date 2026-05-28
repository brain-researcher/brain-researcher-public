"""
Unit tests for genetics and genomics analysis tools.
"""

import pytest
import numpy as np
import json
from pathlib import Path
import tempfile
import shutil

# Genetics/genomics tools are optional; skip cleanly if the module or required
# classes are absent in this environment instead of failing collection.
genetics_mod = pytest.importorskip(
    "brain_researcher.services.tools.genetics_genomics_tools",
    reason="genetics/genomics tools not available in this environment",
)

_required = {
    "GeneticsGenomicsTools",
    "GWASAnalysisTool",
    "PolygeneticRiskScoreTool",
    "GeneExpressionMappingTool",
    "HeritabilityAnalysisTool",
    "GeneBrainNetworkTool",
    "EpigeneticsTool",
    "PharmacogeneticsTool",
}
missing = [name for name in _required if not hasattr(genetics_mod, name)]
if missing:
    pytest.skip(
        f"genetics/genomics tools missing: {', '.join(missing)}",
        allow_module_level=True,
    )

GeneticsGenomicsTools = genetics_mod.GeneticsGenomicsTools
GWASAnalysisTool = genetics_mod.GWASAnalysisTool
ImagingGeneticsTool = getattr(genetics_mod, "ImagingGeneticsTool", None)
PolygeneticRiskScoreTool = genetics_mod.PolygeneticRiskScoreTool
GeneExpressionMappingTool = genetics_mod.GeneExpressionMappingTool
HeritabilityAnalysisTool = genetics_mod.HeritabilityAnalysisTool
GeneBrainNetworkTool = genetics_mod.GeneBrainNetworkTool
EpigeneticsTool = genetics_mod.EpigeneticsTool
PharmacogeneticsTool = genetics_mod.PharmacogeneticsTool


class TestGeneticsToolsCollection:
    """Test the genetics tools collection."""
    
    def test_collection_initialization(self):
        """Test that the collection initializes properly."""
        tools = GeneticsGenomicsTools()
        assert tools is not None
    
    def test_get_all_tools(self):
        """Test that all 8 tools are returned."""
        tools = GeneticsGenomicsTools()
        all_tools = tools.get_all_tools()
        
        assert len(all_tools) == 8
        assert isinstance(all_tools[0], GWASAnalysisTool)
        assert isinstance(all_tools[1], ImagingGeneticsTool)
        assert isinstance(all_tools[2], PolygeneticRiskScoreTool)
        assert isinstance(all_tools[3], GeneExpressionMappingTool)
        assert isinstance(all_tools[4], HeritabilityAnalysisTool)
        assert isinstance(all_tools[5], GeneBrainNetworkTool)
        assert isinstance(all_tools[6], EpigeneticsTool)
        assert isinstance(all_tools[7], PharmacogeneticsTool)


class TestGWASAnalysisTool:
    """Test GWAS analysis tool."""
    
    @pytest.fixture
    def tool(self):
        """Create tool instance."""
        return GWASAnalysisTool()
    
    @pytest.fixture
    def temp_dir(self):
        """Create temporary directory for outputs."""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir)
    
    def test_initialization(self, tool):
        """Test tool initialization."""
        assert tool.get_tool_name() == "gwas_analysis"
        assert "GWAS" in tool.get_tool_description()
        assert tool.get_args_schema() is not None
    
    def test_synthetic_data_generation(self, tool, temp_dir):
        """Test GWAS with synthetic data."""
        result = tool._run(
            genotype_file=None,  # Use synthetic data
            phenotype_file=None,
            covariates=["age", "sex"],
            model="additive",
            maf_threshold=0.01,
            significance_threshold=5e-8,
            output_dir=temp_dir
        )
        
        assert result.status == "success"
        assert "n_snps" in result.data
        assert "n_samples" in result.data
        assert "lambda_gc" in result.data
        assert "top_snps" in result.data
        assert len(result.data["top_snps"]) <= 10
        
        # Check output files
        output_path = Path(temp_dir)
        assert (output_path / "gwas_summary.csv").exists()
        assert (output_path / "manhattan.json").exists()
        assert (output_path / "qq_plot.json").exists()
    
    def test_maf_filtering(self, tool):
        """Test MAF filtering works correctly."""
        # Generate test genotypes
        n_samples = 100
        n_snps = 10
        genotypes = np.zeros((n_samples, n_snps))
        
        # Set MAF for each SNP
        # SNP 0: MAF = 0.005 (should be filtered)
        genotypes[:, 0] = np.random.choice([0, 1, 2], n_samples, p=[0.99, 0.01, 0])
        
        # SNP 1: MAF = 0.25 (should pass)
        genotypes[:, 1] = np.random.choice([0, 1, 2], n_samples, p=[0.5625, 0.375, 0.0625])
        
        maf = tool._calculate_maf(genotypes)
        
        assert maf[0] < 0.01  # First SNP has low MAF
        assert maf[1] > 0.2   # Second SNP has reasonable MAF
    
    def test_error_handling(self, tool):
        """Test error handling with invalid parameters."""
        result = tool._run(
            genotype_file="/nonexistent/file.bed",
            phenotype_file="/nonexistent/pheno.txt"
        )
        
        # Should handle gracefully by using synthetic data
        assert result.status in ["success", "error"]


class TestImagingGeneticsTool:
    """Test imaging genetics analysis tool."""
    
    @pytest.fixture
    def tool(self):
        return ImagingGeneticsTool()
    
    @pytest.fixture
    def temp_dir(self):
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir)
    
    def test_initialization(self, tool):
        """Test tool initialization."""
        assert tool.get_tool_name() == "imaging_genetics"
        assert "brain imaging" in tool.get_tool_description().lower()
    
    def test_univariate_analysis(self, tool, temp_dir):
        """Test univariate imaging genetics analysis."""
        result = tool._run(
            genotype_file=None,
            imaging_features=None,
            method="univariate",
            output_dir=temp_dir
        )
        
        assert result.status == "success"
        assert "n_genetic_features" in result.data
        assert "n_imaging_features" in result.data
        assert "n_significant_associations" in result.data
        assert result.data["method"] == "univariate"
    
    def test_multivariate_analysis(self, tool, temp_dir):
        """Test multivariate analysis (CCA)."""
        result = tool._run(
            genotype_file=None,
            imaging_features=None,
            method="multivariate",
            output_dir=temp_dir
        )
        
        assert result.status == "success"
        assert result.data["method"] == "multivariate"
    
    def test_pls_analysis(self, tool, temp_dir):
        """Test PLS analysis."""
        result = tool._run(
            genotype_file=None,
            imaging_features=None,
            method="pls",
            output_dir=temp_dir
        )
        
        assert result.status == "success"
        assert result.data["method"] == "pls"


class TestPolygeneticRiskScoreTool:
    """Test PRS calculation tool."""
    
    @pytest.fixture
    def tool(self):
        return PolygeneticRiskScoreTool()
    
    @pytest.fixture
    def temp_dir(self):
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir)
    
    def test_initialization(self, tool):
        """Test tool initialization."""
        assert tool.get_tool_name() == "polygenic_risk_score"
        assert "PRS" in tool.get_tool_description()
    
    def test_prs_calculation(self, tool, temp_dir):
        """Test PRS calculation with p-value thresholding."""
        result = tool._run(
            summary_stats=None,
            target_genotypes=None,
            p_threshold=0.05,
            method="p_value",
            trait="alzheimer",
            output_dir=temp_dir
        )
        
        assert result.status == "success"
        assert "n_individuals" in result.data
        assert "mean_prs" in result.data
        assert "std_prs" in result.data
        assert "risk_distribution" in result.data
        
        # Check risk categories
        risk_dist = result.data["risk_distribution"]
        assert "low" in risk_dist
        assert "medium" in risk_dist
        assert "high" in risk_dist
        assert risk_dist["low"] + risk_dist["medium"] + risk_dist["high"] == result.data["n_individuals"]
    
    def test_risk_categorization(self, tool):
        """Test risk categorization logic."""
        # Test standardized PRS values
        prs_standardized = np.array([-2, -0.5, 0, 0.5, 1.5])
        categories = tool._categorize_risk(prs_standardized)
        
        assert categories[0] == "low"    # -2 < -1
        assert categories[1] == "medium"  # -1 <= -0.5 <= 1
        assert categories[2] == "medium"  # -1 <= 0 <= 1
        assert categories[3] == "medium"  # -1 <= 0.5 <= 1
        assert categories[4] == "high"    # 1.5 > 1


class TestGeneExpressionMappingTool:
    """Test gene expression mapping tool."""
    
    @pytest.fixture
    def tool(self):
        return GeneExpressionMappingTool()
    
    @pytest.fixture
    def temp_dir(self):
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir)
    
    def test_initialization(self, tool):
        """Test tool initialization."""
        assert tool.get_tool_name() == "gene_expression_mapping"
        assert "Allen Brain Atlas" in tool.get_tool_description()
    
    def test_expression_mapping(self, tool, temp_dir):
        """Test gene expression mapping."""
        result = tool._run(
            gene_list=None,
            brain_regions=None,
            expression_data=None,
            correlation_threshold=0.5,
            output_dir=temp_dir
        )
        
        assert result.status == "success"
        assert "n_genes" in result.data
        assert "n_regions" in result.data
        assert "n_modules" in result.data
        assert "top_expressed_genes" in result.data
        assert "enriched_regions" in result.data
    
    def test_coexpression_modules(self, tool):
        """Test co-expression module detection."""
        # Create test expression matrix with clear modules
        n_genes = 20
        n_regions = 10
        expression = np.random.randn(n_genes, n_regions)
        
        # Create two modules with high correlation
        # Module 1: genes 0-4
        common_signal1 = np.random.randn(n_regions)
        for i in range(5):
            expression[i, :] = common_signal1 + np.random.randn(n_regions) * 0.1
        
        # Module 2: genes 5-9
        common_signal2 = np.random.randn(n_regions)
        for i in range(5, 10):
            expression[i, :] = common_signal2 + np.random.randn(n_regions) * 0.1
        
        modules = tool._find_coexpression_modules(expression, threshold=0.7)
        
        assert len(modules) >= 1  # Should find at least one module


class TestHeritabilityAnalysisTool:
    """Test heritability analysis tool."""
    
    @pytest.fixture
    def tool(self):
        return HeritabilityAnalysisTool()
    
    @pytest.fixture
    def temp_dir(self):
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir)
    
    def test_initialization(self, tool):
        """Test tool initialization."""
        assert tool.get_tool_name() == "heritability_analysis"
        assert "twin" in tool.get_tool_description().lower()
    
    def test_ace_model(self, tool, temp_dir):
        """Test ACE model for twin studies."""
        result = tool._run(
            phenotype_data=None,
            kinship_matrix=None,
            study_type="twin",
            method="ace",
            output_dir=temp_dir
        )
        
        assert result.status == "success"
        assert "heritability" in result.data
        assert 0 <= result.data["heritability"] <= 1
        assert "confidence_interval" in result.data
        assert "variance_components" in result.data
        
        # Check variance components for ACE model
        var_comp = result.data["variance_components"]
        assert "additive_genetic" in var_comp or "genetic" in var_comp
    
    def test_heritability_bounds(self, tool):
        """Test that heritability estimates are bounded [0, 1]."""
        # Test with edge cases
        n_individuals = 100
        
        # All individuals have same phenotype (h2 should be ~0)
        phenotypes = np.ones(n_individuals)
        kinship = np.eye(n_individuals) * 0.5
        
        h2_estimate = tool._simple_heritability(phenotypes, kinship)
        assert 0 <= h2_estimate["h2"] <= 1


class TestGeneBrainNetworkTool:
    """Test gene-brain network analysis tool."""
    
    @pytest.fixture
    def tool(self):
        return GeneBrainNetworkTool()
    
    @pytest.fixture
    def temp_dir(self):
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir)
    
    def test_initialization(self, tool):
        """Test tool initialization."""
        assert tool.get_tool_name() == "gene_brain_network"
        assert "co-expression" in tool.get_tool_description().lower()
    
    def test_network_construction(self, tool, temp_dir):
        """Test network construction."""
        result = tool._run(
            expression_data=None,
            gene_list=None,
            network_method="correlation",
            module_detection=True,
            output_dir=temp_dir
        )
        
        assert result.status == "success"
        assert "n_genes" in result.data
        assert "n_edges" in result.data
        assert "network_density" in result.data
        assert "hub_genes" in result.data
        assert len(result.data["hub_genes"]) <= 10
    
    def test_network_metrics(self, tool):
        """Test network metric calculations."""
        # Create simple test network
        network = np.array([
            [0, 1, 1, 0],
            [1, 0, 1, 1],
            [1, 1, 0, 1],
            [0, 1, 1, 0]
        ])
        
        metrics = tool._calculate_network_metrics(network)
        
        assert "n_nodes" in metrics
        assert metrics["n_nodes"] == 4
        assert "n_edges" in metrics
        assert metrics["n_edges"] == 5  # Edges: (0,1), (0,2), (1,2), (1,3), (2,3)
        assert "density" in metrics
        assert 0 <= metrics["density"] <= 1
        assert "mean_degree" in metrics
        assert "clustering_coefficient" in metrics


class TestEpigeneticsTool:
    """Test epigenetics analysis tool."""
    
    @pytest.fixture
    def tool(self):
        return EpigeneticsTool()
    
    @pytest.fixture
    def temp_dir(self):
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir)
    
    def test_initialization(self, tool):
        """Test tool initialization."""
        assert tool.get_tool_name() == "epigenetics_analysis"
        assert "methylation" in tool.get_tool_description().lower()
    
    def test_differential_methylation(self, tool, temp_dir):
        """Test differential methylation analysis."""
        result = tool._run(
            methylation_data=None,
            sample_groups=None,
            cpg_sites=None,
            analysis_type="differential",
            output_dir=temp_dir
        )
        
        assert result.status == "success"
        assert "n_samples" in result.data
        assert "n_cpg_sites" in result.data
        assert "n_significant_sites" in result.data
    
    def test_age_prediction(self, tool, temp_dir):
        """Test epigenetic age prediction."""
        result = tool._run(
            methylation_data=None,
            analysis_type="age_prediction",
            output_dir=temp_dir
        )
        
        assert result.status == "success"
        assert result.data["analysis_type"] == "age_prediction"
    
    def test_methylation_values(self, tool):
        """Test that methylation values are properly bounded [0, 1]."""
        methylation, _, _ = tool._generate_synthetic_methylation()
        
        assert methylation.min() >= 0
        assert methylation.max() <= 1
        assert methylation.shape[0] == 100  # n_samples
        assert methylation.shape[1] == 1000  # n_cpgs


class TestPharmacogeneticsTool:
    """Test pharmacogenetics analysis tool."""
    
    @pytest.fixture
    def tool(self):
        return PharmacogeneticsTool()
    
    @pytest.fixture
    def temp_dir(self):
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir)
    
    def test_initialization(self, tool):
        """Test tool initialization."""
        assert tool.get_tool_name() == "pharmacogenetics"
        assert "drug response" in tool.get_tool_description().lower()
    
    def test_dosing_recommendations(self, tool, temp_dir):
        """Test dosing recommendations."""
        result = tool._run(
            genotype_data=None,
            drug_list=None,
            variant_list=None,
            analysis_type="dosing",
            output_dir=temp_dir
        )
        
        assert result.status == "success"
        assert "n_individuals" in result.data
        assert "n_variants" in result.data
        assert "n_drugs" in result.data
        assert "recommendations" in result.data
        assert len(result.data["recommendations"]) <= 5
    
    def test_efficacy_prediction(self, tool, temp_dir):
        """Test drug efficacy prediction."""
        result = tool._run(
            genotype_data=None,
            analysis_type="efficacy",
            output_dir=temp_dir
        )
        
        assert result.status == "success"
        assert result.data["analysis_type"] == "efficacy"
    
    def test_adverse_event_risk(self, tool, temp_dir):
        """Test adverse event risk assessment."""
        result = tool._run(
            genotype_data=None,
            analysis_type="adverse_events",
            output_dir=temp_dir
        )
        
        assert result.status == "success"
        assert result.data["analysis_type"] == "adverse_events"
    
    def test_drug_recommendations(self, tool):
        """Test that recommendations are generated properly."""
        # Generate test data
        genotypes, variants, drugs = tool._generate_synthetic_pharmaco_data()
        
        # Get dosing recommendations
        results = tool._dosing_recommendations(genotypes, variants, drugs)
        
        assert len(results) == len(drugs)
        for drug in drugs:
            assert drug in results
            assert len(results[drug]) == len(genotypes)
            
            # Check that each individual has a recommendation
            for rec in results[drug]:
                assert "dose_adjustment" in rec
                assert "phenotype" in rec
                assert 0 <= rec["dose_adjustment"] <= 1.0


class TestIntegration:
    """Integration tests for genetics tools."""
    
    def test_registry_integration(self):
        """Test that genetics tools register properly."""
        from brain_researcher.services.tools.tool_registry import ToolRegistry
        
        registry = ToolRegistry()
        
        # Check that all genetics tools are registered
        tool_names = [
            "gwas_analysis",
            "imaging_genetics",
            "polygenic_risk_score",
            "gene_expression_mapping",
            "heritability_analysis",
            "gene_brain_network",
            "epigenetics_analysis",
            "pharmacogenetics"
        ]
        
        for name in tool_names:
            tool = registry.get_tool(name)
            assert tool is not None
            assert tool.get_tool_name() == name
    
    def test_tool_chain(self):
        """Test chaining multiple genetics tools."""
        # Run GWAS
        gwas_tool = GWASAnalysisTool()
        gwas_result = gwas_tool._run()
        assert gwas_result.status == "success"
        
        # Use GWAS results for PRS
        prs_tool = PolygeneticRiskScoreTool()
        prs_result = prs_tool._run()
        assert prs_result.status == "success"
        
        # Both should work independently with synthetic data
        assert gwas_result.data["n_snps"] > 0
        assert prs_result.data["n_individuals"] > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
