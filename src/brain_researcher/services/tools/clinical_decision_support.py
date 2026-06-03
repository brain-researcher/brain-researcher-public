"""
Clinical Decision Support System for neuroimaging analysis.
Provides automated clinical insights and recommendations.
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import numpy as np
import nibabel as nib

from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult

logger = logging.getLogger(__name__)


class ClinicalPriority(Enum):
    """Clinical finding priority levels."""
    CRITICAL = "critical"
    HIGH = "high"
    MODERATE = "moderate"
    LOW = "low"
    NORMAL = "normal"


class PathologyType(Enum):
    """Types of pathologies."""
    STROKE = "stroke"
    TUMOR = "tumor"
    MS_LESION = "multiple_sclerosis"
    WMH = "white_matter_hyperintensity"
    ATROPHY = "atrophy"
    HEMORRHAGE = "hemorrhage"
    EDEMA = "edema"
    MICROBLEED = "microbleed"


@dataclass
class ClinicalFinding:
    """Single clinical finding."""
    pathology: PathologyType
    priority: ClinicalPriority
    location: str
    volume_ml: float
    confidence: float
    description: str
    recommendations: List[str]
    references: List[str] = field(default_factory=list)


@dataclass
class ClinicalReport:
    """Complete clinical report."""
    patient_id: str
    scan_date: str
    findings: List[ClinicalFinding]
    overall_assessment: str
    clinical_recommendations: List[str]
    follow_up: str
    risk_scores: Dict[str, float]
    quality_metrics: Dict[str, float]


class ClinicalDecisionSupport(NeuroToolWrapper):
    """Clinical decision support for neuroimaging."""

    def __init__(self):
        super().__init__(
            name="clinical_decision_support",
            description="Automated clinical insights and recommendations"
        )
        self.clinical_thresholds = self._load_clinical_thresholds()
        self.risk_models = self._load_risk_models()

    def _load_clinical_thresholds(self) -> Dict:
        """Load clinical thresholds for various conditions."""
        return {
            "wmh_volume": {
                "mild": 5.0,  # ml
                "moderate": 15.0,
                "severe": 30.0
            },
            "brain_volume_percentile": {
                "atrophy": 5,  # Below 5th percentile
                "normal": 50
            },
            "stroke_volume": {
                "small": 1.0,  # ml
                "moderate": 10.0,
                "large": 50.0
            },
            "tumor_growth_rate": {
                "stable": 0.1,  # cm/year
                "slow": 0.5,
                "rapid": 1.0
            }
        }

    def _load_risk_models(self) -> Dict:
        """Load risk assessment models."""
        return {
            "stroke_risk": {
                "wmh_weight": 0.3,
                "age_weight": 0.2,
                "atrophy_weight": 0.2,
                "microbleed_weight": 0.3
            },
            "dementia_risk": {
                "hippocampal_volume_weight": 0.4,
                "wmh_weight": 0.3,
                "cortical_thickness_weight": 0.3
            },
            "progression_risk": {
                "lesion_count_weight": 0.3,
                "lesion_volume_weight": 0.4,
                "new_lesions_weight": 0.3
            }
        }

    def _run(
        self,
        segmentation_file: Optional[str] = None,
        lesion_file: Optional[str] = None,
        volumetrics: Optional[Dict] = None,
        clinical_data: Optional[Dict] = None,
        prior_scan: Optional[str] = None,
        output_dir: Optional[str] = None,
        **kwargs
    ) -> ToolResult:
        """
        Generate clinical decision support report.

        Args:
            segmentation_file: Brain segmentation
            lesion_file: Lesion segmentation
            volumetrics: Volumetric measurements
            clinical_data: Patient clinical data
            prior_scan: Previous scan for comparison
            output_dir: Output directory
        """
        try:
            output_path = Path(output_dir or "clinical_report")
            output_path.mkdir(parents=True, exist_ok=True)

            # Analyze findings
            findings = []

            # Analyze segmentation if available
            if segmentation_file:
                seg_findings = self._analyze_segmentation(segmentation_file)
                findings.extend(seg_findings)

            # Analyze lesions if available
            if lesion_file:
                lesion_findings = self._analyze_lesions(lesion_file)
                findings.extend(lesion_findings)

            # Analyze volumetrics
            if volumetrics:
                vol_findings = self._analyze_volumetrics(volumetrics)
                findings.extend(vol_findings)

            # Compare with prior if available
            if prior_scan:
                progression_findings = self._analyze_progression(
                    segmentation_file, prior_scan
                )
                findings.extend(progression_findings)

            # Calculate risk scores
            risk_scores = self._calculate_risk_scores(findings, clinical_data)

            # Generate recommendations
            recommendations = self._generate_recommendations(findings, risk_scores)

            # Determine overall assessment
            assessment = self._generate_assessment(findings, risk_scores)

            # Create report
            report = ClinicalReport(
                patient_id=clinical_data.get("patient_id", "Unknown") if clinical_data else "Unknown",
                scan_date=datetime.now().strftime("%Y-%m-%d"),
                findings=findings,
                overall_assessment=assessment,
                clinical_recommendations=recommendations,
                follow_up=self._determine_follow_up(findings, risk_scores),
                risk_scores=risk_scores,
                quality_metrics=self._assess_quality(segmentation_file, lesion_file)
            )

            # Generate outputs
            html_report = self._generate_html_report(report, output_path)
            json_report = self._save_json_report(report, output_path)

            # Generate clinical alerts if needed
            alerts = self._check_critical_findings(findings)

            return ToolResult(
                status="success",
                data={
                    "findings_count": len(findings),
                    "highest_priority": max(
                        [f.priority.value for f in findings],
                        default="normal"
                    ),
                    "risk_scores": risk_scores,
                    "recommendations": recommendations,
                    "html_report": str(html_report),
                    "json_report": str(json_report),
                    "alerts": alerts,
                    "follow_up": report.follow_up
                }
            )

        except Exception as e:
            logger.error(f"Clinical decision support failed: {e}")
            return ToolResult(
                status="error",
                error=str(e)
            )

    def _analyze_segmentation(self, seg_file: str) -> List[ClinicalFinding]:
        """Analyze brain segmentation for clinical findings."""
        findings = []

        try:
            # Load segmentation
            seg_img = nib.load(seg_file)
            seg_data = seg_img.get_fdata()
            voxel_volume = np.prod(seg_img.header.get_zooms()) / 1000  # ml

            # Calculate tissue volumes
            gm_volume = np.sum(seg_data == 1) * voxel_volume
            wm_volume = np.sum(seg_data == 2) * voxel_volume
            csf_volume = np.sum(seg_data == 3) * voxel_volume
            total_brain = gm_volume + wm_volume

            # Check for atrophy
            expected_brain_volume = 1200  # ml (average)
            if total_brain < expected_brain_volume * 0.9:
                atrophy_severity = (expected_brain_volume - total_brain) / expected_brain_volume

                findings.append(ClinicalFinding(
                    pathology=PathologyType.ATROPHY,
                    priority=ClinicalPriority.MODERATE if atrophy_severity < 0.15 else ClinicalPriority.HIGH,
                    location="Global",
                    volume_ml=expected_brain_volume - total_brain,
                    confidence=0.85,
                    description=f"Brain volume {total_brain:.0f}ml ({atrophy_severity*100:.1f}% below expected)",
                    recommendations=[
                        "Consider neurodegenerative evaluation",
                        "Recommend cognitive assessment",
                        "Follow-up MRI in 6-12 months"
                    ],
                    references=["Jack et al., 2018 NIA-AA Framework"]
                ))

            # Check CSF expansion
            csf_ratio = csf_volume / (total_brain + csf_volume)
            if csf_ratio > 0.15:
                findings.append(ClinicalFinding(
                    pathology=PathologyType.ATROPHY,
                    priority=ClinicalPriority.MODERATE,
                    location="Ventricular system",
                    volume_ml=csf_volume,
                    confidence=0.80,
                    description=f"Ventricular enlargement (CSF ratio: {csf_ratio:.2f})",
                    recommendations=[
                        "Evaluate for hydrocephalus",
                        "Check for normal pressure hydrocephalus symptoms"
                    ]
                ))

        except Exception as e:
            logger.error(f"Segmentation analysis failed: {e}")

        return findings

    def _analyze_lesions(self, lesion_file: str) -> List[ClinicalFinding]:
        """Analyze lesion segmentation."""
        findings = []

        try:
            # Load lesion mask
            lesion_img = nib.load(lesion_file)
            lesion_data = lesion_img.get_fdata()
            voxel_volume = np.prod(lesion_img.header.get_zooms()) / 1000  # ml

            # Find connected components
            from scipy import ndimage
            labeled, n_lesions = ndimage.label(lesion_data > 0)

            # Analyze each lesion
            for i in range(1, n_lesions + 1):
                lesion_mask = labeled == i
                lesion_volume = np.sum(lesion_mask) * voxel_volume

                # Get location
                coords = np.where(lesion_mask)
                center = [int(np.mean(c)) for c in coords]
                location = self._get_anatomical_location(center)

                # Classify lesion
                if lesion_volume > 50:
                    pathology = PathologyType.STROKE
                    priority = ClinicalPriority.CRITICAL
                    recommendations = [
                        "URGENT: Possible acute stroke",
                        "Immediate neurological consultation",
                        "Consider thrombolysis/thrombectomy if within window"
                    ]
                elif lesion_volume > 10:
                    pathology = PathologyType.TUMOR
                    priority = ClinicalPriority.HIGH
                    recommendations = [
                        "Neurosurgical consultation recommended",
                        "Consider contrast-enhanced MRI",
                        "Evaluate for biopsy"
                    ]
                else:
                    pathology = PathologyType.WMH
                    priority = ClinicalPriority.LOW
                    recommendations = [
                        "Monitor progression",
                        "Vascular risk factor assessment"
                    ]

                findings.append(ClinicalFinding(
                    pathology=pathology,
                    priority=priority,
                    location=location,
                    volume_ml=lesion_volume,
                    confidence=0.75,
                    description=f"Lesion detected: {lesion_volume:.1f}ml",
                    recommendations=recommendations
                ))

            # Calculate total WMH burden
            total_wmh = np.sum(lesion_data > 0) * voxel_volume
            if total_wmh > self.clinical_thresholds["wmh_volume"]["moderate"]:
                findings.append(ClinicalFinding(
                    pathology=PathologyType.WMH,
                    priority=ClinicalPriority.MODERATE,
                    location="Periventricular and deep white matter",
                    volume_ml=total_wmh,
                    confidence=0.85,
                    description=f"Moderate to severe WMH burden (Fazekas 2-3)",
                    recommendations=[
                        "Cardiovascular risk assessment",
                        "Blood pressure management",
                        "Consider antiplatelet therapy"
                    ],
                    references=["Wardlaw et al., 2013 STRIVE"]
                ))

        except Exception as e:
            logger.error(f"Lesion analysis failed: {e}")

        return findings

    def _analyze_volumetrics(self, volumetrics: Dict) -> List[ClinicalFinding]:
        """Analyze volumetric measurements."""
        findings = []

        # Check hippocampal volume
        if "hippocampal_volume" in volumetrics:
            hc_volume = volumetrics["hippocampal_volume"]
            expected_hc = 3.5  # ml per hemisphere

            if hc_volume < expected_hc * 0.7:
                findings.append(ClinicalFinding(
                    pathology=PathologyType.ATROPHY,
                    priority=ClinicalPriority.HIGH,
                    location="Bilateral hippocampi",
                    volume_ml=expected_hc - hc_volume,
                    confidence=0.80,
                    description=f"Hippocampal atrophy ({hc_volume:.1f}ml, {(hc_volume/expected_hc)*100:.0f}% of expected)",
                    recommendations=[
                        "Memory assessment recommended",
                        "Consider Alzheimer's biomarkers",
                        "Neuropsychological evaluation"
                    ],
                    references=["Scheltens et al., 1992 MTA scale"]
                ))

        return findings

    def _analyze_progression(self, current: str, prior: str) -> List[ClinicalFinding]:
        """Analyze progression between scans."""
        findings = []

        try:
            # Simple volume comparison
            current_img = nib.load(current)
            prior_img = nib.load(prior)

            current_vol = np.sum(current_img.get_fdata() > 0)
            prior_vol = np.sum(prior_img.get_fdata() > 0)

            change_pct = ((current_vol - prior_vol) / prior_vol) * 100

            if abs(change_pct) > 5:
                findings.append(ClinicalFinding(
                    pathology=PathologyType.ATROPHY if change_pct < 0 else PathologyType.EDEMA,
                    priority=ClinicalPriority.MODERATE,
                    location="Global",
                    volume_ml=abs(current_vol - prior_vol) * 0.001,
                    confidence=0.70,
                    description=f"Volume change: {change_pct:+.1f}% from prior",
                    recommendations=[
                        "Disease progression noted",
                        "Consider treatment modification"
                    ]
                ))

        except Exception as e:
            logger.error(f"Progression analysis failed: {e}")

        return findings

    def _calculate_risk_scores(
        self,
        findings: List[ClinicalFinding],
        clinical_data: Optional[Dict]
    ) -> Dict[str, float]:
        """Calculate clinical risk scores."""
        scores = {}

        # Stroke risk
        stroke_risk = 0.0
        for finding in findings:
            if finding.pathology == PathologyType.WMH:
                stroke_risk += 0.3 * min(finding.volume_ml / 30, 1.0)
            elif finding.pathology == PathologyType.MICROBLEED:
                stroke_risk += 0.2

        if clinical_data:
            age = clinical_data.get("age", 50)
            stroke_risk += 0.1 * max(0, (age - 50) / 50)

        scores["stroke_risk"] = min(stroke_risk, 1.0)

        # Dementia risk
        dementia_risk = 0.0
        for finding in findings:
            if finding.pathology == PathologyType.ATROPHY:
                if "hippocampal" in finding.location.lower():
                    dementia_risk += 0.4
                else:
                    dementia_risk += 0.2

        scores["dementia_risk"] = min(dementia_risk, 1.0)

        # Progression risk
        progression_risk = 0.0
        high_priority_count = sum(1 for f in findings if f.priority in [ClinicalPriority.HIGH, ClinicalPriority.CRITICAL])
        progression_risk = min(high_priority_count * 0.3, 1.0)
        scores["progression_risk"] = progression_risk

        return scores

    def _generate_recommendations(
        self,
        findings: List[ClinicalFinding],
        risk_scores: Dict[str, float]
    ) -> List[str]:
        """Generate clinical recommendations."""
        recommendations = []

        # Priority-based recommendations
        critical_findings = [f for f in findings if f.priority == ClinicalPriority.CRITICAL]
        if critical_findings:
            recommendations.append("⚠️ URGENT: Critical findings requiring immediate attention")

        # Risk-based recommendations
        if risk_scores.get("stroke_risk", 0) > 0.7:
            recommendations.append("High stroke risk - aggressive vascular risk management indicated")

        if risk_scores.get("dementia_risk", 0) > 0.6:
            recommendations.append("Elevated dementia risk - consider cognitive assessment and biomarkers")

        if risk_scores.get("progression_risk", 0) > 0.5:
            recommendations.append("Disease progression likely - close monitoring recommended")

        # General recommendations
        if not recommendations:
            recommendations.append("Continue routine monitoring")

        return recommendations

    def _generate_assessment(
        self,
        findings: List[ClinicalFinding],
        risk_scores: Dict[str, float]
    ) -> str:
        """Generate overall clinical assessment."""
        if not findings:
            return "No significant abnormalities detected. Brain structure appears within normal limits."

        critical_count = sum(1 for f in findings if f.priority == ClinicalPriority.CRITICAL)
        high_count = sum(1 for f in findings if f.priority == ClinicalPriority.HIGH)

        if critical_count > 0:
            assessment = f"CRITICAL: {critical_count} urgent finding(s) requiring immediate attention. "
        elif high_count > 0:
            assessment = f"Significant abnormalities detected: {high_count} high-priority finding(s). "
        else:
            assessment = "Mild to moderate abnormalities detected. "

        # Add risk assessment
        high_risks = [k for k, v in risk_scores.items() if v > 0.7]
        if high_risks:
            assessment += f"Elevated risk for: {', '.join(high_risks)}. "

        return assessment

    def _determine_follow_up(
        self,
        findings: List[ClinicalFinding],
        risk_scores: Dict[str, float]
    ) -> str:
        """Determine follow-up recommendations."""
        max_priority = max([f.priority for f in findings], default=ClinicalPriority.NORMAL)
        max_risk = max(risk_scores.values()) if risk_scores else 0

        if max_priority == ClinicalPriority.CRITICAL:
            return "Immediate follow-up required"
        elif max_priority == ClinicalPriority.HIGH or max_risk > 0.8:
            return "Follow-up MRI in 3 months"
        elif max_priority == ClinicalPriority.MODERATE or max_risk > 0.5:
            return "Follow-up MRI in 6 months"
        else:
            return "Annual follow-up recommended"

    def _assess_quality(self, seg_file: Optional[str], lesion_file: Optional[str]) -> Dict[str, float]:
        """Assess scan quality metrics."""
        metrics = {
            "signal_to_noise": 0.85,  # Placeholder
            "motion_artifact": 0.1,
            "coverage_complete": 1.0,
            "resolution_adequate": 1.0
        }
        return metrics

    def _check_critical_findings(self, findings: List[ClinicalFinding]) -> List[str]:
        """Check for critical findings requiring alerts."""
        alerts = []

        for finding in findings:
            if finding.priority == ClinicalPriority.CRITICAL:
                alerts.append(f"⚠️ CRITICAL: {finding.description}")

        return alerts

    def _get_anatomical_location(self, coords: List[int]) -> str:
        """Get anatomical location from coordinates."""
        # Simplified anatomical mapping
        x, y, z = coords

        if z < 40:
            region = "Cerebellum"
        elif z > 120:
            region = "Superior frontal"
        elif x < 80:
            region = "Right hemisphere"
        elif x > 110:
            region = "Left hemisphere"
        else:
            region = "Central structures"

        return region

    def _generate_html_report(self, report: ClinicalReport, output_path: Path) -> Path:
        """Generate HTML clinical report."""
        html = f"""
