#!/usr/bin/env python3
"""End-to-end test script for polar-flow-server.

Tests all key functionality:
- Health endpoint (public)
- API key authentication
- Data endpoints (sleep, activity, etc.)
- Migration status

Usage:
    uv run python scripts/test_e2e.py
    # Or with custom config:
    API_KEY=your_key USER_ID=12345 uv run python scripts/test_e2e.py
"""

import os
import sys

import httpx

# Configuration
BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")
API_KEY = os.getenv("API_KEY", "pfs_test_key_for_development_only")
USER_ID = os.getenv("USER_ID", "63831921")  # Default test user


def test_health():
    """Test health endpoint (no auth required)."""
    print("Testing health endpoint...")
    r = httpx.get(f"{BASE_URL}/health")
    assert r.status_code == 200, f"Health check failed: {r.status_code}"
    data = r.json()
    assert data["status"] == "ok", f"Unexpected status: {data}"
    print(f"  ✅ Health: {data}")
    return True


def test_auth_required():
    """Test that endpoints require API key."""
    print("Testing authentication requirement...")
    r = httpx.get(f"{BASE_URL}/users/{USER_ID}/sleep")
    assert r.status_code == 401, f"Expected 401, got: {r.status_code}"
    assert "Missing API key" in r.json()["detail"]
    print("  ✅ Endpoints correctly require API key")
    return True


def test_invalid_key():
    """Test that invalid API key is rejected."""
    print("Testing invalid API key rejection...")
    headers = {"X-API-Key": "invalid_key_12345"}
    r = httpx.get(f"{BASE_URL}/users/{USER_ID}/sleep", headers=headers)
    assert r.status_code == 401, f"Expected 401, got: {r.status_code}"
    assert "Invalid API key" in r.json()["detail"]
    print("  ✅ Invalid API key correctly rejected")
    return True


def test_sleep_endpoint():
    """Test sleep data endpoint with valid API key."""
    print("Testing sleep endpoint...")
    headers = {"X-API-Key": API_KEY}
    r = httpx.get(f"{BASE_URL}/users/{USER_ID}/sleep?days=7", headers=headers)
    assert r.status_code == 200, f"Sleep endpoint failed: {r.status_code} - {r.text}"
    data = r.json()
    print(f"  ✅ Sleep records: {len(data)}")
    if data:
        print(f"     Latest: {data[0]['date']} - score: {data[0]['sleep_score']}")
    return True


def test_activity_endpoint():
    """Test activity data endpoint."""
    print("Testing activity endpoint...")
    headers = {"X-API-Key": API_KEY}
    r = httpx.get(f"{BASE_URL}/users/{USER_ID}/activity?days=7", headers=headers)
    assert r.status_code == 200, f"Activity endpoint failed: {r.status_code}"
    data = r.json()
    print(f"  ✅ Activity records: {len(data)}")
    return True


def test_recharge_endpoint():
    """Test nightly recharge endpoint."""
    print("Testing recharge endpoint...")
    headers = {"X-API-Key": API_KEY}
    r = httpx.get(f"{BASE_URL}/users/{USER_ID}/recharge?days=7", headers=headers)
    assert r.status_code == 200, f"Recharge endpoint failed: {r.status_code}"
    data = r.json()
    print(f"  ✅ Recharge records: {len(data)}")
    return True


def test_export_summary():
    """Test export summary endpoint."""
    print("Testing export summary...")
    headers = {"X-API-Key": API_KEY}
    r = httpx.get(f"{BASE_URL}/users/{USER_ID}/export/summary?days=30", headers=headers)
    assert r.status_code == 200, f"Export summary failed: {r.status_code}"
    data = r.json()
    print("  ✅ Export summary:")
    print(f"     User: {data['user_id']}")
    print(f"     Total records: {data['total_records']}")
    print(f"     Counts: {data['record_counts']}")
    return True


def test_bearer_token():
    """Test Bearer token authentication."""
    print("Testing Bearer token auth...")
    headers = {"Authorization": f"Bearer {API_KEY}"}
    r = httpx.get(f"{BASE_URL}/users/{USER_ID}/sleep?days=1", headers=headers)
    assert r.status_code == 200, f"Bearer auth failed: {r.status_code}"
    print("  ✅ Bearer token authentication works")
    return True


def main():
    """Run all end-to-end tests."""
    print("=" * 60)
    print("polar-flow-server End-to-End Tests")
    print("=" * 60)
    print(f"Base URL: {BASE_URL}")
    print(f"User ID: {USER_ID}")
    print("-" * 60)

    tests = [
        test_health,
        test_auth_required,
        test_invalid_key,
        test_sleep_endpoint,
        test_activity_endpoint,
        test_recharge_endpoint,
        test_export_summary,
        test_bearer_token,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            print(f"  ❌ FAILED: {e}")
            failed += 1
        except Exception as e:
            print(f"  ❌ ERROR: {e}")
            failed += 1

    print("-" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 60)

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
