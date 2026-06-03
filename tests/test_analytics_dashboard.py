#!/usr/bin/env python3
"""
Comprehensive Test Suite for Advanced Analytics Dashboard (UI-040)
Tests all components, backend endpoints, and functionality.
"""

import requests
import json
import time
from datetime import datetime, timedelta
from typing import Dict, Any
import sys

# Test configuration
BASE_URL = "http://localhost:8081"  # Orchestrator URL
ANALYTICS_BASE = f"{BASE_URL}/api/analytics"

def test_analytics_endpoints():
    """Test all analytics backend endpoints."""
    print("🧪 Testing Analytics Backend Endpoints...")

    # Test parameters
    end_date = datetime.now()
    start_date = end_date - timedelta(days=7)

    start_str = start_date.isoformat()
    end_str = end_date.isoformat()

    endpoints_to_test = [
        f"/usage?start={start_str}&end={end_str}",
        f"/performance?start={start_str}&end={end_str}",
        f"/research?start={start_str}&end={end_str}",
        f"/system?start={start_str}&end={end_str}",
        f"/engagement?start={start_str}&end={end_str}"
    ]

    results = {}

    for endpoint in endpoints_to_test:
        url = f"{ANALYTICS_BASE}{endpoint}"
        try:
            print(f"  Testing: {endpoint}")
            response = requests.get(url, timeout=10)

            if response.status_code == 200:
                data = response.json()
                results[endpoint] = {
                    "status": "✅ PASS",
                    "response_time": response.elapsed.total_seconds(),
                    "data_keys": list(data.keys()) if isinstance(data, dict) else "non-dict",
                    "sample_data": str(data)[:200] + "..." if len(str(data)) > 200 else str(data)
                }
                print(f"    ✅ Status: {response.status_code}")
                print(f"    ⏱️  Response time: {response.elapsed.total_seconds():.3f}s")
                print(f"    📊 Data keys: {list(data.keys()) if isinstance(data, dict) else 'non-dict'}")
            else:
                results[endpoint] = {
                    "status": f"❌ FAIL - HTTP {response.status_code}",
                    "error": response.text
                }
                print(f"    ❌ Failed with status: {response.status_code}")
                print(f"    📄 Error: {response.text}")

        except requests.exceptions.RequestException as e:
            results[endpoint] = {
                "status": f"❌ FAIL - Connection Error",
                "error": str(e)
            }
            print(f"    ❌ Connection error: {e}")

        print()

    return results

def test_export_functionality():
    """Test analytics export functionality."""
    print("📤 Testing Export Functionality...")

    end_date = datetime.now()
    start_date = end_date - timedelta(days=7)

    formats = ['json', 'csv']  # Skip PDF for now as it's mock

    results = {}

    for format_type in formats:
        url = f"{ANALYTICS_BASE}/export"
        params = {
            'format': format_type,
            'start': start_date.isoformat(),
            'end': end_date.isoformat()
        }

        try:
            print(f"  Testing {format_type.upper()} export...")
            response = requests.get(url, params=params, timeout=15)

            if response.status_code == 200:
                if format_type == 'json':
                    try:
                        data = response.json()
                        results[format_type] = {
                            "status": "✅ PASS",
                            "content_type": response.headers.get('content-type'),
                            "data_sections": list(data.keys()) if isinstance(data, dict) else "non-dict"
                        }
                        print(f"    ✅ JSON export successful")
                        print(f"    📊 Sections: {list(data.keys()) if isinstance(data, dict) else 'non-dict'}")
                    except json.JSONDecodeError:
                        results[format_type] = {"status": "❌ FAIL - Invalid JSON"}
                        print(f"    ❌ Invalid JSON response")
                elif format_type == 'csv':
                    csv_content = response.text
                    lines = csv_content.split('\n')
                    results[format_type] = {
                        "status": "✅ PASS",
                        "content_type": response.headers.get('content-type'),
                        "line_count": len(lines),
                        "header": lines[0] if lines else "no header"
                    }
                    print(f"    ✅ CSV export successful")
                    print(f"    📄 Lines: {len(lines)}, Header: {lines[0] if lines else 'no header'}")
            else:
                results[format_type] = {
                    "status": f"❌ FAIL - HTTP {response.status_code}",
                    "error": response.text
                }
                print(f"    ❌ Failed with status: {response.status_code}")

        except requests.exceptions.RequestException as e:
            results[format_type] = {
                "status": f"❌ FAIL - Connection Error",
                "error": str(e)
            }
            print(f"    ❌ Connection error: {e}")

        print()

    return results

