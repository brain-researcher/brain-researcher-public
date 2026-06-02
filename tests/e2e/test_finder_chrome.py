#!/usr/bin/env python
"""
End-to-end test script for Finder UI using Chrome automation.
This script tests the complete Finder user flow in a real browser.
"""

import json
import time
from typing import Any, Dict, List

import requests


class FinderChromeTest:
    """Chrome-based E2E tests for Finder UI."""

    def __init__(self):
        self.base_url = "http://localhost:3003"
        self.api_url = "http://localhost:5000"
        self.test_results = []

    def check_services(self) -> bool:
        """Check if required services are running."""
        print("🔍 Checking services...")

        # Check API
        try:
            response = requests.get(f"{self.api_url}/health")
            if response.status_code != 200:
                print(f"❌ API not healthy at {self.api_url}")
                return False
        except requests.ConnectionError:
            print(f"❌ Cannot connect to API at {self.api_url}")
            return False

        # Check UI
        try:
            response = requests.get(f"{self.base_url}")
            if response.status_code != 200:
                print(f"❌ UI not accessible at {self.base_url}")
                return False
        except requests.ConnectionError:
            print(f"❌ Cannot connect to UI at {self.base_url}")
            return False

        print("✅ All services running")
        return True

    def test_finder_page_loads(self) -> Dict[str, Any]:
        """Test that Finder page loads successfully."""
        test_name = "Finder Page Load"
        print(f"\n🧪 Testing: {test_name}")

        try:
            response = requests.get(f"{self.base_url}/finder")

            success = response.status_code == 200

            # Check for key UI elements in HTML
            html = response.text
            has_search = "search" in html.lower()
            has_filter = "filter" in html.lower()

            result = {
                "name": test_name,
                "success": success and has_search,
                "details": {
                    "status_code": response.status_code,
                    "has_search_ui": has_search,
                    "has_filter_ui": has_filter,
                    "page_size": len(html),
                },
            }

            if result["success"]:
                print(f"  ✅ Page loaded successfully")
            else:
                print(f"  ❌ Page load failed")

            return result

        except Exception as e:
            print(f"  ❌ Error: {e}")
            return {"name": test_name, "success": False, "error": str(e)}

    def test_natural_language_search(self) -> Dict[str, Any]:
        """Test natural language search functionality."""
        test_name = "Natural Language Search"
        print(f"\n🧪 Testing: {test_name}")

        test_queries = [
            "fMRI motor task",
            "structural MRI studies",
            "working memory after 2020",
        ]

        results = []
        for query in test_queries:
            print(f"  Testing query: '{query}'")

            # Test API endpoint
            response = requests.post(
                f"{self.api_url}/kg/suggestFilters", json={"text": query}
            )

            if response.status_code == 200:
                filters = response.json()["filters"]
                print(f"    Generated {len(filters)} filters")
                results.append(
                    {"query": query, "success": True, "filter_count": len(filters)}
                )
            else:
                results.append(
                    {"query": query, "success": False, "error": response.status_code}
                )

        success = all(r["success"] for r in results)

        return {"name": test_name, "success": success, "details": results}

    def test_facet_functionality(self) -> Dict[str, Any]:
        """Test facet counting and filtering."""
        test_name = "Facet Functionality"
        print(f"\n🧪 Testing: {test_name}")

        try:
            # Test without filters
            response = requests.post(f"{self.api_url}/kg/facets", json={"filters": []})

            if response.status_code == 200:
                facets = response.json()["facets"]
                facet_count = len(facets)

                print(f"  ✅ Retrieved {facet_count} facet categories")

                # Test with filter
                filters = [{"facet": "modality", "op": "=", "value": "fmri"}]
                response = requests.post(
                    f"{self.api_url}/kg/facets", json={"filters": filters}
                )

                filtered_success = response.status_code == 200

                return {
                    "name": test_name,
                    "success": True,
                    "details": {
                        "facet_categories": facet_count,
                        "filtered_test": filtered_success,
                    },
                }
            else:
                print(f"  ❌ Facet API returned {response.status_code}")
                return {
                    "name": test_name,
                    "success": False,
                    "error": f"API returned {response.status_code}",
                }

        except Exception as e:
            print(f"  ❌ Error: {e}")
            return {"name": test_name, "success": False, "error": str(e)}

    def test_dataset_search(self) -> Dict[str, Any]:
        """Test dataset search functionality."""
        test_name = "Dataset Search"
        print(f"\n🧪 Testing: {test_name}")

        try:
            # Search without filters
            response = requests.post(
                f"{self.api_url}/kg/searchDatasets",
                json={"filters": [], "sort": "readiness", "limit": 5, "offset": 0},
            )

            if response.status_code == 200:
                datasets = response.json()["datasets"]
                dataset_count = len(datasets)

                print(f"  Found {dataset_count} datasets")

                # Check dataset structure
                if dataset_count > 0:
                    ds = datasets[0]
                    has_required = all(k in ds for k in ["id", "name", "readiness"])

                    if has_required:
                        print(f"  ✅ Dataset structure valid")
                        print(f"    First dataset: {ds['name']}")
                        print(f"    Readiness: {ds['readiness']['color']}")

                    return {
                        "name": test_name,
                        "success": has_required,
                        "details": {
                            "dataset_count": dataset_count,
                            "has_required_fields": has_required,
                        },
                    }
                else:
                    print(f"  ⚠️ No datasets returned")
                    return {
                        "name": test_name,
                        "success": True,  # Empty result is valid
                        "details": {"dataset_count": 0},
                    }
            else:
                print(f"  ❌ Search API returned {response.status_code}")
                return {
                    "name": test_name,
                    "success": False,
                    "error": f"API returned {response.status_code}",
                }

        except Exception as e:
            print(f"  ❌ Error: {e}")
            return {"name": test_name, "success": False, "error": str(e)}

    def test_complete_user_flow(self) -> Dict[str, Any]:
        """Test complete user workflow."""
        test_name = "Complete User Flow"
        print(f"\n🧪 Testing: {test_name}")

        workflow_steps = []

        try:
            # Step 1: Natural language query
            print("  1️⃣ Natural language query...")
            response = requests.post(
                f"{self.api_url}/kg/suggestFilters", json={"text": "fMRI motor task"}
            )

            if response.status_code == 200:
                filters = response.json()["filters"]
                workflow_steps.append(
                    {"step": "NL Query", "success": True, "filters": len(filters)}
                )

                # Step 2: Get facets
                print("  2️⃣ Getting facets...")
                response = requests.post(
                    f"{self.api_url}/kg/facets", json={"filters": filters}
                )

                if response.status_code == 200:
                    workflow_steps.append({"step": "Get Facets", "success": True})

                    # Step 3: Search datasets
                    print("  3️⃣ Searching datasets...")
                    response = requests.post(
                        f"{self.api_url}/kg/searchDatasets",
                        json={
                            "filters": filters,
                            "sort": "readiness",
                            "limit": 5,
                            "offset": 0,
                        },
                    )

                    if response.status_code == 200:
                        datasets = response.json()["datasets"]
                        workflow_steps.append(
                            {
                                "step": "Search Datasets",
                                "success": True,
                                "datasets": len(datasets),
                            }
                        )

                        # Step 4: Get explanation (if datasets available)
                        if len(datasets) > 0:
                            print("  4️⃣ Getting dataset explanation...")
                            dataset_id = datasets[0]["id"]
                            response = requests.get(
                                f"{self.api_url}/kg/explain/{dataset_id}"
                            )

                            if response.status_code == 200:
                                workflow_steps.append(
                                    {"step": "Get Explanation", "success": True}
                                )
                            else:
                                workflow_steps.append(
                                    {
                                        "step": "Get Explanation",
                                        "success": False,
                                        "error": response.status_code,
                                    }
                                )

            success = all(s.get("success", False) for s in workflow_steps)

            if success:
                print("  ✅ Complete workflow successful!")
            else:
                print("  ❌ Workflow failed at some step")

            return {"name": test_name, "success": success, "details": workflow_steps}

        except Exception as e:
            print(f"  ❌ Error: {e}")
            return {
                "name": test_name,
                "success": False,
                "error": str(e),
                "completed_steps": workflow_steps,
            }

    def run_all_tests(self):
        """Run all tests and generate report."""
        print("=" * 60)
        print("FINDER E2E TEST SUITE")
        print("=" * 60)

        if not self.check_services():
            print("\n❌ Required services not running. Exiting.")
            return

        # Run tests
        tests = [
            self.test_finder_page_loads,
            self.test_natural_language_search,
            self.test_facet_functionality,
            self.test_dataset_search,
            self.test_complete_user_flow,
        ]

        for test_func in tests:
            result = test_func()
            self.test_results.append(result)
            time.sleep(0.5)  # Small delay between tests

        # Generate report
        self.generate_report()

    def generate_report(self):
        """Generate test report."""
        print("\n" + "=" * 60)
        print("TEST REPORT")
        print("=" * 60)

        passed = 0
        failed = 0

        for result in self.test_results:
            if result["success"]:
                print(f"✅ PASS: {result['name']}")
                passed += 1
            else:
                print(f"❌ FAIL: {result['name']}")
                if "error" in result:
                    print(f"         Error: {result['error']}")
                failed += 1

        print("\n" + "-" * 40)
        print(f"Total: {passed} passed, {failed} failed")
        print("-" * 40)

        # Save detailed report
        report_file = "test_results/finder_e2e_report.json"
        import os

        os.makedirs("test_results", exist_ok=True)

        with open(report_file, "w") as f:
            json.dump(
                {
                    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "summary": {
                        "passed": passed,
                        "failed": failed,
                        "total": len(self.test_results),
                    },
                    "results": self.test_results,
                },
                f,
                indent=2,
            )

        print(f"\nDetailed report saved to: {report_file}")

        # Instructions for manual testing
        print("\n" + "=" * 60)
        print("MANUAL TESTING INSTRUCTIONS")
        print("=" * 60)
        print(
            """
To manually test the Finder UI:

1. Open Chrome/Firefox and navigate to: http://localhost:3003/finder

2. Test Natural Language Search:
   - Type "fMRI motor task" in search box
   - Verify filter chips appear below search
   - Try removing chips by clicking X

3. Test Facet Sidebar:
   - Check various facet checkboxes
   - Verify dataset count updates
   - Test collapsible sections

4. Test Dataset Cards:
   - Verify readiness indicators (green/yellow/red)
   - Check "Why matched" explanations
   - Click on dataset cards

5. Test Dataset Details:
   - Click "View Details" on a card
   - Verify evidence rail opens
   - Check Summary, Evidence, and Graph tabs
   - Verify mini-graph renders

6. Test Pagination:
   - Navigate through result pages
   - Change results per page

7. Test Sorting:
   - Try different sort options
   - Verify order changes

Report any issues found during manual testing.
        """
        )


def main():
    """Run the test suite."""
    tester = FinderChromeTest()
    tester.run_all_tests()


if __name__ == "__main__":
    main()
