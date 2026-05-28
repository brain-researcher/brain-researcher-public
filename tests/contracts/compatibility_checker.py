#!/usr/bin/env python3
"""
Contract compatibility checker for Brain Researcher services.

This tool analyzes pact files to detect breaking changes and
ensure backward compatibility between service versions.
"""

import argparse
import json
import logging
from pathlib import Path
from typing import Dict, Any, List, Tuple
from dataclasses import dataclass, asdict

from pact_helpers.verification_utils import VerificationHelper

logger = logging.getLogger(__name__)


@dataclass
class CompatibilityReport:
    """Compatibility analysis report."""
    timestamp: str
    total_contracts: int
    compatible_contracts: int
    incompatible_contracts: int
    breaking_changes: List[str]
    warnings: List[str]
    contracts: Dict[str, Any]
    can_deploy: bool


class ContractCompatibilityChecker:
    """Analyzes contract compatibility between service versions."""
    
    def __init__(self, pact_dir: Path):
        self.pact_dir = Path(pact_dir)
        self.report = CompatibilityReport(
            timestamp="",
            total_contracts=0,
            compatible_contracts=0,
            incompatible_contracts=0,
            breaking_changes=[],
            warnings=[],
            contracts={},
            can_deploy=True
        )
    
    def analyze_all_contracts(self) -> CompatibilityReport:
        """Analyze all contracts in the pact directory."""
        from datetime import datetime
        self.report.timestamp = datetime.utcnow().isoformat() + "Z"
        
        logger.info(f"Analyzing contracts in {self.pact_dir}")
        
        # Find all pact files
        pact_files = list(self.pact_dir.glob("*.json"))
        self.report.total_contracts = len(pact_files)
        
        if not pact_files:
            logger.warning("No pact files found")
            return self.report
        
        # Analyze each contract
        for pact_file in pact_files:
            try:
                self._analyze_contract(pact_file)
            except Exception as e:
                logger.error(f"Failed to analyze {pact_file}: {e}")
                self.report.breaking_changes.append(f"Failed to analyze {pact_file.name}: {e}")
                self.report.incompatible_contracts += 1
        
        # Check for previous versions and compare
        self._check_backward_compatibility()
        
        # Determine if deployment is safe
        self.report.can_deploy = len(self.report.breaking_changes) == 0
        
        logger.info(f"Analysis complete: {self.report.compatible_contracts}/{self.report.total_contracts} contracts compatible")
        
        return self.report
    
    def _analyze_contract(self, pact_file: Path) -> None:
        """Analyze a single contract file."""
        logger.debug(f"Analyzing {pact_file}")
        
        # Validate pact file structure
        is_valid, errors = VerificationHelper.validate_pact_file(pact_file)
        
        contract_name = pact_file.stem
        contract_info = {
            "file": str(pact_file),
            "valid": is_valid,
            "errors": errors,
            "interactions": 0,
            "breaking_changes": [],
            "warnings": []
        }
        
        if not is_valid:
            logger.error(f"Invalid pact file {pact_file}: {errors}")
            contract_info["breaking_changes"].extend(errors)
            self.report.breaking_changes.extend([f"{contract_name}: {error}" for error in errors])
            self.report.incompatible_contracts += 1
        else:
            # Extract interactions for further analysis
            interactions = VerificationHelper.extract_pact_interactions(pact_file)
            contract_info["interactions"] = len(interactions)
            
            # Analyze interactions for potential issues
            interaction_warnings = self._analyze_interactions(interactions, contract_name)
            contract_info["warnings"].extend(interaction_warnings)
            self.report.warnings.extend(interaction_warnings)
            
            self.report.compatible_contracts += 1
        
        self.report.contracts[contract_name] = contract_info
    
    def _analyze_interactions(self, interactions: List[Dict[str, Any]], contract_name: str) -> List[str]:
        """Analyze interactions for potential compatibility issues."""
        warnings = []
        
        for i, interaction in enumerate(interactions):
            # Check for potential issues
            request = interaction.get("request", {})
            response = interaction.get("response", {})
            
            # Warn about strict matching
            if "body" in request and isinstance(request["body"], dict):
                if self._has_strict_matching(request["body"]):
                    warnings.append(f"{contract_name} interaction {i}: Uses strict body matching")
            
            if "body" in response and isinstance(response["body"], dict):
                if self._has_strict_matching(response["body"]):
                    warnings.append(f"{contract_name} interaction {i}: Uses strict response matching")
            
            # Check for missing descriptions
            if not interaction.get("description"):
                warnings.append(f"{contract_name} interaction {i}: Missing description")
            
            # Check for provider state dependencies
            if "providerState" in interaction or "provider_state" in interaction:
                state = interaction.get("providerState") or interaction.get("provider_state")
                if not state:
                    warnings.append(f"{contract_name} interaction {i}: Empty provider state")
        
        return warnings
    
    def _has_strict_matching(self, data: Any) -> bool:
        """Check if data uses strict matching (no matchers)."""
        if isinstance(data, dict):
            # Simple heuristic: if all values are primitive types, it's strict matching
            return all(isinstance(v, (str, int, float, bool, type(None))) for v in data.values())
        return isinstance(data, (str, int, float, bool))
    
    def _check_backward_compatibility(self) -> None:
        """Check backward compatibility with previous versions."""
        logger.info("Checking backward compatibility")
        
        for contract_name, contract_info in self.report.contracts.items():
            # Look for previous version of the same contract
            previous_file = self.pact_dir / f"{contract_name}.previous.json"
            
            if not previous_file.exists():
                logger.debug(f"No previous version found for {contract_name}")
                continue
            
            current_file = Path(contract_info["file"])
            
            try:
                comparison = VerificationHelper.compare_pact_versions(previous_file, current_file)
                
                if not comparison["is_backward_compatible"]:
                    breaking_changes = comparison["breaking_changes"]
                    contract_info["breaking_changes"].extend(breaking_changes)
                    self.report.breaking_changes.extend([
                        f"{contract_name}: {change}" for change in breaking_changes
                    ])
                    
                    # Move from compatible to incompatible
                    if contract_info["valid"]:
                        self.report.compatible_contracts -= 1
                        self.report.incompatible_contracts += 1
                        contract_info["valid"] = False
                
                # Add information about changes
                if comparison["new_interactions"]:
                    contract_info["warnings"].append(
                        f"Added {len(comparison['new_interactions'])} new interactions"
                    )
                
                if comparison["modified_interactions"]:
                    contract_info["warnings"].append(
                        f"Modified {len(comparison['modified_interactions'])} interactions"
                    )
                
            except Exception as e:
                logger.error(f"Failed to compare versions for {contract_name}: {e}")
                self.report.warnings.append(f"{contract_name}: Failed to compare versions")
    
    def generate_report(self, output_file: Path = None) -> str:
        """Generate compatibility report."""
        report_data = asdict(self.report)
        
        if output_file:
            with open(output_file, 'w') as f:
                json.dump(report_data, f, indent=2)
            logger.info(f"Report written to {output_file}")
        
        return json.dumps(report_data, indent=2)
    
    def print_summary(self) -> None:
        """Print compatibility summary to console."""
        print("\n" + "="*60)
        print("CONTRACT COMPATIBILITY REPORT")
        print("="*60)
        
        print(f"Timestamp: {self.report.timestamp}")
        print(f"Total contracts: {self.report.total_contracts}")
        print(f"Compatible: {self.report.compatible_contracts}")
        print(f"Incompatible: {self.report.incompatible_contracts}")
        print(f"Can deploy: {'✅ YES' if self.report.can_deploy else '❌ NO'}")
        
        if self.report.breaking_changes:
            print(f"\n❌ BREAKING CHANGES ({len(self.report.breaking_changes)}):")
            for change in self.report.breaking_changes:
                print(f"  • {change}")
        
        if self.report.warnings:
            print(f"\n⚠️  WARNINGS ({len(self.report.warnings)}):")
            for warning in self.report.warnings[:10]:  # Limit to first 10
                print(f"  • {warning}")
            if len(self.report.warnings) > 10:
                print(f"  ... and {len(self.report.warnings) - 10} more")
        
        print("\nCONTRACT DETAILS:")
        for name, info in self.report.contracts.items():
            status = "✅" if info["valid"] else "❌"
            interactions = info["interactions"]
            print(f"  {status} {name} ({interactions} interactions)")
        
        print("\n" + "="*60)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Analyze contract compatibility for Brain Researcher services"
    )
    parser.add_argument(
        "--pact-dir",
        type=Path,
        default=Path("tests/contracts/pacts"),
        help="Directory containing pact files"
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Output file for JSON report"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose logging"
    )
    parser.add_argument(
        "--fail-on-breaking",
        action="store_true",
        default=True,
        help="Exit with non-zero code if breaking changes detected"
    )
    
    args = parser.parse_args()
    
    # Configure logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Run compatibility check
    checker = ContractCompatibilityChecker(args.pact_dir)
    report = checker.analyze_all_contracts()
    
    # Generate output
    if args.output:
        checker.generate_report(args.output)
    
    checker.print_summary()
    
    # Exit with appropriate code
    if args.fail_on_breaking and not report.can_deploy:
        exit(1)
    else:
        exit(0)


if __name__ == "__main__":
    main()