def test_custom_reports():
    """Test custom reports functionality."""
    print("📋 Testing Custom Reports...")

    results = {}

    # Test getting reports (should be empty initially)
    try:
        print("  Testing GET /reports...")
        response = requests.get(f"{ANALYTICS_BASE}/reports", timeout=10)

        if response.status_code == 200:
            reports = response.json()
            results["get_reports"] = {
                "status": "✅ PASS",
                "count": len(reports) if isinstance(reports, list) else "non-list"
            }
            print(f"    ✅ Retrieved {len(reports) if isinstance(reports, list) else 'non-list'} reports")
        else:
            results["get_reports"] = {"status": f"❌ FAIL - HTTP {response.status_code}"}
            print(f"    ❌ Failed with status: {response.status_code}")

    except requests.exceptions.RequestException as e:
        results["get_reports"] = {"status": f"❌ FAIL - {e}"}
        print(f"    ❌ Error: {e}")

    # Test creating a report
    sample_report = {
        "name": "Test Analytics Report",
        "description": "Test report created by automated testing",
        "charts": [
            {
                "type": "line",
                "title": "User Growth",
                "data": [],
                "options": {"xAxis": "date", "yAxis": "users"}
            }
        ],
        "filters": {
            "timeRange": {
                "start": (datetime.now() - timedelta(days=7)).isoformat(),
                "end": datetime.now().isoformat()
            }
        }
    }

    try:
        print("  Testing POST /reports...")
        response = requests.post(
            f"{ANALYTICS_BASE}/reports",
            json=sample_report,
            timeout=10
        )

        if response.status_code == 200:
            created_report = response.json()
            report_id = created_report.get('id')
            results["create_report"] = {
                "status": "✅ PASS",
                "report_id": report_id,
                "name": created_report.get('name')
            }
            print(f"    ✅ Created report with ID: {report_id}")

            # Test updating the report
            if report_id:
                try:
                    print("  Testing PATCH /reports/{id}...")
                    update_data = {"description": "Updated description via test"}
                    response = requests.patch(
                        f"{ANALYTICS_BASE}/reports/{report_id}",
                        json=update_data,
                        timeout=10
                    )

                    if response.status_code == 200:
                        results["update_report"] = {"status": "✅ PASS"}
                        print(f"    ✅ Updated report successfully")
                    else:
                        results["update_report"] = {"status": f"❌ FAIL - HTTP {response.status_code}"}
                        print(f"    ❌ Update failed with status: {response.status_code}")

                except requests.exceptions.RequestException as e:
                    results["update_report"] = {"status": f"❌ FAIL - {e}"}
                    print(f"    ❌ Update error: {e}")

                # Clean up - delete the test report
                try:
                    print("  Cleaning up test report...")
                    response = requests.delete(f"{ANALYTICS_BASE}/reports/{report_id}", timeout=10)
                    if response.status_code == 200:
                        print(f"    ✅ Test report deleted")
                    else:
                        print(f"    ⚠️  Failed to delete test report")
                except:
                    print(f"    ⚠️  Error deleting test report")

        else:
            results["create_report"] = {"status": f"❌ FAIL - HTTP {response.status_code}"}
            print(f"    ❌ Failed with status: {response.status_code}")

    except requests.exceptions.RequestException as e:
        results["create_report"] = {"status": f"❌ FAIL - {e}"}
        print(f"    ❌ Error: {e}")

    print()
    return results

