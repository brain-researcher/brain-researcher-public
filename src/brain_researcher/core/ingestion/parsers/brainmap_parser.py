"""Parser for BrainMap data formats."""

import json
import re
import xml.etree.ElementTree as ET
from typing import Any


class BrainMapParser:
    """Parser for BrainMap experimental data."""

    def __init__(self):
        self.coordinate_spaces = {
            "MNI": {"x": (-90, 90), "y": (-126, 91), "z": (-72, 109)},
            "TAL": {"x": (-80, 80), "y": (-110, 80), "z": (-65, 85)},
            "Talairach": {"x": (-80, 80), "y": (-110, 80), "z": (-65, 85)},
        }

        # Standard behavioral domain categories
        self.behavioral_domains_taxonomy = {
            "action": [
                "execution",
                "imagination",
                "inhibition",
                "observation",
                "preparation",
            ],
            "cognition": ["attention", "language", "memory", "reasoning", "social"],
            "emotion": ["anger", "anxiety", "disgust", "fear", "happiness", "sadness"],
            "interoception": ["bladder", "heartbeat", "hunger", "sexuality", "thirst"],
            "perception": [
                "audition",
                "gustation",
                "olfaction",
                "somesthesis",
                "vision",
            ],
        }

    def parse_workspace(self, workspace_path: str) -> list[dict[str, Any]]:
        """Parse BrainMap Sleuth workspace file.

        Args:
            workspace_path: Path to workspace file

        Returns:
            List of parsed experiments
        """
        experiments = []

        try:
            # Try XML format first
            tree = ET.parse(workspace_path)
            root = tree.getroot()

            # Check for namespace
            ns = {}
            if root.tag.startswith("{"):
                # Extract namespace
                ns_url = root.tag.split("}")[0][1:]
                ns = {"bm": ns_url}

                # Find experiments with namespace
                for exp in root.findall(".//bm:Experiment", ns) + root.findall(
                    ".//bm:experiment", ns
                ):
                    experiment = self._parse_xml_experiment(exp, ns)
                    if experiment:
                        experiments.append(experiment)
            else:
                # Try both lowercase and uppercase tags without namespace
                for exp in root.findall(".//experiment") + root.findall(
                    ".//Experiment"
                ):
                    experiment = self._parse_xml_experiment(exp)
                    if experiment:
                        experiments.append(experiment)

        except ET.ParseError:
            # Try JSON format
            try:
                with open(workspace_path) as f:
                    data = json.load(f)

                if isinstance(data, list):
                    experiments = data
                elif isinstance(data, dict) and "experiments" in data:
                    experiments = data["experiments"]

            except json.JSONDecodeError:
                # Try custom text format
                experiments = self._parse_text_workspace(workspace_path)

        return experiments

    def _parse_xml_experiment(
        self, exp_element: ET.Element, ns: dict[str, str] = None
    ) -> dict[str, Any]:
        """Parse single experiment from XML.

        Args:
            exp_element: XML element for experiment

        Returns:
            Parsed experiment data
        """
        experiment = {
            "experiment_id": exp_element.get("id", ""),
            "contrasts": [],
            "coordinates": [],
            "behavioral_domains": [],
            "paradigm_classes": [],
        }

        # Parse basic metadata (handle both cases and namespace)
        if ns:
            # With namespace
            experiment["title"] = exp_element.findtext(
                "bm:Title", namespaces=ns
            ) or exp_element.findtext("bm:title", "", namespaces=ns)
            experiment["authors"] = exp_element.findtext(
                "bm:Authors", namespaces=ns
            ) or exp_element.findtext("bm:authors", "", namespaces=ns)
            experiment["year"] = exp_element.findtext(
                "bm:Year", namespaces=ns
            ) or exp_element.findtext("bm:year", "", namespaces=ns)
            experiment["journal"] = exp_element.findtext(
                "bm:Journal", namespaces=ns
            ) or exp_element.findtext("bm:journal", "", namespaces=ns)
            experiment["pmid"] = exp_element.findtext(
                "bm:PMID", namespaces=ns
            ) or exp_element.findtext("bm:pmid", "", namespaces=ns)
            experiment["modality"] = exp_element.findtext(
                "bm:Modality", namespaces=ns
            ) or exp_element.findtext("bm:modality", "", namespaces=ns)
            experiment["paradigm"] = exp_element.findtext(
                "bm:Paradigm", namespaces=ns
            ) or exp_element.findtext("bm:paradigm", "", namespaces=ns)
        else:
            # Without namespace
            experiment["title"] = exp_element.findtext("Title") or exp_element.findtext(
                "title", ""
            )
            experiment["authors"] = exp_element.findtext(
                "Authors"
            ) or exp_element.findtext("authors", "")
            experiment["year"] = exp_element.findtext("Year") or exp_element.findtext(
                "year", ""
            )
            experiment["journal"] = exp_element.findtext(
                "Journal"
            ) or exp_element.findtext("journal", "")
            experiment["pmid"] = exp_element.findtext("PMID") or exp_element.findtext(
                "pmid", ""
            )
            experiment["modality"] = exp_element.findtext(
                "Modality"
            ) or exp_element.findtext("modality", "")
            experiment["paradigm"] = exp_element.findtext(
                "Paradigm"
            ) or exp_element.findtext("paradigm", "")

        # Parse paper reference (if separate element exists)
        paper = exp_element.find("paper") or exp_element.find("Paper")
        if paper is not None:
            experiment["paper"] = {
                "pmid": paper.get("pmid", "") or experiment.get("pmid", ""),
                "title": paper.findtext("title", "") or paper.findtext("Title", ""),
                "authors": paper.findtext("authors", "")
                or paper.findtext("Authors", ""),
                "year": paper.findtext("year", "") or paper.findtext("Year", ""),
            }
        else:
            # Create paper from metadata if PMID exists
            if experiment.get("pmid"):
                experiment["paper"] = {
                    "pmid": experiment["pmid"],
                    "title": experiment.get("title", ""),
                    "authors": experiment.get("authors", ""),
                    "year": experiment.get("year", ""),
                }

        # Parse contrasts (handle both cases and namespace)
        if ns:
            contrasts_container = exp_element.find(
                "bm:Contrasts", ns
            ) or exp_element.find("bm:contrasts", ns)
            if contrasts_container:
                for contrast in contrasts_container.findall(
                    "bm:Contrast", ns
                ) + contrasts_container.findall("bm:contrast", ns):
                    contrast_data = {
                        "id": contrast.get("id", ""),
                        "name": contrast.findtext("bm:Name", namespaces=ns)
                        or contrast.findtext("bm:name", "", namespaces=ns),
                        "type": contrast.findtext("bm:Type", namespaces=ns)
                        or contrast.findtext("bm:type", "", namespaces=ns),
                        "description": contrast.findtext(
                            "bm:Description", namespaces=ns
                        )
                        or contrast.findtext("bm:description", "", namespaces=ns),
                        "coordinates": [],
                    }

                    # Parse coordinates within contrast
                    coords_container = contrast.find(
                        "bm:Coordinates", ns
                    ) or contrast.find("bm:coordinates", ns)
                    if coords_container:
                        for coord in coords_container.findall(
                            "bm:Coordinate", ns
                        ) + coords_container.findall("bm:coordinate", ns):
                            coord_data = self._parse_coordinate(coord, ns)
                            if coord_data:
                                contrast_data["coordinates"].append(coord_data)
                                experiment["coordinates"].append(
                                    coord_data
                                )  # Also add to global coordinates

                    experiment["contrasts"].append(contrast_data)
        else:
            contrasts_container = exp_element.find("Contrasts") or exp_element.find(
                "contrasts"
            )
            if contrasts_container:
                for contrast in contrasts_container.findall(
                    "Contrast"
                ) + contrasts_container.findall("contrast"):
                    contrast_data = {
                        "id": contrast.get("id", ""),
                        "name": contrast.findtext("Name")
                        or contrast.findtext("name", ""),
                        "type": contrast.findtext("Type")
                        or contrast.findtext("type", ""),
                        "description": contrast.findtext("Description")
                        or contrast.findtext("description", ""),
                        "coordinates": [],
                    }

                    # Parse coordinates within contrast
                    coords_container = contrast.find("Coordinates") or contrast.find(
                        "coordinates"
                    )
                    if coords_container:
                        for coord in coords_container.findall(
                            "Coordinate"
                        ) + coords_container.findall("coordinate"):
                            coord_data = self._parse_coordinate(coord)
                            if coord_data:
                                contrast_data["coordinates"].append(coord_data)
                                experiment["coordinates"].append(
                                    coord_data
                                )  # Also add to global coordinates

                    experiment["contrasts"].append(contrast_data)

        # Parse global coordinates (if not in contrasts)
        for coord in exp_element.findall(".//coordinate") + exp_element.findall(
            ".//Coordinate"
        ):
            if coord.getparent().tag not in ["Coordinates", "coordinates"]:
                coord_data = self._parse_coordinate(coord)
                if coord_data:
                    experiment["coordinates"].append(coord_data)

        # Parse behavioral domains (handle both cases)
        domain_text = exp_element.findtext("BehavioralDomain") or exp_element.findtext(
            "behavioral_domain"
        )
        if domain_text:
            experiment["behavioral_domains"].append(domain_text)
        for domain in exp_element.findall(".//behavioral_domain") + exp_element.findall(
            ".//BehavioralDomain"
        ):
            if domain.text:
                experiment["behavioral_domains"].append(domain.text)

        # Parse paradigm classes
        for paradigm in exp_element.findall(".//paradigm_class") + exp_element.findall(
            ".//ParadigmClass"
        ):
            if paradigm.text:
                experiment["paradigm_classes"].append(paradigm.text)

        return experiment

    def _parse_text_workspace(self, workspace_path: str) -> list[dict[str, Any]]:
        """Parse custom text format workspace.

        Args:
            workspace_path: Path to workspace file

        Returns:
            List of parsed experiments
        """
        experiments = []
        current_exp = None

        with open(workspace_path) as f:
            for line in f:
                line = line.strip()

                if line.startswith("EXPERIMENT:"):
                    if current_exp:
                        experiments.append(current_exp)

                    exp_id = line.replace("EXPERIMENT:", "").strip()
                    current_exp = {
                        "experiment_id": exp_id,
                        "contrasts": [],
                        "coordinates": [],
                        "behavioral_domains": [],
                        "paradigm_classes": [],
                    }

                elif line.startswith("PMID:") and current_exp:
                    pmid = line.replace("PMID:", "").strip()
                    current_exp["paper"] = {"pmid": pmid}

                elif line.startswith("CONTRAST:") and current_exp:
                    contrast = line.replace("CONTRAST:", "").strip()
                    current_exp["contrasts"].append({"name": contrast})

                elif line.startswith("COORDINATE:") and current_exp:
                    coord_str = line.replace("COORDINATE:", "").strip()
                    coord = self._parse_coordinate_string(coord_str)
                    if coord:
                        current_exp["coordinates"].append(coord)

                elif line.startswith("DOMAIN:") and current_exp:
                    domain = line.replace("DOMAIN:", "").strip()
                    current_exp["behavioral_domains"].append(domain)

        if current_exp:
            experiments.append(current_exp)

        return experiments

    def _parse_coordinate(
        self, coord_element, ns: dict[str, str] = None
    ) -> dict[str, Any] | None:
        """Parse coordinate from XML element.

        Args:
            coord_element: XML element or dict
            ns: Optional namespace dict

        Returns:
            Parsed coordinate or None if invalid
        """
        if isinstance(coord_element, ET.Element):
            if ns:
                # Handle namespace
                x = float(
                    coord_element.findtext("bm:X", namespaces=ns)
                    or coord_element.findtext("bm:x", 0, namespaces=ns)
                )
                y = float(
                    coord_element.findtext("bm:Y", namespaces=ns)
                    or coord_element.findtext("bm:y", 0, namespaces=ns)
                )
                z = float(
                    coord_element.findtext("bm:Z", namespaces=ns)
                    or coord_element.findtext("bm:z", 0, namespaces=ns)
                )
                space = coord_element.findtext(
                    "bm:Space", namespaces=ns
                ) or coord_element.findtext("bm:space", "MNI", namespaces=ns)
            else:
                # Handle both uppercase and lowercase tags without namespace
                x = float(coord_element.findtext("X") or coord_element.findtext("x", 0))
                y = float(coord_element.findtext("Y") or coord_element.findtext("y", 0))
                z = float(coord_element.findtext("Z") or coord_element.findtext("z", 0))
                space = coord_element.findtext("Space") or coord_element.findtext(
                    "space", "MNI"
                )
        elif isinstance(coord_element, dict):
            x = float(coord_element.get("x", 0))
            y = float(coord_element.get("y", 0))
            z = float(coord_element.get("z", 0))
            space = coord_element.get("space", "MNI")
        else:
            return None

        # Validate coordinate
        if self._validate_coordinate(x, y, z, space):
            return {"x": x, "y": y, "z": z, "space": space}

        return None

    def _parse_coordinate_string(self, coord_str: str) -> dict[str, Any] | None:
        """Parse coordinate from string format.

        Args:
            coord_str: String like "(-45, 20, 8) MNI"

        Returns:
            Parsed coordinate or None
        """
        # Match patterns like "(-45, 20, 8) MNI" or "x=-45 y=20 z=8 space=MNI"
        pattern1 = r"\(([\-\d\.]+),\s*([\-\d\.]+),\s*([\-\d\.]+)\)\s*(\w+)?"
        pattern2 = r"x=([\-\d\.]+)\s+y=([\-\d\.]+)\s+z=([\-\d\.]+)(?:\s+space=(\w+))?"

        match = re.match(pattern1, coord_str)
        if match:
            x, y, z, space = match.groups()
            space = space or "MNI"
        else:
            match = re.match(pattern2, coord_str)
            if match:
                x, y, z, space = match.groups()
                space = space or "MNI"
            else:
                return None

        x, y, z = float(x), float(y), float(z)

        if self._validate_coordinate(x, y, z, space):
            return {"x": x, "y": y, "z": z, "space": space}

        return None

    def _validate_coordinate(self, x: float, y: float, z: float, space: str) -> bool:
        """Validate coordinate values.

        Args:
            x, y, z: Coordinate values
            space: Coordinate space

        Returns:
            True if valid
        """
        if space not in self.coordinate_spaces:
            return False

        bounds = self.coordinate_spaces[space]

        return (
            bounds["x"][0] <= x <= bounds["x"][1]
            and bounds["y"][0] <= y <= bounds["y"][1]
            and bounds["z"][0] <= z <= bounds["z"][1]
        )

    def convert_coordinate_space(
        self, coord: dict[str, Any], target_space: str = "MNI"
    ) -> dict[str, Any]:
        """Convert coordinate between spaces.

        Args:
            coord: Coordinate with x, y, z, space
            target_space: Target coordinate space

        Returns:
            Converted coordinate
        """
        if coord["space"] == target_space:
            return coord

        # Simplified conversion (should use proper transforms)
        if coord["space"] in ["TAL", "Talairach"] and target_space == "MNI":
            # Approximate Talairach to MNI conversion
            x = coord["x"] * 1.08
            y = coord["y"] * 1.08
            z = coord["z"] * 1.10
        elif coord["space"] == "MNI" and target_space in ["TAL", "Talairach"]:
            # Approximate MNI to Talairach conversion
            x = coord["x"] / 1.08
            y = coord["y"] / 1.08
            z = coord["z"] / 1.10
        else:
            return coord

        return {"x": x, "y": y, "z": z, "space": target_space}

    def parse_contrast_details(self, contrast_element) -> dict[str, Any]:
        """Extract detailed contrast information including statistics.

        Args:
            contrast_element: XML element, dict or string with contrast info

        Returns:
            Detailed contrast information
        """
        contrast = {
            "name": "",
            "description": "",
            "analysis_type": "activation",  # default
            "statistical_threshold": None,
            "correction_method": "uncorrected",  # default
            "n_subjects": 0,
            "n_experiments": 1,
            "anatomical_details": [],
        }

        if isinstance(contrast_element, ET.Element):
            contrast["name"] = contrast_element.findtext("name", "")
            contrast["description"] = contrast_element.findtext("description", "")
            contrast["analysis_type"] = contrast_element.findtext("type", "activation")

            # Parse statistical info
            stats = contrast_element.find("statistics")
            if stats is not None:
                contrast["statistical_threshold"] = float(
                    stats.findtext("threshold", 0)
                )
                contrast["correction_method"] = stats.findtext(
                    "correction", "uncorrected"
                )

            # Parse subject info
            contrast["n_subjects"] = int(contrast_element.findtext("n_subjects", 0))

        elif isinstance(contrast_element, dict):
            contrast.update(
                {k: v for k, v in contrast_element.items() if k in contrast}
            )

        elif isinstance(contrast_element, str):
            # Parse string format like "task > baseline (p<0.001, FWE)"
            contrast["name"] = contrast_element

            # Extract statistical info from string
            import re

            stat_match = re.search(r"p[<>]?([\d.]+)", contrast_element)
            if stat_match:
                contrast["statistical_threshold"] = float(stat_match.group(1))

            if "FWE" in contrast_element:
                contrast["correction_method"] = "FWE"
            elif "FDR" in contrast_element:
                contrast["correction_method"] = "FDR"

        return contrast

    def parse_behavioral_domain_hierarchy(self, domain_string: str) -> dict[str, Any]:
        """Parse hierarchical behavioral domain structure.

        Args:
            domain_string: Domain path like 'cognition.language.speech'

        Returns:
            Hierarchical domain structure
        """
        levels = domain_string.split(".")

        # Find parent and child domains
        parent_domains = []
        child_domains = []

        if len(levels) > 1:
            parent_domains = [".".join(levels[:i]) for i in range(1, len(levels))]

        # Check if it's a known domain category
        base_domain = levels[0] if levels else ""
        if base_domain in self.behavioral_domains_taxonomy:
            known_subdomains = self.behavioral_domains_taxonomy[base_domain]
            if len(levels) == 1:
                child_domains = [f"{base_domain}.{sub}" for sub in known_subdomains]

        return {
            "full_path": domain_string,
            "levels": levels,
            "depth": len(levels),
            "parent_domains": parent_domains,
            "child_domains": child_domains,
            "base_category": base_domain,
        }

    def parse_study_metadata(self, study_element) -> dict[str, Any]:
        """Extract comprehensive study metadata.

        Args:
            study_element: Study information element

        Returns:
            Study metadata dictionary
        """
        metadata = {
            "study_design": "block",  # default
            "imaging_modality": "fMRI",  # default
            "field_strength": 3.0,  # default Tesla
            "analysis_software": [],
            "demographic_info": {},
            "exclusion_criteria": [],
        }

        if isinstance(study_element, ET.Element):
            # Parse design info
            metadata["study_design"] = study_element.findtext("design", "block")
            metadata["imaging_modality"] = study_element.findtext("modality", "fMRI")

            # Parse scanner info
            scanner = study_element.find("scanner")
            if scanner is not None:
                metadata["field_strength"] = float(
                    scanner.findtext("field_strength", 3.0)
                )

            # Parse software
            for software in study_element.findall(".//software"):
                metadata["analysis_software"].append(software.text)

            # Parse demographics
            demo = study_element.find("demographics")
            if demo is not None:
                metadata["demographic_info"] = {
                    "n_subjects": int(demo.findtext("n_subjects", 0)),
                    "mean_age": float(demo.findtext("mean_age", 0)),
                    "age_range": demo.findtext("age_range", ""),
                    "gender_ratio": demo.findtext("gender_ratio", ""),
                }

        elif isinstance(study_element, dict):
            metadata.update({k: v for k, v in study_element.items() if k in metadata})

        return metadata

    def parse_experiment_full(self, exp_data: dict[str, Any]) -> dict[str, Any]:
        """Parse complete experiment with all details.

        Args:
            exp_data: Raw experiment data

        Returns:
            Fully parsed experiment
        """
        experiment = exp_data.copy()

        # Parse contrasts with details
        if "contrasts" in experiment:
            detailed_contrasts = []
            for contrast in experiment["contrasts"]:
                detailed_contrasts.append(self.parse_contrast_details(contrast))
            experiment["contrasts"] = detailed_contrasts

        # Parse behavioral domains with hierarchy
        if "behavioral_domains" in experiment:
            hierarchical_domains = []
            for domain in experiment["behavioral_domains"]:
                hierarchical_domains.append(
                    self.parse_behavioral_domain_hierarchy(domain)
                )
            experiment["behavioral_domain_hierarchy"] = hierarchical_domains

        # Add study metadata if available
        if "study_info" in experiment:
            experiment["study_metadata"] = self.parse_study_metadata(
                experiment["study_info"]
            )

        return experiment
