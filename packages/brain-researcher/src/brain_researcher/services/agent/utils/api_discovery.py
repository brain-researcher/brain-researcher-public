"""
API Discovery Module for Parameter Validation.

Automatically discovers parameter ranges and constraints from multiple sources:
- Python package APIs and docstrings
- Command-line help text (Neurodesk tools)
- Online documentation
- Configuration files
"""

import ast
import inspect
import json
import logging
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


class APIDiscovery:
    """Discovers parameter information from various sources."""
    
    def __init__(self):
        """Initialize API discovery with source handlers."""
        self.neurodesk_base = Path("/cvmfs/neurodesk.ardc.edu.au/neurodesk-modules")
        self.cache_dir = Path.home() / ".cache" / "brain_researcher" / "api_discovery"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
    def discover_all(self, tool_name: str) -> Dict[str, Any]:
        """
        Discover parameter information from all available sources.
        
        Args:
            tool_name: Name of the tool to discover
            
        Returns:
            Combined parameter information from all sources
        """
        results = {}
        
        # Try each discovery method
        discovery_methods = [
            ("python_api", self.discover_from_python_api),
            ("cli_help", self.discover_from_cli_help),
            ("neurodesk", self.discover_from_neurodesk),
            ("config_files", self.discover_from_config_files),
            ("online_docs", self.discover_from_online_docs),
        ]
        
        for source_name, method in discovery_methods:
            try:
                source_results = method(tool_name)
                if source_results:
                    results[source_name] = source_results
                    logger.info(f"Discovered {len(source_results)} parameters from {source_name} for {tool_name}")
            except Exception as e:
                logger.debug(f"Discovery from {source_name} failed for {tool_name}: {e}")
                
        return self._merge_discoveries(results)
    
    def discover_from_python_api(self, tool_name: str) -> Optional[Dict[str, Any]]:
        """
        Discover parameters from Python package APIs.
        
        Args:
            tool_name: Name of the tool/package
            
        Returns:
            Parameter information from Python API
        """
        try:
            # Map tool names to Python modules
            module_mapping = {
                "nilearn": "nilearn",
                "nibabel": "nibabel",
                "fsl": "nipype.interfaces.fsl",
                "ants": "nipype.interfaces.ants",
                "freesurfer": "nipype.interfaces.freesurfer",
                "spm": "nipype.interfaces.spm",
                "afni": "nipype.interfaces.afni",
            }
            
            module_name = module_mapping.get(tool_name.lower())
            if not module_name:
                return None
                
            # Try to import the module
            module = __import__(module_name, fromlist=[''])
            
            # Extract parameter information
            parameters = {}
            
            # Look for common analysis functions
            common_functions = [
                "smooth_img", "resample_img", "threshold_img",  # nilearn
                "load", "save", "Nifti1Image",  # nibabel
                "FLIRT", "FNIRT", "BET", "FAST",  # FSL via nipype
                "Registration", "N4BiasFieldCorrection",  # ANTs
            ]
            
            for func_name in common_functions:
                if hasattr(module, func_name):
                    func = getattr(module, func_name)
                    try:
                        sig = inspect.signature(func)
                        found_params = False
                        for param_name, param in sig.parameters.items():
                            if param_name in ['self', 'cls', 'args', 'kwargs']:
                                continue

                            param_info = {
                                "type": self._get_param_type(param),
                                "default": self._get_param_default(param),
                                "description": self._extract_param_description(func, param_name),
                            }

                            # Try to infer ranges from docstring
                            if param_info["description"]:
                                param_info["range"] = self._extract_range_from_description(
                                    param_info["description"]
                                )

                            parameters[f"{func_name}.{param_name}"] = param_info
                            found_params = True
                        if not found_params:
                            for param_name, type_hint, desc in self._parse_docstring_params(
                                getattr(func, "__doc__", "") or ""
                            ):
                                description = desc or self._extract_param_description(func, param_name)
                                param_info = {
                                    "type": self._infer_type_from_text(type_hint or description),
                                    "default": None,
                                    "description": description,
                                }
                                if param_info["description"]:
                                    param_info["range"] = self._extract_range_from_description(
                                        param_info["description"]
                                    )
                                parameters[f"{func_name}.{param_name}"] = param_info
                    except (TypeError, ValueError):
                        # Fall back to docstring parsing for non-introspectable callables
                        for param_name, type_hint, desc in self._parse_docstring_params(
                            getattr(func, "__doc__", "") or ""
                        ):
                            description = desc or self._extract_param_description(func, param_name)
                            param_info = {
                                "type": self._infer_type_from_text(type_hint or description),
                                "default": None,
                                "description": description,
                            }
                            if param_info["description"]:
                                param_info["range"] = self._extract_range_from_description(
                                    param_info["description"]
                                )
                            parameters[f"{func_name}.{param_name}"] = param_info
                        
            return parameters if parameters else None
            
        except Exception as e:
            logger.debug(f"Python API discovery failed for {tool_name}: {e}")
            return None
    
    def discover_from_cli_help(self, tool_name: str) -> Optional[Dict[str, Any]]:
        """
        Discover parameters from command-line help text.
        
        Args:
            tool_name: Name of the CLI tool
            
        Returns:
            Parameter information from CLI help
        """
        try:
            # Common help flags to try
            help_flags = ["--help", "-h", "-help", "help"]
            
            for flag in help_flags:
                try:
                    result = subprocess.run(
                        [tool_name, flag],
                        capture_output=True,
                        text=True,
                        timeout=5
                    )
                    
                    if result.returncode == 0 or result.stdout:
                        return self._parse_cli_help(result.stdout)
                        
                except (subprocess.TimeoutExpired, FileNotFoundError):
                    continue
                    
            return None
            
        except Exception as e:
            logger.debug(f"CLI help discovery failed for {tool_name}: {e}")
            return None
    
    def discover_from_neurodesk(self, tool_name: str) -> Optional[Dict[str, Any]]:
        """
        Discover parameters from Neurodesk module files.
        
        Args:
            tool_name: Name of the Neurodesk tool
            
        Returns:
            Parameter information from Neurodesk
        """
        try:
            if not self.neurodesk_base.exists():
                return None
                
            # Search for tool in Neurodesk modules
            tool_paths = []
            
            # Common categories to search
            categories = [
                "functional_imaging",
                "structural_imaging", 
                "diffusion",
                "statistics",
                "visualization"
            ]
            
            for category in categories:
                category_path = self.neurodesk_base / category
                if category_path.exists():
                    # Look for tool directories
                    for tool_dir in category_path.glob(f"*{tool_name}*"):
                        if tool_dir.is_dir():
                            tool_paths.append(tool_dir)
                            
            if not tool_paths:
                return None
                
            # Extract parameter info from module files
            parameters = {}
            
            for tool_path in tool_paths:
                # Look for help files or scripts
                for help_file in tool_path.glob("*.txt"):
                    with open(help_file) as f:
                        content = f.read()
                        params = self._parse_cli_help(content)
                        if params:
                            parameters.update(params)
                            
                # Look for wrapper scripts
                for script in tool_path.glob("*.sh"):
                    params = self._extract_params_from_script(script)
                    if params:
                        parameters.update(params)
                        
            return parameters if parameters else None
            
        except Exception as e:
            logger.debug(f"Neurodesk discovery failed for {tool_name}: {e}")
            return None
    
    def discover_from_config_files(self, tool_name: str) -> Optional[Dict[str, Any]]:
        """
        Discover parameters from configuration files.
        
        Args:
            tool_name: Name of the tool
            
        Returns:
            Parameter information from config files
        """
        try:
            # Common config locations
            config_paths = [
                Path.home() / f".{tool_name}",
                Path.home() / f".config" / tool_name,
                Path("/etc") / tool_name,
                Path.cwd() / f"{tool_name}.conf",
                Path.cwd() / f".{tool_name}rc",
            ]
            
            parameters = {}
            
            for config_path in config_paths:
                if config_path.exists():
                    if config_path.is_file():
                        params = self._parse_config_file(config_path)
                        if params:
                            parameters.update(params)
                    elif config_path.is_dir():
                        # Look for config files in directory
                        for config_file in config_path.glob("*.{conf,cfg,json,yaml,yml}"):
                            params = self._parse_config_file(config_file)
                            if params:
                                parameters.update(params)
                                
            return parameters if parameters else None
            
        except Exception as e:
            logger.debug(f"Config file discovery failed for {tool_name}: {e}")
            return None
    
    def discover_from_online_docs(self, tool_name: str) -> Optional[Dict[str, Any]]:
        """
        Discover parameters from online documentation.
        
        Args:
            tool_name: Name of the tool
            
        Returns:
            Parameter information from online docs
        """
        try:
            # Check cache first
            cache_file = self.cache_dir / f"{tool_name}_online.json"
            if cache_file.exists():
                age = (Path.ctime(Path()) - cache_file.stat().st_mtime) / 3600
                if age < 24:  # Cache for 24 hours
                    with open(cache_file) as f:
                        return json.load(f)
                        
            # Documentation URLs for common neuroimaging tools
            doc_urls = {
                "fsl": "https://fsl.fmrib.ox.ac.uk/fsl/fslwiki/",
                "freesurfer": "https://surfer.nmr.mgh.harvard.edu/fswiki/",
                "ants": "http://stnava.github.io/ANTs/",
                "spm": "https://www.fil.ion.ucl.ac.uk/spm/doc/",
                "afni": "https://afni.nimh.nih.gov/pub/dist/doc/htmldoc/",
                "mrtrix": "https://mrtrix.readthedocs.io/",
                "nilearn": "https://nilearn.github.io/stable/modules/reference.html",
            }
            
            base_url = doc_urls.get(tool_name.lower())
            if not base_url:
                return None
                
            # Fetch documentation page
            response = requests.get(base_url, timeout=10)
            if response.status_code != 200:
                return None
                
            # Parse HTML for parameter information
            soup = BeautifulSoup(response.text, 'html.parser')
            parameters = self._extract_params_from_html(soup, tool_name)
            
            # Cache results
            if parameters:
                with open(cache_file, 'w') as f:
                    json.dump(parameters, f)
                    
            return parameters
            
        except Exception as e:
            logger.debug(f"Online docs discovery failed for {tool_name}: {e}")
            return None
    
    def _parse_cli_help(self, help_text: str) -> Dict[str, Any]:
        """Parse CLI help text to extract parameters."""
        parameters = {}
        
        # Common patterns for CLI parameters
        patterns = [
            r'-(\w+),?\s*--([^\s]+)\s+(.+)',  # -s, --smooth description
            r'--([^\s]+)\s+(.+)',  # --parameter description
            r'-(\w)\s+(.+)',  # -p description
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, help_text, re.MULTILINE)
            for match in matches:
                if len(match) == 3:
                    short, long, desc = match
                    param_name = long if long else short
                elif len(match) == 2:
                    param_name, desc = match
                else:
                    continue
                    
                # Extract type and range from description
                param_type = "string"  # default
                param_range = None
                
                # Look for type hints (use word boundaries to avoid "intensity" -> int)
                if re.search(r"\binteger\b", desc, re.IGNORECASE) or re.search(r"\bint\b", desc, re.IGNORECASE):
                    param_type = "integer"
                elif re.search(r"\bfloat\b", desc, re.IGNORECASE) or "number" in desc.lower():
                    param_type = "float"
                elif re.search(r"\bbool\b", desc, re.IGNORECASE) or "flag" in desc.lower():
                    param_type = "boolean"
                    
                # Look for range patterns
                range_match = re.search(r'\[([0-9.-]+)[,\s]*([0-9.-]+)\]', desc)
                if range_match:
                    param_range = [float(range_match.group(1)), float(range_match.group(2))]
                else:
                    arrow_match = re.search(r'([0-9.-]+)\s*->\s*([0-9.-]+)', desc)
                    if arrow_match:
                        param_range = [float(arrow_match.group(1)), float(arrow_match.group(2))]

                # Infer float if decimal defaults/ranges appear
                if param_type == "string":
                    if re.search(r"[0-9]\.[0-9]", desc):
                        param_type = "float"
                
                parameters[param_name] = {
                    "type": param_type,
                    "description": desc.strip(),
                    "range": param_range
                }
                
        return parameters
    
    def _extract_params_from_script(self, script_path: Path) -> Dict[str, Any]:
        """Extract parameter information from shell scripts."""
        parameters = {}
        
        try:
            with open(script_path) as f:
                content = f.read()
                
            # Look for parameter definitions
            param_patterns = [
                r'#\s*@param\s+(\w+)\s+(.+)',  # Documented parameters
                r'(\w+)=\${?\d+:-([^}]+)}?',  # Default values
                r'if\s+\[\s*"\$(\w+)"\s*([<>=]+)\s*([0-9.-]+)\s*\]',  # Range checks
            ]
            
            for pattern in param_patterns:
                matches = re.findall(pattern, content)
                for match in matches:
                    if len(match) >= 2:
                        param_name = match[0]
                        if param_name not in parameters:
                            parameters[param_name] = {}
                            
                        if "@param" in pattern:
                            parameters[param_name]["description"] = match[1]
                        elif ":-" in pattern:
                            parameters[param_name]["default"] = match[1]
                        elif "if" in pattern:
                            # Extract range from conditionals
                            op = match[1]
                            value = float(match[2])
                            if "range" not in parameters[param_name]:
                                parameters[param_name]["range"] = [None, None]
                            if "<" in op:
                                parameters[param_name]["range"][1] = value
                            elif ">" in op:
                                parameters[param_name]["range"][0] = value
                                
        except Exception as e:
            logger.debug(f"Script parsing failed for {script_path}: {e}")
            
        return parameters
    
    def _parse_config_file(self, config_path: Path) -> Dict[str, Any]:
        """Parse configuration files for parameter information."""
        parameters = {}
        
        try:
            suffix = config_path.suffix.lower()
            
            if suffix == ".json":
                with open(config_path) as f:
                    data = json.load(f)
                parameters = self._extract_params_from_dict(data)
                
            elif suffix in [".yaml", ".yml"]:
                import yaml
                with open(config_path) as f:
                    data = yaml.safe_load(f)
                parameters = self._extract_params_from_dict(data)
                
            else:
                # Parse as key=value format
                with open(config_path) as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#"):
                            if "=" in line:
                                key, value = line.split("=", 1)
                                parameters[key.strip()] = {
                                    "value": value.strip(),
                                    "source": "config"
                                }
                                
        except Exception as e:
            logger.debug(f"Config parsing failed for {config_path}: {e}")
            
        return parameters
    
    def _extract_params_from_dict(self, data: Dict, prefix: str = "") -> Dict[str, Any]:
        """Extract parameters from nested dictionary structure."""
        parameters = {}
        
        for key, value in data.items():
            full_key = f"{prefix}.{key}" if prefix else key
            
            if isinstance(value, dict):
                # Recurse into nested structures
                nested = self._extract_params_from_dict(value, full_key)
                parameters.update(nested)
            else:
                # Store parameter value and infer type
                param_info = {
                    "value": value,
                    "type": type(value).__name__
                }
                
                # Infer ranges for numeric types
                if isinstance(value, (int, float)):
                    # Common patterns for range constraints
                    if "threshold" in key.lower():
                        param_info["range"] = [0, None]
                    elif "probability" in key.lower() or "prob" in key.lower():
                        param_info["range"] = [0, 1]
                    elif "iterations" in key.lower() or "iter" in key.lower():
                        param_info["range"] = [1, None]
                        
                parameters[full_key] = param_info
                
        return parameters
    
    def _extract_params_from_html(self, soup: BeautifulSoup, tool_name: str) -> Dict[str, Any]:
        """Extract parameter information from HTML documentation."""
        parameters = {}
        
        # Look for parameter tables
        tables = soup.find_all('table')
        for table in tables:
            # Check if this is a parameter table
            headers = table.find_all('th')
            if any('parameter' in h.text.lower() for h in headers):
                rows = table.find_all('tr')[1:]  # Skip header
                for row in rows:
                    cells = row.find_all('td')
                    if len(cells) >= 2:
                        param_name = cells[0].text.strip()
                        param_desc = cells[1].text.strip()
                        
                        param_info = {
                            "description": param_desc,
                            "source": "documentation"
                        }
                        
                        # Extract type and range from description
                        if len(cells) > 2:
                            param_info["type"] = cells[2].text.strip()
                        if len(cells) > 3:
                            param_info["default"] = cells[3].text.strip()
                            
                        parameters[param_name] = param_info
                        
        # Look for definition lists
        dl_elements = soup.find_all('dl')
        for dl in dl_elements:
            terms = dl.find_all('dt')
            definitions = dl.find_all('dd')
            
            for term, definition in zip(terms, definitions):
                param_name = term.text.strip()
                if param_name.startswith('-'):
                    param_info = {
                        "description": definition.text.strip(),
                        "source": "documentation"
                    }
                    parameters[param_name.lstrip('-')] = param_info
                    
        return parameters
    
    def _get_param_type(self, param: inspect.Parameter) -> str:
        """Get parameter type from inspect.Parameter."""
        if param.annotation != inspect.Parameter.empty:
            type_str = str(param.annotation)
            if "int" in type_str:
                return "integer"
            elif "float" in type_str:
                return "float"
            elif "bool" in type_str:
                return "boolean"
            elif "str" in type_str:
                return "string"
            elif "list" in type_str or "List" in type_str:
                return "array"
            elif "dict" in type_str or "Dict" in type_str:
                return "object"
        return "any"

    def _infer_type_from_text(self, text: Optional[str]) -> str:
        """Infer a simple parameter type from text hints."""
        if not text:
            return "any"
        lower = text.lower()
        if "float" in lower or "double" in lower:
            return "float"
        if "int" in lower or "integer" in lower:
            return "integer"
        if "bool" in lower or "boolean" in lower:
            return "boolean"
        if "list" in lower or "array" in lower:
            return "array"
        return "string"
    
    def _get_param_default(self, param: inspect.Parameter) -> Any:
        """Get parameter default value."""
        if param.default != inspect.Parameter.empty:
            return param.default
        return None
    
    def _extract_param_description(self, func: Any, param_name: str) -> Optional[str]:
        """Extract parameter description from docstring."""
        if not func.__doc__:
            return None
            
        # Parse docstring for parameter descriptions
        lines = func.__doc__.split('\n')
        in_params = False
        
        for i, line in enumerate(lines):
            if 'Parameters' in line or 'Args:' in line:
                in_params = True
                continue
            elif in_params and line.strip() and not line.startswith(' '):
                # End of parameters section
                break
            elif in_params and param_name in line:
                # Found parameter, extract description
                desc_lines = [line.split(':', 1)[-1].strip()]
                
                # Get continuation lines
                for j in range(i + 1, len(lines)):
                    if lines[j].startswith('        '):
                        desc_lines.append(lines[j].strip())
                    else:
                        break
                        
                return ' '.join(desc_lines)
                
        return None
    
    def _extract_range_from_description(self, description: str) -> Optional[List[float]]:
        """Extract numeric range from description text."""
        # Common range patterns
        patterns = [
            r'between\s+([0-9.-]+)\s+and\s+([0-9.-]+)',
            r'from\s+([0-9.-]+)\s+to\s+([0-9.-]+)',
            r'\[([0-9.-]+),\s*([0-9.-]+)\]',
            r'range:\s*([0-9.-]+)-([0-9.-]+)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, description, re.IGNORECASE)
            if match:
                try:
                    return [float(match.group(1)), float(match.group(2))]
                except ValueError:
                    continue
                    
        # Check for minimum/maximum mentions
        min_val = None
        max_val = None
        
        min_match = re.search(r'minimum[:\s]+([0-9.-]+)', description, re.IGNORECASE)
        if min_match:
            min_val = float(min_match.group(1))
            
        max_match = re.search(r'maximum[:\s]+([0-9.-]+)', description, re.IGNORECASE)
        if max_match:
            max_val = float(max_match.group(1))
            
        if min_val is not None or max_val is not None:
            return [min_val, max_val]
            
        return None

    def _parse_docstring_params(self, docstring: str) -> List[Tuple[str, str, str]]:
        """Parse Numpy-style docstrings for parameter names/types/descriptions."""
        if not docstring:
            return []

        params: List[Tuple[str, str, str]] = []
        lines = docstring.splitlines()
        in_params = False
        current_index: Optional[int] = None

        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.lower().startswith("parameters"):
                in_params = True
                continue
            if in_params and stripped and stripped.lower().startswith(("returns", "yield", "notes", "examples")):
                break

            if in_params:
                match = re.match(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.+)$", line)
                if match:
                    params.append((match.group(1), match.group(2).strip(), ""))
                    current_index = len(params) - 1
                    continue
                if current_index is not None and line.startswith(" " * 4):
                    name, type_hint, desc = params[current_index]
                    extra = stripped
                    if extra:
                        desc = f"{desc} {extra}".strip()
                        params[current_index] = (name, type_hint, desc)

        return params
    
    def _merge_discoveries(self, results: Dict[str, Dict]) -> Dict[str, Any]:
        """Merge parameter discoveries from multiple sources."""
        merged = {}
        
        # Priority order for sources (higher priority overwrites lower)
        priority = ["online_docs", "python_api", "neurodesk", "cli_help", "config_files"]
        
        # Collect all parameter names
        all_params = set()
        for source_results in results.values():
            if source_results:
                all_params.update(source_results.keys())
                
        # Merge information for each parameter
        for param_name in all_params:
            param_info = {}
            sources = []
            
            for source in priority:
                if source in results and results[source] and param_name in results[source]:
                    source_info = results[source][param_name]
                    
                    # Merge information, preferring non-None values
                    for key, value in source_info.items():
                        if value is not None and (key not in param_info or param_info[key] is None):
                            param_info[key] = value
                            
                    sources.append(source)
                    
            param_info["sources"] = sources
            merged[param_name] = param_info
            
        return merged
