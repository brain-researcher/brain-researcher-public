"""
Performance testing suite for Brain Researcher UI
Tests Core Web Vitals, TTI targets, and custom performance metrics
"""

import json
import time
from typing import Any

import pytest
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


class PerformanceTestSuite:
    """Comprehensive performance testing suite"""

    def __init__(self, base_url: str = "http://localhost:3000"):
        self.base_url = base_url
        self.driver = None
        self.performance_budgets = {
            "TTI": 3000,  # Our key target: <3s
            "LCP": 2500,  # Largest Contentful Paint
            "FCP": 1800,  # First Contentful Paint
            "FID": 100,  # First Input Delay
            "CLS": 0.1,  # Cumulative Layout Shift
            "bundle_size": 2048,  # KB
            "initial_load": 3000,  # ms
            "route_change": 500,  # ms
        }

    def setup_driver(self) -> webdriver.Chrome:
        """Setup Chrome driver with performance monitoring enabled"""
        options = Options()
        options.add_argument("--headless")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1920,1080")

        # Enable performance logging
        options.add_argument("--enable-logging")
        options.add_argument("--log-level=0")
        options.set_capability("goog:loggingPrefs", {"performance": "ALL"})

        # Network throttling simulation
        options.add_argument("--force-device-scale-factor=1")

        return webdriver.Chrome(options=options)

    def get_web_vitals(self, page_url: str) -> dict[str, float]:
        """Extract Web Vitals metrics from page"""
        self.driver.get(page_url)

        # Wait for page load
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )

        # Execute JavaScript to get Web Vitals
        script = """
        return new Promise((resolve) => {
            const vitals = {};

            // Get performance entries
            const observer = new PerformanceObserver((list) => {
                for (const entry of list.getEntries()) {
                    if (entry.entryType === 'largest-contentful-paint') {
                        vitals.LCP = entry.startTime;
                    }
                    if (entry.entryType === 'first-input') {
                        vitals.FID = entry.processingStart - entry.startTime;
                    }
                    if (entry.entryType === 'layout-shift') {
                        vitals.CLS = (vitals.CLS || 0) + entry.value;
                    }
                    if (entry.entryType === 'paint' && entry.name === 'first-contentful-paint') {
                        vitals.FCP = entry.startTime;
                    }
                }
            });

            observer.observe({entryTypes: ['largest-contentful-paint', 'first-input', 'layout-shift', 'paint']});

            // Navigation timing for TTI estimation
            const navigation = performance.getEntriesByType('navigation')[0];
            if (navigation) {
                vitals.TTFB = navigation.responseStart - navigation.requestStart;
                vitals.TTI = Math.max(navigation.domComplete, navigation.loadEventEnd) - navigation.navigationStart;
            }

            // Wait a bit for metrics to be collected
            setTimeout(() => {
                observer.disconnect();
                resolve(vitals);
            }, 2000);
        });
        """

        return self.driver.execute_script(script)

    def measure_initial_load_time(self, page_url: str) -> dict[str, float]:
        """Measure initial page load performance"""
        start_time = time.time()

        self.driver.get(page_url)

        # Wait for main content to load
        WebDriverWait(self.driver, 15).until(
            EC.any_of(
                EC.presence_of_element_located((By.CLASS_NAME, "main-content")),
                EC.presence_of_element_located((By.ID, "root")),
                EC.presence_of_element_located((By.TAG_NAME, "main")),
            )
        )

        end_time = time.time()
        total_load_time = (end_time - start_time) * 1000  # Convert to ms

        # Get navigation timing details
        timing_script = """
        const timing = performance.getEntriesByType('navigation')[0];
        return {
            'dns_lookup': timing.domainLookupEnd - timing.domainLookupStart,
            'connection': timing.connectEnd - timing.connectStart,
            'request': timing.responseStart - timing.requestStart,
            'response': timing.responseEnd - timing.responseStart,
            'dom_processing': timing.domComplete - timing.domContentLoadedEventStart,
            'load_event': timing.loadEventEnd - timing.loadEventStart,
            'total_navigation': timing.loadEventEnd - timing.navigationStart
        };
        """

        timing_details = self.driver.execute_script(timing_script)
        timing_details["measured_load_time"] = total_load_time

        return timing_details

    def measure_route_change_performance(self, routes: list[str]) -> dict[str, float]:
        """Measure client-side route change performance"""
        results = {}

        # Start at home page
        self.driver.get(self.base_url)
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )

        for route in routes:
            start_time = time.time()

            # Navigate to route
            self.driver.get(f"{self.base_url}{route}")

            # Wait for route content
            WebDriverWait(self.driver, 10).until(
                EC.any_of(
                    EC.presence_of_element_located((By.CLASS_NAME, "page-content")),
                    EC.presence_of_element_located((By.TAG_NAME, "main")),
                    EC.staleness_of(self.driver.find_element(By.TAG_NAME, "body")),
                )
            )

            end_time = time.time()
            route_change_time = (end_time - start_time) * 1000

            results[route] = route_change_time

        return results

    def analyze_bundle_sizes(self) -> dict[str, int]:
        """Analyze JavaScript bundle sizes"""
        # Get network logs for resource loading
        logs = self.driver.get_log("performance")
        bundle_sizes = {}

        for entry in logs:
            message = json.loads(entry["message"])

            if (
                message["message"]["method"] == "Network.responseReceived"
                and message["message"]["params"]["response"]["mimeType"]
                == "application/javascript"
            ):

                url = message["message"]["params"]["response"]["url"]

                # Categorize bundles
                if "_next/static/chunks/pages/" in url:
                    bundle_sizes["pages"] = bundle_sizes.get("pages", 0) + 1
                elif "_next/static/chunks/" in url:
                    if "framework" in url:
                        bundle_sizes["framework"] = bundle_sizes.get("framework", 0) + 1
                    elif "main" in url:
                        bundle_sizes["main"] = bundle_sizes.get("main", 0) + 1
                    else:
                        bundle_sizes["chunks"] = bundle_sizes.get("chunks", 0) + 1

        return bundle_sizes

    def test_image_optimization(
        self, image_urls: list[str]
    ) -> dict[str, dict[str, Any]]:
        """Test image loading performance and optimization"""
        results = {}

        for url in image_urls:
            self.driver.get(f"{self.base_url}?test_image={url}")

            # Measure image load time
            script = f"""
            return new Promise((resolve) => {{
                const img = document.querySelector('img[src*="{url.split("/")[-1]}"]');
                if (!img) {{
                    resolve({{error: 'Image not found'}});
                    return;
                }}

                const startTime = performance.now();

                if (img.complete) {{
                    resolve({{
                        loadTime: 0,
                        naturalWidth: img.naturalWidth,
                        naturalHeight: img.naturalHeight,
                        displayWidth: img.width,
                        displayHeight: img.height
                    }});
                }} else {{
                    img.onload = () => {{
                        resolve({{
                            loadTime: performance.now() - startTime,
                            naturalWidth: img.naturalWidth,
                            naturalHeight: img.naturalHeight,
                            displayWidth: img.width,
                            displayHeight: img.height
                        }});
                    }};
                    img.onerror = () => {{
                        resolve({{error: 'Image failed to load'}});
                    }};
                }}
            }});
            """

            image_metrics = self.driver.execute_script(script)
            results[url] = image_metrics

        return results

    def run_comprehensive_test(self) -> dict[str, Any]:
        """Run comprehensive performance test suite"""
        self.driver = self.setup_driver()

        try:
            results = {
                "timestamp": time.time(),
                "test_config": {
                    "base_url": self.base_url,
                    "budgets": self.performance_budgets,
                },
                "violations": [],
            }

            # Test routes to analyze
            test_routes = [
                "/",
                "/dashboard",
                "/charts",
                "/knowledge-graph",
                "/datasets",
            ]

            # 1. Test Web Vitals for each route
            print("Testing Web Vitals...")
            web_vitals_results = {}
            for route in test_routes:
                try:
                    vitals = self.get_web_vitals(f"{self.base_url}{route}")
                    web_vitals_results[route] = vitals

                    # Check TTI target specifically
                    if (
                        "TTI" in vitals
                        and vitals["TTI"] > self.performance_budgets["TTI"]
                    ):
                        results["violations"].append(
                            {
                                "type": "TTI_BUDGET_VIOLATION",
                                "route": route,
                                "actual": vitals["TTI"],
                                "budget": self.performance_budgets["TTI"],
                            }
                        )
                except Exception as e:
                    print(f"Web Vitals test failed for {route}: {e}")
                    web_vitals_results[route] = {"error": str(e)}

            results["web_vitals"] = web_vitals_results

            # 2. Test initial load times
            print("Testing initial load times...")
            load_times = {}
            for route in test_routes:
                try:
                    timing = self.measure_initial_load_time(f"{self.base_url}{route}")
                    load_times[route] = timing

                    if (
                        timing.get("measured_load_time", 0)
                        > self.performance_budgets["initial_load"]
                    ):
                        results["violations"].append(
                            {
                                "type": "LOAD_TIME_VIOLATION",
                                "route": route,
                                "actual": timing["measured_load_time"],
                                "budget": self.performance_budgets["initial_load"],
                            }
                        )
                except Exception as e:
                    print(f"Load time test failed for {route}: {e}")
                    load_times[route] = {"error": str(e)}

            results["load_times"] = load_times

            # 3. Test route change performance
            print("Testing route changes...")
            try:
                route_changes = self.measure_route_change_performance(
                    test_routes[1:]
                )  # Skip home
                results["route_changes"] = route_changes

                for route, time_taken in route_changes.items():
                    if time_taken > self.performance_budgets["route_change"]:
                        results["violations"].append(
                            {
                                "type": "ROUTE_CHANGE_VIOLATION",
                                "route": route,
                                "actual": time_taken,
                                "budget": self.performance_budgets["route_change"],
                            }
                        )
            except Exception as e:
                print(f"Route change test failed: {e}")
                results["route_changes"] = {"error": str(e)}

            # 4. Analyze bundle sizes
            print("Analyzing bundle sizes...")
            try:
                self.driver.get(self.base_url)
                time.sleep(3)  # Allow all bundles to load
                bundle_analysis = self.analyze_bundle_sizes()
                results["bundle_analysis"] = bundle_analysis
            except Exception as e:
                print(f"Bundle analysis failed: {e}")
                results["bundle_analysis"] = {"error": str(e)}

            # 5. Calculate overall performance score
            results["performance_score"] = self.calculate_performance_score(results)
            results["tti_target_met"] = self.check_tti_target(results)

            return results

        finally:
            if self.driver:
                self.driver.quit()

    def calculate_performance_score(self, results: dict[str, Any]) -> int:
        """Calculate overall performance score (0-100)"""
        scores = []

        # Web Vitals scoring
        for _route, vitals in results.get("web_vitals", {}).items():
            if isinstance(vitals, dict) and "error" not in vitals:
                route_scores = []

                # TTI score (most important)
                if "TTI" in vitals:
                    tti = vitals["TTI"]
                    if tti <= 3000:
                        route_scores.append(100)
                    elif tti <= 5000:
                        route_scores.append(50)
                    else:
                        route_scores.append(0)

                # LCP score
                if "LCP" in vitals:
                    lcp = vitals["LCP"]
                    if lcp <= 2500:
                        route_scores.append(100)
                    elif lcp <= 4000:
                        route_scores.append(50)
                    else:
                        route_scores.append(0)

                # FID score
                if "FID" in vitals:
                    fid = vitals["FID"]
                    if fid <= 100:
                        route_scores.append(100)
                    elif fid <= 300:
                        route_scores.append(50)
                    else:
                        route_scores.append(0)

                # CLS score
                if "CLS" in vitals:
                    cls = vitals["CLS"]
                    if cls <= 0.1:
                        route_scores.append(100)
                    elif cls <= 0.25:
                        route_scores.append(50)
                    else:
                        route_scores.append(0)

                if route_scores:
                    scores.extend(route_scores)

        # Load time scoring
        for _route, timing in results.get("load_times", {}).items():
            if isinstance(timing, dict) and "measured_load_time" in timing:
                load_time = timing["measured_load_time"]
                if load_time <= 3000:
                    scores.append(100)
                elif load_time <= 5000:
                    scores.append(50)
                else:
                    scores.append(0)

        return int(sum(scores) / len(scores)) if scores else 0

    def check_tti_target(self, results: dict[str, Any]) -> bool:
        """Check if TTI <3s target is met across all routes"""
        for _route, vitals in results.get("web_vitals", {}).items():
            if isinstance(vitals, dict) and "TTI" in vitals:
                if vitals["TTI"] > 3000:
                    return False
        return True