def test_alerts():
    """Test alerts functionality."""
    print("🚨 Testing Alerts...")

    results = {}

    # Test getting alerts
    try:
        print("  Testing GET /alerts...")
        response = requests.get(f"{ANALYTICS_BASE}/alerts", timeout=10)

        if response.status_code == 200:
            alerts = response.json()
            results["get_alerts"] = {
                "status": "✅ PASS",
                "count": len(alerts) if isinstance(alerts, list) else "non-list"
            }
            print(f"    ✅ Retrieved {len(alerts) if isinstance(alerts, list) else 'non-list'} alerts")
        else:
            results["get_alerts"] = {"status": f"❌ FAIL - HTTP {response.status_code}"}
            print(f"    ❌ Failed with status: {response.status_code}")

    except requests.exceptions.RequestException as e:
        results["get_alerts"] = {"status": f"❌ FAIL - {e}"}
        print(f"    ❌ Error: {e}")

    # Test creating an alert
    sample_alert = {
        "name": "High CPU Usage Alert",
        "metric": "cpuUsage",
        "threshold": 80.0,
        "condition": "above",
        "severity": "warning",
        "enabled": True,
        "recipients": ["admin@example.com"]
    }

    try:
        print("  Testing POST /alerts...")
        response = requests.post(
            f"{ANALYTICS_BASE}/alerts",
            json=sample_alert,
            timeout=10
        )

        if response.status_code == 200:
            created_alert = response.json()
            alert_id = created_alert.get('id')
            results["create_alert"] = {
                "status": "✅ PASS",
                "alert_id": alert_id,
                "name": created_alert.get('name')
            }
            print(f"    ✅ Created alert with ID: {alert_id}")
        else:
            results["create_alert"] = {"status": f"❌ FAIL - HTTP {response.status_code}"}
            print(f"    ❌ Failed with status: {response.status_code}")

    except requests.exceptions.RequestException as e:
        results["create_alert"] = {"status": f"❌ FAIL - {e}"}
        print(f"    ❌ Error: {e}")

    print()
    return results

def test_data_accuracy():
    """Test data accuracy and calculations."""
    print("🔍 Testing Data Accuracy...")

    results = {}

    try:
        # Get usage metrics
        end_date = datetime.now()
        start_date = end_date - timedelta(days=7)

        url = f"{ANALYTICS_BASE}/usage"
        params = {
            'start': start_date.isoformat(),
            'end': end_date.isoformat()
        }

        response = requests.get(url, params=params, timeout=10)

        if response.status_code == 200:
            data = response.json()

            # Test data structure and types
            required_fields = [
                'totalUsers', 'activeUsers', 'newUsers',
                'avgSessionDuration', 'bounceRate', 'topPages'
            ]

            missing_fields = []
            type_errors = []

            for field in required_fields:
                if field not in data:
                    missing_fields.append(field)
                else:
                    # Check data types
                    value = data[field]
                    if field in ['totalUsers', 'activeUsers', 'newUsers'] and not isinstance(value, int):
                        type_errors.append(f"{field}: expected int, got {type(value)}")
                    elif field in ['avgSessionDuration', 'bounceRate'] and not isinstance(value, (int, float)):
                        type_errors.append(f"{field}: expected number, got {type(value)}")
                    elif field == 'topPages' and not isinstance(value, list):
                        type_errors.append(f"{field}: expected list, got {type(value)}")

            # Test data ranges (reasonable values)
            range_errors = []
            if 'bounceRate' in data and (data['bounceRate'] < 0 or data['bounceRate'] > 100):
                range_errors.append(f"bounceRate: {data['bounceRate']} should be 0-100")

            if 'avgSessionDuration' in data and data['avgSessionDuration'] < 0:
                range_errors.append(f"avgSessionDuration: {data['avgSessionDuration']} should be positive")

            if 'activeUsers' in data and 'totalUsers' in data and data['activeUsers'] > data['totalUsers']:
                range_errors.append("activeUsers cannot exceed totalUsers")

            # Compile results
            if not missing_fields and not type_errors and not range_errors:
                results["data_accuracy"] = {
                    "status": "✅ PASS",
                    "message": "All data validation checks passed"
                }
                print("    ✅ All data validation checks passed")
            else:
                results["data_accuracy"] = {
                    "status": "⚠️  PARTIAL",
                    "missing_fields": missing_fields,
                    "type_errors": type_errors,
                    "range_errors": range_errors
                }
                if missing_fields:
                    print(f"    ⚠️  Missing fields: {missing_fields}")
                if type_errors:
                    print(f"    ⚠️  Type errors: {type_errors}")
                if range_errors:
                    print(f"    ⚠️  Range errors: {range_errors}")
        else:
            results["data_accuracy"] = {"status": f"❌ FAIL - Could not retrieve data"}
            print(f"    ❌ Could not retrieve data for testing")

    except requests.exceptions.RequestException as e:
        results["data_accuracy"] = {"status": f"❌ FAIL - {e}"}
        print(f"    ❌ Error: {e}")

    print()
    return results