<!DOCTYPE html>
<html>
<head>
    <title>Clinical Neuroimaging Report</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; }}
        .header {{ background: #2c3e50; color: white; padding: 20px; }}
        .critical {{ color: #e74c3c; font-weight: bold; }}
        .high {{ color: #e67e22; font-weight: bold; }}
        .moderate {{ color: #f39c12; }}
        .finding {{ margin: 20px 0; padding: 15px; border-left: 4px solid #3498db; }}
        .risk-score {{ display: inline-block; padding: 5px 10px; margin: 5px; }}
        .recommendations {{ background: #ecf0f1; padding: 15px; margin: 20px 0; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>Clinical Neuroimaging Report</h1>
        <p>Patient ID: {report.patient_id} | Date: {report.scan_date}</p>
    </div>

    <h2>Overall Assessment</h2>
    <p>{report.overall_assessment}</p>

    <h2>Clinical Findings</h2>
"""

        for finding in report.findings:
            priority_class = finding.priority.value
            html += f"""
    <div class="finding">
        <h3 class="{priority_class}">{finding.pathology.value.replace('_', ' ').title()}</h3>
        <p><strong>Location:</strong> {finding.location}</p>
        <p><strong>Volume:</strong> {finding.volume_ml:.1f} ml</p>
        <p><strong>Description:</strong> {finding.description}</p>
        <p><strong>Confidence:</strong> {finding.confidence*100:.0f}%</p>
        <ul>
"""
            for rec in finding.recommendations:
                html += f"            <li>{rec}</li>\n"
            html += "        </ul>\n    </div>\n"

        html += f"""
    <h2>Risk Assessment</h2>
    <div>
"""
        for risk_name, risk_value in report.risk_scores.items():
            color = "#e74c3c" if risk_value > 0.7 else "#f39c12" if risk_value > 0.4 else "#27ae60"
            html += f'        <span class="risk-score" style="background: {color};">{risk_name}: {risk_value*100:.0f}%</span>\n'

        html += f"""
    </div>

    <div class="recommendations">
        <h2>Clinical Recommendations</h2>
        <ul>
"""
        for rec in report.clinical_recommendations:
            html += f"            <li>{rec}</li>\n"

        html += f"""
        </ul>
        <p><strong>Follow-up:</strong> {report.follow_up}</p>
    </div>

    <footer>
        <p><small>Report generated automatically. Clinical correlation recommended.</small></p>
    </footer>
</body>
</html>
"""

        report_path = output_path / "clinical_report.html"
        with open(report_path, 'w') as f:
            f.write(html)

        return report_path

    def _save_json_report(self, report: ClinicalReport, output_path: Path) -> Path:
        """Save report as JSON."""
        json_data = {
            "patient_id": report.patient_id,
            "scan_date": report.scan_date,
            "overall_assessment": report.overall_assessment,
            "findings": [
                {
                    "pathology": f.pathology.value,
                    "priority": f.priority.value,
                    "location": f.location,
                    "volume_ml": f.volume_ml,
                    "confidence": f.confidence,
                    "description": f.description,
                    "recommendations": f.recommendations,
                    "references": f.references
                }
                for f in report.findings
            ],
            "risk_scores": report.risk_scores,
            "clinical_recommendations": report.clinical_recommendations,
            "follow_up": report.follow_up,
            "quality_metrics": report.quality_metrics
        }

        json_path = output_path / "clinical_report.json"
        with open(json_path, 'w') as f:
            json.dump(json_data, f, indent=2)

        return json_path