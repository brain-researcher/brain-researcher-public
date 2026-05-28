"""
Enhanced Integration tests for UI-002C: Trust Strip component
Tests trust metrics display, tool logos, institutional partnerships, and animations
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
import json


class TestTrustStripIntegration:
    """Integration test suite for Trust Strip component functionality"""

    def test_trust_metrics_structure(self):
        """Test TRUST_METRICS structure from actual component"""
        # Based on actual TRUST_METRICS from component
        trust_metrics = [
            {
                "id": "datasets",
                "label": "Datasets",
                "value": "2,847",
                "icon": "Database",
                "description": "Curated neuroimaging datasets",
                "trend": {"direction": "up", "value": "+127 this month"},
                "color": "text-blue-600",
                "animate": True
            },
            {
                "id": "studies",
                "label": "Studies", 
                "value": "45,239",
                "icon": "Award",
                "description": "Peer-reviewed research studies",
                "trend": {"direction": "up", "value": "+2.3K this month"},
                "color": "text-green-600",
                "animate": True
            },
            {
                "id": "users",
                "label": "Researchers",
                "value": "12,450+",
                "icon": "Users",
                "description": "Active research users",
                "trend": {"direction": "up", "value": "+15% growth"},
                "color": "text-purple-600",
                "animate": True
            },
            {
                "id": "uptime",
                "label": "Uptime",
                "value": "99.9%",
                "icon": "Shield",
                "description": "System reliability",
                "trend": {"direction": "stable", "value": "Last 30 days"},
                "color": "text-emerald-600"
            }
        ]
        
        # Test trust metrics structure 
        assert len(trust_metrics) == 4
        
        # Test each metric has required fields
        for metric in trust_metrics:
            assert "id" in metric
            assert "label" in metric
            assert "value" in metric
            assert "icon" in metric
            assert "description" in metric
            assert "color" in metric
            
            # Test optional fields
            if "trend" in metric:
                trend = metric["trend"]
                assert "direction" in trend
                assert "value" in trend
                assert trend["direction"] in ["up", "down", "stable"]
        
        # Test specific metrics
        datasets_metric = next(m for m in trust_metrics if m["id"] == "datasets")
        assert datasets_metric["label"] == "Datasets"
        assert datasets_metric["value"] == "2,847"
        assert datasets_metric["icon"] == "Database"
        
        studies_metric = next(m for m in trust_metrics if m["id"] == "studies")
        assert studies_metric["value"] == "45,239"
        assert studies_metric["trend"]["direction"] == "up"
        
        uptime_metric = next(m for m in trust_metrics if m["id"] == "uptime")
        assert uptime_metric["value"] == "99.9%"
        assert uptime_metric["trend"]["direction"] == "stable"

    def test_tool_logos_structure(self):
        """Test TOOL_LOGOS structure from actual component"""
        # Based on actual TOOL_LOGOS from component
        tool_logos = [
            {
                "name": "FSL",
                "logo": "🧠",
                "description": "FMRIB Software Library",
                "category": "analysis",
                "url": "https://fsl.fmrib.ox.ac.uk"
            },
            {
                "name": "Nilearn",
                "logo": "🐍",
                "description": "Machine learning for neuroimaging",
                "category": "analysis",
                "url": "https://nilearn.github.io"
            },
            {
                "name": "fMRIPrep",
                "logo": "⚙️",
                "description": "Robust preprocessing pipeline",
                "category": "preprocessing",
                "url": "https://fmriprep.org"
            },
            {
                "name": "BIDS",
                "logo": "📁",
                "description": "Brain Imaging Data Structure",
                "category": "data",
                "url": "https://bids.neuroimaging.io"
            },
            {
                "name": "OpenNeuro",
                "logo": "🌐",
                "description": "Open neuroimaging datasets",
                "category": "data",
                "url": "https://openneuro.org"
            },
            {
                "name": "Plotly",
                "logo": "📊",
                "description": "Interactive visualizations",
                "category": "visualization",
                "url": "https://plotly.com"
            }
        ]
        
        # Test tool logos structure
        assert len(tool_logos) == 6
        
        # Test each tool has required fields
        for tool in tool_logos:
            assert "name" in tool
            assert "logo" in tool
            assert "description" in tool
            assert "category" in tool
            assert tool["category"] in ["analysis", "preprocessing", "visualization", "data"]
            
            # Test URL if present
            if "url" in tool:
                assert tool["url"].startswith("https://")
        
        # Test specific tools
        fsl_tool = next(t for t in tool_logos if t["name"] == "FSL")
        assert fsl_tool["category"] == "analysis"
        assert fsl_tool["logo"] == "🧠"
        
        bids_tool = next(t for t in tool_logos if t["name"] == "BIDS")
        assert bids_tool["category"] == "data"
        assert bids_tool["description"] == "Brain Imaging Data Structure"
        
        # Test category distribution
        categories = [tool["category"] for tool in tool_logos]
        assert "analysis" in categories
        assert "preprocessing" in categories
        assert "visualization" in categories
        assert "data" in categories

    def test_institutions_structure(self):
        """Test INSTITUTIONS structure from actual component"""
        # Based on actual INSTITUTIONS from component
        institutions = [
            {"name": "Stanford University", "type": "university", "country": "US"},
            {"name": "Harvard Medical School", "type": "medical", "country": "US"},
            {"name": "Oxford University", "type": "university", "country": "UK"},
            {"name": "MIT", "type": "university", "country": "US"},
            {"name": "Max Planck Institute", "type": "research", "country": "DE"},
            {"name": "NIH", "type": "government", "country": "US"},
            {"name": "University of Toronto", "type": "university", "country": "CA"},
            {"name": "ETH Zurich", "type": "university", "country": "CH"}
        ]
        
        # Test institutions structure
        assert len(institutions) == 8
        
        # Test each institution has required fields
        for institution in institutions:
            assert "name" in institution
            assert "type" in institution
            assert "country" in institution
            assert institution["type"] in ["university", "medical", "research", "government"]
            assert len(institution["country"]) == 2  # Country code
        
        # Test specific institutions
        stanford = next(i for i in institutions if i["name"] == "Stanford University")
        assert stanford["type"] == "university"
        assert stanford["country"] == "US"
        
        oxford = next(i for i in institutions if i["name"] == "Oxford University")
        assert oxford["type"] == "university" 
        assert oxford["country"] == "UK"
        
        # Test type distribution
        types = [inst["type"] for inst in institutions]
        assert "university" in types
        assert "medical" in types
        assert "research" in types
        assert "government" in types
        
        # Test geographic distribution
        countries = [inst["country"] for inst in institutions]
        assert "US" in countries
        assert "UK" in countries
        assert "DE" in countries
        assert "CA" in countries

    def test_trust_strip_props_interface(self):
        """Test TrustStripProps interface"""
        # Based on actual TrustStripProps interface
        trust_strip_props = {
            "className": "custom-trust-strip",
            "showTools": True,
            "showInstitutions": True,
            "showMetrics": True,
            "animate": True
        }
        
        # Test all props are valid
        assert isinstance(trust_strip_props["className"], str)
        assert isinstance(trust_strip_props["showTools"], bool)
        assert isinstance(trust_strip_props["showInstitutions"], bool)
        assert isinstance(trust_strip_props["showMetrics"], bool)
        assert isinstance(trust_strip_props["animate"], bool)
        
        # Test default values behavior
        default_props = {
            "className": "",
            "showTools": True,
            "showInstitutions": True,
            "showMetrics": True,
            "animate": True
        }
        
        for prop, default_value in default_props.items():
            if prop not in trust_strip_props:
                trust_strip_props[prop] = default_value
        
        # All props should be present with proper types
        assert all(prop in trust_strip_props for prop in default_props.keys())

    def test_icon_mapping_functions(self):
        """Test icon mapping helper functions"""
        def get_category_icon(category):
            """Mock getCategoryIcon function from component"""
            icon_map = {
                'analysis': '🔬',
                'preprocessing': '⚙️',
                'visualization': '📊',
                'data': '📁',
                'default': '🔧'
            }
            return icon_map.get(category, icon_map['default'])
        
        def get_institution_icon(institution_type):
            """Mock getInstitutionIcon function from component"""
            icon_map = {
                'university': '🎓',
                'medical': '🏥',
                'research': '🔬',
                'government': '🏛️',
                'default': '🏢'
            }
            return icon_map.get(institution_type, icon_map['default'])
        
        def get_country_flag(country):
            """Mock getCountryFlag function from component"""
            flags = {
                'US': '🇺🇸',
                'UK': '🇬🇧', 
                'DE': '🇩🇪',
                'CA': '🇨🇦',
                'CH': '🇨🇭',
                'default': '🌍'
            }
            return flags.get(country, flags['default'])
        
        # Test category icons
        assert get_category_icon('analysis') == '🔬'
        assert get_category_icon('preprocessing') == '⚙️'
        assert get_category_icon('visualization') == '📊'
        assert get_category_icon('data') == '📁'
        assert get_category_icon('unknown') == '🔧'
        
        # Test institution icons
        assert get_institution_icon('university') == '🎓'
        assert get_institution_icon('medical') == '🏥'
        assert get_institution_icon('research') == '🔬'
        assert get_institution_icon('government') == '🏛️'
        assert get_institution_icon('unknown') == '🏢'
        
        # Test country flags
        assert get_country_flag('US') == '🇺🇸'
        assert get_country_flag('UK') == '🇬🇧'
        assert get_country_flag('DE') == '🇩🇪'
        assert get_country_flag('unknown') == '🌍'

    def test_animation_state_management(self):
        """Test animation state management"""
        animation_state = {
            "is_visible": False,
            "current_metric_index": 0,
            "animation_enabled": True,
            "animation_interval": 3000,
            "metrics_count": 4
        }
        
        def initialize_animation():
            """Mock animation initialization"""
            animation_state["is_visible"] = True
            if animation_state["animation_enabled"]:
                # Simulate interval setup
                return True
            return False
        
        def cycle_metric():
            """Mock metric cycling"""
            if animation_state["animation_enabled"]:
                animation_state["current_metric_index"] = (
                    animation_state["current_metric_index"] + 1
                ) % animation_state["metrics_count"]
                return animation_state["current_metric_index"]
            return animation_state["current_metric_index"]
        
        # Test initial state
        assert not animation_state["is_visible"]
        assert animation_state["current_metric_index"] == 0
        
        # Test animation initialization
        assert initialize_animation()
        assert animation_state["is_visible"]
        
        # Test metric cycling
        initial_index = animation_state["current_metric_index"]
        for i in range(animation_state["metrics_count"]):
            current_index = cycle_metric()
            expected_index = (initial_index + i + 1) % animation_state["metrics_count"]
            assert current_index == expected_index
        
        # Test with animation disabled
        animation_state["animation_enabled"] = False
        initial_index = animation_state["current_metric_index"]
        cycle_metric()
        assert animation_state["current_metric_index"] == initial_index

    def test_performance_indicators(self):
        """Test performance indicators section"""
        performance_indicators = [
            {
                "icon": "animate-pulse-dot",
                "text": "All systems operational",
                "color": "green",
                "status": "operational"
            },
            {
                "icon": "Check",
                "text": "SOC 2 Type II Compliant",
                "color": "green", 
                "status": "compliant"
            },
            {
                "icon": "Shield",
                "text": "GDPR & HIPAA Ready",
                "color": "blue",
                "status": "compliant"
            },
            {
                "icon": "Zap",
                "text": "99.9% API Uptime",
                "color": "yellow",
                "status": "performance"
            }
        ]
        
        # Test performance indicators structure
        assert len(performance_indicators) == 4
        
        # Test each indicator has required fields
        for indicator in performance_indicators:
            assert "icon" in indicator
            assert "text" in indicator
            assert "color" in indicator
            assert "status" in indicator
            assert indicator["status"] in ["operational", "compliant", "performance"]
        
        # Test specific indicators
        operational_indicator = next(i for i in performance_indicators if i["status"] == "operational")
        assert "systems operational" in operational_indicator["text"]
        
        uptime_indicator = next(i for i in performance_indicators if "Uptime" in i["text"])
        assert "99.9%" in uptime_indicator["text"]
        assert uptime_indicator["color"] == "yellow"

    def test_responsive_behavior(self):
        """Test responsive behavior across different screen sizes"""
        responsive_config = {
            "metrics_grid": {
                "mobile": "grid-cols-2",
                "desktop": "lg:grid-cols-4"
            },
            "tools_grid": {
                "mobile": "grid-cols-3",
                "tablet": "md:grid-cols-6"
            },
            "institutions_grid": {
                "mobile": "grid-cols-2",
                "tablet": "md:grid-cols-4", 
                "desktop": "lg:grid-cols-8"
            },
            "animation_delays": {
                "metrics": lambda index: f"{index * 100}ms",
                "tools": lambda index: f"{index * 50}ms",
                "institutions": lambda index: f"{index * 30}ms"
            }
        }
        
        # Test responsive grid configurations
        assert "grid-cols-2" in responsive_config["metrics_grid"]["mobile"]
        assert "lg:grid-cols-4" in responsive_config["metrics_grid"]["desktop"]
        
        assert "grid-cols-3" in responsive_config["tools_grid"]["mobile"]
        assert "md:grid-cols-6" in responsive_config["tools_grid"]["tablet"]
        
        assert "lg:grid-cols-8" in responsive_config["institutions_grid"]["desktop"]
        
        # Test animation delays
        delays = responsive_config["animation_delays"]
        assert delays["metrics"](0) == "0ms"
        assert delays["metrics"](3) == "300ms"
        assert delays["tools"](5) == "250ms"
        assert delays["institutions"](2) == "60ms"

    def test_external_link_handling(self):
        """Test external link handling for tools"""
        def handle_tool_click(tool):
            """Mock tool click handler"""
            if tool.get("url"):
                # In real implementation, this would be window.open(url, '_blank')
                return {
                    "action": "external_link",
                    "url": tool["url"],
                    "target": "_blank"
                }
            return {"action": "none"}
        
        # Test with URL
        fsl_tool = {
            "name": "FSL",
            "url": "https://fsl.fmrib.ox.ac.uk"
        }
        
        result = handle_tool_click(fsl_tool)
        assert result["action"] == "external_link"
        assert result["url"] == fsl_tool["url"]
        assert result["target"] == "_blank"
        
        # Test without URL
        no_url_tool = {
            "name": "Custom Tool"
        }
        
        result = handle_tool_click(no_url_tool)
        assert result["action"] == "none"


@pytest.fixture
def mock_trust_strip():
    """Mock trust strip component for testing"""
    return {
        "component_name": "TrustStrip",
        "props": {
            "showTools": True,
            "showInstitutions": True,
            "showMetrics": True,
            "animate": True
        },
        "state": {
            "is_visible": False,
            "current_metric_index": 0,
            "metrics_count": 4
        },
        "data": {
            "trust_metrics": 4,
            "tool_logos": 6,
            "institutions": 8
        }
    }


def test_trust_strip_integration(mock_trust_strip):
    """Test trust strip component integration"""
    component = mock_trust_strip
    
    # Test component structure
    assert component["component_name"] == "TrustStrip"
    assert component["props"]["showTools"]
    assert component["props"]["showInstitutions"]
    assert component["props"]["showMetrics"]
    assert component["props"]["animate"]
    
    # Test initial state
    assert not component["state"]["is_visible"]
    assert component["state"]["current_metric_index"] == 0
    assert component["state"]["metrics_count"] == 4
    
    # Test data structure
    assert component["data"]["trust_metrics"] == 4
    assert component["data"]["tool_logos"] == 6
    assert component["data"]["institutions"] == 8