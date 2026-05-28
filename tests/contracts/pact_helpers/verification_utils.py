"""
Utilities for contract verification and validation.
"""

import json
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
import jsonschema
from jsonschema import validate, ValidationError

logger = logging.getLogger(__name__)


class VerificationHelper:
    """Helper class for contract verification operations."""
    
    @staticmethod
    def validate_pact_file(pact_file_path: Path) -> Tuple[bool, List[str]]:
        """Validate a pact file structure."""
        errors = []
        
        try:
            with open(pact_file_path, 'r') as f:
                pact_data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            return False, [f"Failed to read pact file: {e}"]
        
        # Check required top-level fields
        required_fields = ['consumer', 'provider', 'interactions', 'metadata']
        for field in required_fields:
            if field not in pact_data:
                errors.append(f"Missing required field: {field}")
        
        # Validate consumer and provider
        if 'consumer' in pact_data:
            if not isinstance(pact_data['consumer'], dict) or 'name' not in pact_data['consumer']:
                errors.append("Consumer must be an object with 'name' field")
        
        if 'provider' in pact_data:
            if not isinstance(pact_data['provider'], dict) or 'name' not in pact_data['provider']:
                errors.append("Provider must be an object with 'name' field")
        
        # Validate interactions
        if 'interactions' in pact_data:
            if not isinstance(pact_data['interactions'], list):
                errors.append("Interactions must be an array")
            else:
                for i, interaction in enumerate(pact_data['interactions']):
                    interaction_errors = VerificationHelper._validate_interaction(interaction, i)
                    errors.extend(interaction_errors)
        
        return len(errors) == 0, errors
    
    @staticmethod
    def _validate_interaction(interaction: Dict[str, Any], index: int) -> List[str]:
        """Validate a single interaction."""
        errors = []
        prefix = f"Interaction {index}"
        
        # Check required fields
        required_fields = ['description', 'request', 'response']
        for field in required_fields:
            if field not in interaction:
                errors.append(f"{prefix}: Missing required field '{field}'")
        
        # Validate request
        if 'request' in interaction:
            request_errors = VerificationHelper._validate_request(interaction['request'], prefix)
            errors.extend(request_errors)
        
        # Validate response
        if 'response' in interaction:
            response_errors = VerificationHelper._validate_response(interaction['response'], prefix)
            errors.extend(response_errors)
        
        return errors
    
    @staticmethod
    def _validate_request(request: Dict[str, Any], prefix: str) -> List[str]:
        """Validate a request specification."""
        errors = []
        
        # Check required fields
        if 'method' not in request:
            errors.append(f"{prefix}: Request missing 'method' field")
        elif request['method'] not in ['GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'HEAD', 'OPTIONS']:
            errors.append(f"{prefix}: Invalid HTTP method '{request['method']}'")
        
        if 'path' not in request:
            errors.append(f"{prefix}: Request missing 'path' field")
        elif not isinstance(request['path'], (str, dict)):
            errors.append(f"{prefix}: Request path must be string or matcher object")
        
        # Validate optional fields
        if 'headers' in request and not isinstance(request['headers'], dict):
            errors.append(f"{prefix}: Request headers must be an object")
        
        if 'query' in request and not isinstance(request['query'], dict):
            errors.append(f"{prefix}: Request query must be an object")
        
        return errors
    
    @staticmethod
    def _validate_response(response: Dict[str, Any], prefix: str) -> List[str]:
        """Validate a response specification."""
        errors = []
        
        # Check required fields
        if 'status' not in response:
            errors.append(f"{prefix}: Response missing 'status' field")
        elif not isinstance(response['status'], int) or not (100 <= response['status'] <= 599):
            errors.append(f"{prefix}: Response status must be valid HTTP status code")
        
        # Validate optional fields
        if 'headers' in response and not isinstance(response['headers'], dict):
            errors.append(f"{prefix}: Response headers must be an object")
        
        return errors
    
    @staticmethod
    def validate_contract_compatibility(
        consumer_pact: Dict[str, Any], 
        provider_capabilities: Dict[str, Any]
    ) -> Tuple[bool, List[str]]:
        """Validate that provider capabilities match consumer expectations."""
        errors = []
        
        # Check if provider supports all required endpoints
        consumer_paths = set()
        for interaction in consumer_pact.get('interactions', []):
            request = interaction.get('request', {})
            method = request.get('method', '').upper()
            path = request.get('path', '')
            if isinstance(path, str):
                consumer_paths.add(f"{method} {path}")
        
        provider_paths = set(provider_capabilities.get('supported_endpoints', []))
        
        missing_endpoints = consumer_paths - provider_paths
        if missing_endpoints:
            errors.extend([f"Provider missing endpoint: {ep}" for ep in missing_endpoints])
        
        return len(errors) == 0, errors
    
    @staticmethod
    def generate_compatibility_report(
        pact_dir: Path,
        provider_name: str
    ) -> Dict[str, Any]:
        """Generate compatibility report for a provider."""
        report = {
            "provider": provider_name,
            "consumers": {},
            "total_interactions": 0,
            "total_errors": 0,
            "compatible_consumers": [],
            "incompatible_consumers": []
        }
        
        # Find all pact files for this provider
        for pact_file in pact_dir.glob(f"*-{provider_name}.json"):
            consumer_name = pact_file.stem.replace(f"-{provider_name}", "")
            
            is_valid, errors = VerificationHelper.validate_pact_file(pact_file)
            
            if is_valid:
                with open(pact_file, 'r') as f:
                    pact_data = json.load(f)
                    
                interactions_count = len(pact_data.get('interactions', []))
                report["total_interactions"] += interactions_count
                
                report["consumers"][consumer_name] = {
                    "pact_file": str(pact_file),
                    "interactions": interactions_count,
                    "errors": [],
                    "valid": True
                }
                report["compatible_consumers"].append(consumer_name)
            else:
                report["consumers"][consumer_name] = {
                    "pact_file": str(pact_file),
                    "interactions": 0,
                    "errors": errors,
                    "valid": False
                }
                report["incompatible_consumers"].append(consumer_name)
                report["total_errors"] += len(errors)
        
        return report
    
    @staticmethod
    def validate_response_schema(response_data: Any, expected_schema: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """Validate response data against JSON schema."""
        try:
            validate(instance=response_data, schema=expected_schema)
            return True, None
        except ValidationError as e:
            return False, str(e)
    
    @staticmethod
    def extract_pact_interactions(pact_file_path: Path) -> List[Dict[str, Any]]:
        """Extract interactions from a pact file."""
        try:
            with open(pact_file_path, 'r') as f:
                pact_data = json.load(f)
            return pact_data.get('interactions', [])
        except (FileNotFoundError, json.JSONDecodeError) as e:
            logger.error(f"Failed to extract interactions from {pact_file_path}: {e}")
            return []
    
    @staticmethod
    def compare_pact_versions(old_pact_file: Path, new_pact_file: Path) -> Dict[str, Any]:
        """Compare two versions of a pact file for breaking changes."""
        comparison = {
            "breaking_changes": [],
            "new_interactions": [],
            "removed_interactions": [],
            "modified_interactions": [],
            "is_backward_compatible": True
        }
        
        try:
            old_interactions = VerificationHelper.extract_pact_interactions(old_pact_file)
            new_interactions = VerificationHelper.extract_pact_interactions(new_pact_file)
            
            # Create lookup by description
            old_lookup = {i.get('description', ''): i for i in old_interactions}
            new_lookup = {i.get('description', ''): i for i in new_interactions}
            
            # Find removed interactions (breaking)
            for desc in old_lookup:
                if desc not in new_lookup:
                    comparison["removed_interactions"].append(desc)
                    comparison["breaking_changes"].append(f"Removed interaction: {desc}")
            
            # Find new interactions (non-breaking)
            for desc in new_lookup:
                if desc not in old_lookup:
                    comparison["new_interactions"].append(desc)
            
            # Find modified interactions
            for desc in old_lookup:
                if desc in new_lookup:
                    old_interaction = old_lookup[desc]
                    new_interaction = new_lookup[desc]
                    
                    if old_interaction != new_interaction:
                        comparison["modified_interactions"].append(desc)
                        
                        # Check for breaking changes in response
                        old_response = old_interaction.get('response', {})
                        new_response = new_interaction.get('response', {})
                        
                        if old_response.get('status') != new_response.get('status'):
                            comparison["breaking_changes"].append(
                                f"Changed response status for '{desc}': "
                                f"{old_response.get('status')} -> {new_response.get('status')}"
                            )
            
            comparison["is_backward_compatible"] = len(comparison["breaking_changes"]) == 0
            
        except Exception as e:
            logger.error(f"Failed to compare pact versions: {e}")
            comparison["error"] = str(e)
        
        return comparison