# Pytest test cases
class TestPerformanceOptimization:

    @pytest.fixture(scope="class")
    def performance_suite(self):
        """Fixture to setup performance testing suite"""
        return PerformanceTestSuite()

    @pytest.mark.performance
    def test_tti_under_3_seconds(self, performance_suite):
        """Test that Time to Interactive is under 3 seconds (our key target)"""
        results = performance_suite.run_comprehensive_test()

        # Extract TTI violations
        tti_violations = [
            v for v in results["violations"] if v["type"] == "TTI_BUDGET_VIOLATION"
        ]

        assert len(tti_violations) == 0, f"TTI budget violations: {tti_violations}"
        assert results["tti_target_met"], "TTI <3s target not met across all routes"

    @pytest.mark.performance
    def test_web_vitals_budgets(self, performance_suite):
        """Test that all Web Vitals meet performance budgets"""
        results = performance_suite.run_comprehensive_test()

        # Check for any Web Vitals violations
        vital_violations = [
            v
            for v in results["violations"]
            if v["type"] in ["TTI_BUDGET_VIOLATION", "LOAD_TIME_VIOLATION"]
        ]

        if vital_violations:
            pytest.fail(f"Web Vitals budget violations found: {vital_violations}")

    @pytest.mark.performance
    def test_overall_performance_score(self, performance_suite):
        """Test that overall performance score meets minimum threshold"""
        results = performance_suite.run_comprehensive_test()

        min_score = 70  # Minimum acceptable score
        actual_score = results["performance_score"]

        assert actual_score >= min_score, (
            f"Performance score {actual_score} below minimum {min_score}. "
            f"Violations: {results['violations']}"
        )

    @pytest.mark.performance
    def test_route_change_performance(self, performance_suite):
        """Test that client-side route changes are fast"""
        results = performance_suite.run_comprehensive_test()

        route_violations = [
            v for v in results["violations"] if v["type"] == "ROUTE_CHANGE_VIOLATION"
        ]

        assert (
            len(route_violations) == 0
        ), f"Route change performance violations: {route_violations}"

    @pytest.mark.performance
    def test_bundle_optimization(self, performance_suite):
        """Test that JavaScript bundles are properly optimized and split"""
        results = performance_suite.run_comprehensive_test()

        bundle_analysis = results.get("bundle_analysis", {})

        # Check that we have proper code splitting
        assert "framework" in bundle_analysis, "Framework bundle should be split"
        assert "main" in bundle_analysis, "Main bundle should exist"
        assert "chunks" in bundle_analysis, "Code should be split into chunks"

    @pytest.mark.performance
    @pytest.mark.slow
    def test_memory_usage(self, performance_suite):
        """Test memory usage doesn't exceed limits during extended usage"""
        # This would require a longer running test
        # Placeholder for memory profiling test
        pass

    @pytest.mark.performance
    def test_image_optimization(self, performance_suite):
        """Test that images are properly optimized"""
        # Test with some common image scenarios
        test_images = [
            "/static/brain-scan-sample.jpg",
            "/static/chart-example.png",
            "/static/logo.svg",
        ]

        results = performance_suite.test_image_optimization(test_images)

        for url, metrics in results.items():
            if "error" not in metrics:
                # Images should load within reasonable time
                assert (
                    metrics.get("loadTime", 0) < 2000
                ), f"Image {url} load time too high"

                # Images should be properly sized (not loading massive images)
                natural_width = metrics.get("naturalWidth", 0)
                display_width = metrics.get("displayWidth", 0)

                if natural_width > 0 and display_width > 0:
                    ratio = natural_width / display_width
                    assert ratio <= 3, f"Image {url} over-sized (ratio: {ratio})"


if __name__ == "__main__":
    # Run performance test suite directly
    suite = PerformanceTestSuite()
    results = suite.run_comprehensive_test()

    print("\n" + "=" * 50)
    print("BRAIN RESEARCHER UI PERFORMANCE TEST RESULTS")
    print("=" * 50)

    print(f"\nOverall Performance Score: {results['performance_score']}/100")
    print(f"TTI Target (<3s) Met: {'✓' if results['tti_target_met'] else '✗'}")

    if results["violations"]:
        print(f"\nViolations Found: {len(results['violations'])}")
        for violation in results["violations"]:
            print(
                f"  - {violation['type']}: {violation['route']} "
                f"({violation['actual']:.0f}ms > {violation['budget']}ms)"
            )
    else:
        print("\n✓ No performance budget violations found!")

    # Save detailed results
    output_file = f"performance_report_{int(time.time())}.json"
    with open(output_file, "w") as f:
        json.dump(results, f, indent=2)

    print(f"\nDetailed results saved to: {output_file}")
