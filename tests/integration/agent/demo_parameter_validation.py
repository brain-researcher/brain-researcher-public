#!/usr/bin/env python
"""
Demo script showing parameter validation system capabilities.
"""

from brain_researcher.services.agent.parameter_validation import ParameterValidator
from brain_researcher.services.agent.utils.domain_knowledge import DomainKnowledgeEngine


def main():
    print("\n" + "="*70)
    print("PARAMETER VALIDATION SYSTEM DEMONSTRATION")
    print("="*70)
    
    # Initialize components
    validator = ParameterValidator()
    domain_engine = DomainKnowledgeEngine()
    
    # Example 1: Basic FSL validation
    print("\n📊 Example 1: Basic FSL Parameter Validation")
    print("-" * 50)
    
    fsl_params = {
        "smooth": 6.0,
        "thresh": 3.1,
        "tr": 2.0,
        "paradigm_hp": 100
    }
    
    print(f"Input parameters: {fsl_params}")
    validated = validator.validate_parameters("fsl.feat", fsl_params)
    print(f"Validated parameters: {validated}")
    
    # Example 2: Context-aware validation
    print("\n🧠 Example 2: Context-Aware Parameter Suggestions")
    print("-" * 50)
    
    context = {
        "task": "group_analysis",
        "modality": "fmri",
        "first_time": True
    }
    
    print(f"Context: {context}")
    suggestions = domain_engine.suggest_parameters(context)
    print(f"Suggested parameters: {list(suggestions.keys())[:5]}...")  # Show first 5
    
    # Example 3: Cross-tool parameter mapping
    print("\n🔄 Example 3: Cross-Tool Parameter Mapping")
    print("-" * 50)
    
    tools = ["fsl", "spm", "nilearn", "afni"]
    param = "smoothing_fwhm"
    
    print(f"Finding equivalent of '{param}' across tools:")
    for tool in tools:
        equiv = domain_engine.get_equivalent_parameters(param, "generic", tool)
        print(f"  - {tool:10s}: {equiv if equiv else 'Not found'}")
    
    # Example 4: Domain knowledge and best practices
    print("\n📚 Example 4: Domain Knowledge & Best Practices")
    print("-" * 50)
    
    knowledge = domain_engine.get_parameter_knowledge("threshold")
    if knowledge:
        print(f"Parameter: {knowledge.name}")
        print(f"Category: {knowledge.category}")
        print(f"Typical range: {knowledge.typical_range}")
        print(f"Recommended: {knowledge.recommended_range}")
        print(f"Units: {knowledge.units}")
        print("\nBest practices:")
        for i, practice in enumerate(knowledge.best_practices[:3], 1):
            print(f"  {i}. {practice}")
    
    # Example 5: Neurodesk tool validation
    print("\n🐳 Example 5: Neurodesk Tool Validation")
    print("-" * 50)
    
    neurodesk_tools = [
        ("fsl.bet", {"f": 0.5, "g": 0}),
        ("freesurfer.recon-all", {"parallel": True, "openmp": 4}),
        ("ants.Registration", {"dimensionality": 3, "metric": "MI"}),
        ("spm.smooth", {"fwhm": [8, 8, 8]}),
    ]
    
    for tool, params in neurodesk_tools:
        validated = validator.validate_parameters(tool, params)
        print(f"✓ {tool:25s}: {len(validated)} parameters validated")
    
    # Example 6: Parameter validation with warnings
    print("\n⚠️  Example 6: Validation with Warnings")
    print("-" * 50)
    
    risky_params = {
        "smoothing_fwhm": 15.0,  # Very high smoothing
        "motion_threshold": 4.0,  # High motion tolerance
        "threshold": 1.5,  # Low statistical threshold
    }
    
    print("Risky parameters:")
    for param, value in risky_params.items():
        knowledge = domain_engine.get_parameter_knowledge(param)
        if knowledge and knowledge.recommended_range:
            min_rec, max_rec = knowledge.recommended_range
            if min_rec and max_rec:
                if value < min_rec or value > max_rec:
                    print(f"  ⚠️  {param} = {value} (recommended: {min_rec}-{max_rec})")
                else:
                    print(f"  ✓ {param} = {value}")
    
    # Example 7: Complete pipeline validation
    print("\n🔧 Example 7: Complete Pipeline Validation")
    print("-" * 50)
    
    pipeline = {
        # Preprocessing
        "skull_strip": True,
        "motion_correction": True,
        "slice_timing": False,  # Multiband acquisition
        "smoothing_fwhm": 6.0,
        
        # Registration
        "registration_cost": "corratio",
        "registration_dof": 12,
        
        # Statistics
        "threshold": 3.1,
        "cluster_threshold": 20,
        "fdr_correction": True,
    }
    
    print(f"Pipeline with {len(pipeline)} parameters")
    validated = validator.validate_parameters("neuroimaging_pipeline", pipeline)
    print(f"✓ All {len(validated)} parameters validated")
    
    # Show parameter combinations warning
    warnings = domain_engine.validate_parameter_combination({
        "highpass_filter": 0.01,
        "bandpass_filter": [0.01, 0.1]  # Incompatible!
    })
    
    if warnings:
        print("\n⚠️  Parameter combination warnings:")
        for warning in warnings:
            print(f"  - {warning}")
    
    print("\n" + "="*70)
    print("✅ DEMONSTRATION COMPLETE")
    print("="*70)
    print("""
Key Features Demonstrated:
1. ✓ Basic parameter validation
2. ✓ Context-aware suggestions
3. ✓ Cross-tool parameter mapping
4. ✓ Domain knowledge integration
5. ✓ Neurodesk tool support
6. ✓ Warning detection
7. ✓ Pipeline validation
8. ✓ Combination checking

The system provides comprehensive parameter validation with:
- Automatic discovery from multiple sources
- Domain-specific neuroimaging knowledge
- Support for 100+ tools via Neurodesk
- Intelligent suggestions and best practices
    """)


if __name__ == "__main__":
    main()