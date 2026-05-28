#!/usr/bin/env python
"""
Integration test demonstrating the complete parameter validation system.
Run this to verify all components work together.
"""

import json
import tempfile
from pathlib import Path

from brain_researcher.services.agent.parameter_validation import (
    ParameterValidator,
    ParameterDatabase,
)
from brain_researcher.services.agent.utils.api_discovery import APIDiscovery
from brain_researcher.services.agent.utils.domain_knowledge import (
    DomainKnowledgeEngine,
    ParameterCategory,
)


def test_parameter_validation_system():
    """Test the complete parameter validation system."""
    print("=" * 60)
    print("Testing Parameter Validation System")
    print("=" * 60)
    
    # 1. Test ParameterValidator
    print("\n1. Testing ParameterValidator:")
    validator = ParameterValidator()
    
    # Validate FSL parameters
    fsl_params = {
        "smooth": 6.0,
        "thresh": 3.1,
        "tr": 2.0
    }
    validated = validator.validate_parameters("fsl.feat", fsl_params)
    print(f"   ✓ Validated FSL params: {validated}")
    
    # Validate with context
    context = {"task": "group_analysis", "modality": "fmri"}
    validated_with_context = validator.validate_parameters(
        "fsl", {"smoothing_fwhm": 4.0}, context=context
    )
    print(f"   ✓ Validated with context: {validated_with_context}")
    
    # 2. Test ParameterDatabase
    print("\n2. Testing ParameterDatabase:")
    with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
        db_file = f.name
    
    db = ParameterDatabase(db_file)
    
    # Add parameters
    db.update_tool_params("test_tool", {
        "param1": {"type": "float", "range": [0, 10]},
        "param2": {"type": "integer", "range": [1, 100]}
    })
    
    # Retrieve parameters
    params = db.get_tool_params("test_tool")
    print(f"   ✓ Stored and retrieved params: {params['parameters'].keys()}")
    
    # Clean up
    Path(db_file).unlink()
    
    # 3. Test DomainKnowledgeEngine
    print("\n3. Testing DomainKnowledgeEngine:")
    engine = DomainKnowledgeEngine()
    
    # Get parameter knowledge
    knowledge = engine.get_parameter_knowledge("smoothing_fwhm")
    if knowledge:
        print(f"   ✓ Got knowledge for smoothing_fwhm:")
        print(f"     - Category: {knowledge.category}")
        print(f"     - Typical range: {knowledge.typical_range}")
        print(f"     - Recommended range: {knowledge.recommended_range}")
        print(f"     - Units: {knowledge.units}")
    
    # Get best practices
    practices = engine.get_best_practices("smoothing_fwhm")
    print(f"   ✓ Got {len(practices)} best practices")
    if practices:
        print(f"     - Example: {practices[0]}")
    
    # Suggest parameters based on context
    suggestions = engine.suggest_parameters({
        "task": "preprocessing",
        "modality": "fmri"
    })
    print(f"   ✓ Got {len(suggestions)} parameter suggestions for preprocessing")
    
    # Get equivalent parameters
    equiv = engine.get_equivalent_parameters("smoothing_fwhm", "generic", "fsl")
    print(f"   ✓ Equivalent parameter in FSL: {equiv}")
    
    # 4. Test APIDiscovery
    print("\n4. Testing APIDiscovery:")
    discovery = APIDiscovery()
    
    # Test CLI help parsing
    help_text = """
    -f <val>    Fractional intensity threshold (0->1); default=0.5
    -g <val>    Vertical gradient (-1->1); default=0
    """
    parsed = discovery._parse_cli_help(help_text)
    print(f"   ✓ Parsed CLI help: {list(parsed.keys())}")
    
    # Test range extraction
    desc = "Smoothing kernel size between 0 and 20 mm"
    range_vals = discovery._extract_range_from_description(desc)
    print(f"   ✓ Extracted range from description: {range_vals}")
    
    # 5. Test Integration
    print("\n5. Testing Full Integration:")
    
    # Create a complete validation workflow
    validator = ParameterValidator()
    
    # Define parameters for a neuroimaging pipeline
    pipeline_params = {
        # Preprocessing
        "smooth": 6.0,
        "thresh": 3.1,
        "tr": 2.0,
        # Registration
        "cost": "corratio",
        "dof": 12,
        # Analysis
        "iterations": 1000
    }
    
    # Validate all parameters
    validated = validator.validate_parameters("fsl", pipeline_params)
    print(f"   ✓ Validated complete pipeline with {len(validated)} parameters")
    
    # Get tool parameters schemas
    schemas = validator.get_tool_parameters("fsl")
    print(f"   ✓ Retrieved {len(schemas)} parameter schemas")
    
    # Get suggestions for failed parameters
    suggestions = validator.get_parameter_suggestions("fsl", {"smooth": -5})
    print(f"   ✓ Got {len(suggestions)} suggestions for fixing invalid params")
    
    print("\n" + "=" * 60)
    print("✅ All tests passed successfully!")
    print("=" * 60)
    
    return True


def test_neurodesk_integration():
    """Test Neurodesk-specific functionality."""
    print("\n" + "=" * 60)
    print("Testing Neurodesk Integration")
    print("=" * 60)
    
    validator = ParameterValidator()
    
    # Test FSL BET parameters
    bet_params = {
        "f": 0.5,  # Fractional intensity
        "g": 0,    # Gradient
        "r": 45    # Radius
    }
    
    print("\n1. FSL BET validation:")
    validated = validator.validate_parameters("fsl.bet", bet_params)
    print(f"   ✓ Validated BET params: {validated}")
    
    # Test FreeSurfer parameters
    fs_params = {
        "parallel": True,
        "openmp": 4,
        "hires": False
    }
    
    print("\n2. FreeSurfer validation:")
    validated = validator.validate_parameters("freesurfer.recon-all", fs_params)
    print(f"   ✓ Validated FreeSurfer params: {validated}")
    
    # Test ANTs parameters
    ants_params = {
        "dimensionality": 3,
        "metric": "MI",
        "convergence": "[1000x500x250x100,1e-6,10]"
    }
    
    print("\n3. ANTs validation:")
    validated = validator.validate_parameters("ants.Registration", ants_params)
    print(f"   ✓ Validated ANTs params: {validated}")
    
    print("\n✅ Neurodesk integration tests passed!")
    
    return True


def main():
    """Run all integration tests."""
    try:
        # Run main validation tests
        test_parameter_validation_system()
        
        # Run Neurodesk tests
        test_neurodesk_integration()
        
        print("\n🎉 All integration tests completed successfully!")
        return 0
        
    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit(main())