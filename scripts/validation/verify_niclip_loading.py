#!/usr/bin/env python3
"""
NiCLIP Data Loading Verification Script

Verifies that the NiCLIP spatial mapper can successfully load data files
and reports the loading status of each component.
"""

import os
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

def verify_niclip_data():
    """Verify NiCLIP data loading."""
    print("🔍 NiCLIP Data Loading Verification")
    print("=" * 70)
    print()

    # Check environment variable
    niclip_path = os.environ.get('NICLIP_DATA_PATH')
    if niclip_path:
        print(f"✅ NICLIP_DATA_PATH environment variable set:")
        print(f"   {niclip_path}")
    else:
        print("⚠️  NICLIP_DATA_PATH not set in environment")
        niclip_path = str(project_root / "data" / "niclip" / "data")
        print(f"   Using default: {niclip_path}")

    print()

    # Check if path exists
    niclip_path_obj = Path(niclip_path)
    if niclip_path_obj.exists():
        print(f"✅ NiCLIP data directory exists")
    else:
        print(f"❌ NiCLIP data directory does not exist: {niclip_path}")
        return False

    print()

    # Check required files
    required_files = {
        "MNI152_2x2x2_brainmask.nii.gz": "Brain mask file",
        "vocabulary": "Vocabulary directory (task priors)",
        "cognitive_atlas": "Cognitive Atlas directory",
        "text": "Text embeddings directory",
        "image": "Image embeddings directory",
    }

    print("📁 Checking required files/directories:")
    all_present = True
    for file_name, description in required_files.items():
        file_path = niclip_path_obj / file_name
        if file_path.exists():
            if file_path.is_dir():
                # Count files in directory
                file_count = len(list(file_path.iterdir()))
                print(f"   ✅ {file_name:40} ({file_count} files)")
            else:
                size_mb = file_path.stat().st_size / (1024 * 1024)
                print(f"   ✅ {file_name:40} ({size_mb:.2f} MB)")
        else:
            print(f"   ❌ {file_name:40} MISSING")
            all_present = False

    print()

    if not all_present:
        print("❌ Some required files are missing")
        return False

    # Try to load the mapper
    print("🧪 Testing NiCLIP Spatial Mapper...")
    try:
        from brain_researcher.services.neurokg.etl.mappers.niclip_spatial_mapper_improved import (
            get_improved_mapper
        )

        mapper = get_improved_mapper()

        if mapper is None:
            print("❌ Failed to get mapper instance")
            return False

        print(f"✅ Mapper instance created")

        # Check if mapper is loaded
        if hasattr(mapper, '_loaded'):
            if mapper._loaded:
                print(f"✅ Mapper successfully loaded data")
                print(f"   Mapper path: {mapper.niclip_path}")

                # Check loaded components
                print()
                print("📊 Loaded Components:")

                if hasattr(mapper, 'brain_mask') and mapper.brain_mask is not None:
                    print(f"   ✅ Brain mask loaded")
                    print(f"      Shape: {mapper.brain_mask.shape}")
                else:
                    print(f"   ⚠️  Brain mask not loaded")

                if hasattr(mapper, 'task_priors') and mapper.task_priors:
                    print(f"   ✅ Task priors loaded ({len(mapper.task_priors)} tasks)")
                else:
                    print(f"   ⚠️  Task priors not loaded")

                if hasattr(mapper, 'concept_map') and mapper.concept_map:
                    print(f"   ✅ Concept mappings loaded ({len(mapper.concept_map)} concepts)")
                else:
                    print(f"   ⚠️  Concept mappings not loaded")

                # Test coordinate mapping
                print()
                print("🧪 Testing coordinate-to-concept mapping...")
                test_coords = [(42, -22, 54)]  # Primary motor cortex

                try:
                    results = mapper.coordinate_to_concepts(test_coords, radius=10.0, top_k=5)
                    if results:
                        print(f"✅ Mapping successful!")
                        print(f"   Test coordinate: {test_coords[0]}")
                        print(f"   Top concepts:")
                        for concept_info in results[0].get('concepts', [])[:3]:
                            print(f"      • {concept_info['concept']} (score: {concept_info['score']:.3f})")
                    else:
                        print(f"⚠️  Mapping returned no results")
                except Exception as e:
                    print(f"❌ Mapping failed: {str(e)}")
                    return False

                print()
                print("=" * 70)
                print("✅ NiCLIP data is properly loaded and functional!")
                return True
            else:
                print(f"❌ Mapper failed to load data")
                print(f"   Check logs for error messages")
                return False
        else:
            print(f"⚠️  Mapper does not have _loaded attribute")
            return False

    except ImportError as e:
        print(f"❌ Failed to import mapper: {str(e)}")
        return False
    except Exception as e:
        print(f"❌ Error during verification: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print()
    success = verify_niclip_data()
    print()

    if success:
        print("✅ VERIFICATION PASSED - NiCLIP is ready to use!")
        sys.exit(0)
    else:
        print("❌ VERIFICATION FAILED - Check errors above")
        sys.exit(1)