def test_performance():
    """Test response time performance."""
    print("⚡ Testing Performance...")

    results = {}

    # Test multiple endpoints for response time
    end_date = datetime.now()
    start_date = end_date - timedelta(days=1)  # Smaller range for performance test

    endpoints = [
        f"/usage?start={start_date.isoformat()}&end={end_date.isoformat()}",
        f"/performance?start={start_date.isoformat()}&end={end_date.isoformat()}",
        f"/system?start={start_date.isoformat()}&end={end_date.isoformat()}"
    ]

    response_times = []

    for endpoint in endpoints:
        url = f"{ANALYTICS_BASE}{endpoint}"

        try:
            start_time = time.time()
            response = requests.get(url, timeout=10)
            end_time = time.time()

            response_time = end_time - start_time
            response_times.append(response_time)

            print(f"    📊 {endpoint.split('?')[0]}: {response_time:.3f}s")

        except requests.exceptions.RequestException as e:
            print(f"    ❌ {endpoint}: Error - {e}")

    if response_times:
        avg_response_time = sum(response_times) / len(response_times)
        max_response_time = max(response_times)

        # Performance criteria
        if avg_response_time < 2.0 and max_response_time < 5.0:
            results["performance"] = {
                "status": "✅ PASS",
                "avg_response_time": avg_response_time,
                "max_response_time": max_response_time
            }
            print(f"    ✅ Performance PASS - Avg: {avg_response_time:.3f}s, Max: {max_response_time:.3f}s")
        else:
            results["performance"] = {
                "status": "⚠️  SLOW",
                "avg_response_time": avg_response_time,
                "max_response_time": max_response_time
            }
            print(f"    ⚠️  Performance SLOW - Avg: {avg_response_time:.3f}s, Max: {max_response_time:.3f}s")
    else:
        results["performance"] = {"status": "❌ FAIL - No valid responses"}
        print(f"    ❌ No valid responses received")

    print()
    return results

def generate_test_report(all_results):
    """Generate a comprehensive test report."""
    print("=" * 80)
    print("📊 ANALYTICS DASHBOARD TEST REPORT")
    print("=" * 80)

    total_tests = 0
    passed_tests = 0
    failed_tests = 0
    partial_tests = 0

    for category, tests in all_results.items():
        print(f"\n🔵 {category.upper().replace('_', ' ')}")
        print("-" * 40)

        if isinstance(tests, dict):
            for test_name, result in tests.items():
                total_tests += 1
                status = result.get('status', 'Unknown')

                if '✅ PASS' in status:
                    passed_tests += 1
                elif '❌ FAIL' in status:
                    failed_tests += 1
                elif '⚠️' in status:
                    partial_tests += 1

                print(f"  {test_name}: {status}")

                # Show additional details
                for key, value in result.items():
                    if key != 'status' and not key.startswith('error'):
                        print(f"    {key}: {value}")

                if 'error' in result:
                    print(f"    Error: {result['error']}")

    print("\n" + "=" * 80)
    print("📈 SUMMARY")
    print("=" * 80)
    print(f"Total Tests: {total_tests}")
    print(f"✅ Passed: {passed_tests}")
    print(f"⚠️  Partial: {partial_tests}")
    print(f"❌ Failed: {failed_tests}")

    success_rate = (passed_tests + partial_tests * 0.5) / total_tests * 100 if total_tests > 0 else 0
    print(f"📊 Success Rate: {success_rate:.1f}%")

    if success_rate >= 90:
        print("🎉 EXCELLENT - Dashboard is working great!")
    elif success_rate >= 75:
        print("👍 GOOD - Dashboard is mostly functional")
    elif success_rate >= 50:
        print("⚠️  NEEDS WORK - Several issues to address")
    else:
        print("❌ POOR - Major issues need fixing")

    print("=" * 80)

def main():
    """Run all tests."""
    print("🚀 Starting Advanced Analytics Dashboard Test Suite...")
    print(f"📅 Test Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"🔗 Base URL: {BASE_URL}")
    print("=" * 80)

    all_results = {}

    # Run all test suites
    try:
        all_results['endpoints'] = test_analytics_endpoints()
        all_results['exports'] = test_export_functionality()
        all_results['custom_reports'] = test_custom_reports()
        all_results['alerts'] = test_alerts()
        all_results['data_accuracy'] = test_data_accuracy()
        all_results['performance'] = test_performance()

    except KeyboardInterrupt:
        print("\n⚠️  Tests interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Unexpected error during testing: {e}")
        sys.exit(1)

    # Generate final report
    generate_test_report(all_results)

if __name__ == "__main__":
    main()