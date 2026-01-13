#!/usr/bin/env python3
"""End-to-end test for polar-flow-server.

Tests all major endpoints to verify the server is working correctly.

Usage:
    # Set environment variables:
    export API_KEY="pfs_test_key_for_development_only"
    export USER_ID="your_polar_user_id"
    export BASE_URL="http://localhost:8000"

    # Run tests:
    uv run python scripts/test_e2e.py
"""

import asyncio
import os
import sys

import httpx

# Configuration from environment
API_KEY = os.environ.get("API_KEY", "pfs_test_key_for_development_only")
USER_ID = os.environ.get("USER_ID", "test-user")
BASE_URL = os.environ.get("BASE_URL", "http://localhost:8000")
API_BASE = f"{BASE_URL}/api/v1"


async def test_health() -> bool:
    """Test health endpoint (no auth required)."""
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{BASE_URL}/health")
        if r.status_code != 200:
            print(f"  FAIL: Health check returned {r.status_code}")
            return False
        data = r.json()
        if data.get("status") != "healthy":
            print(f"  FAIL: Health status is {data.get('status')}")
            return False
        print(f"  OK: Server healthy, database {data.get('database', 'unknown')}")
        return True


async def test_unauthorized() -> bool:
    """Test that endpoints require API key."""
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{API_BASE}/users/{USER_ID}/sleep")
        if r.status_code != 401:
            print(f"  FAIL: Expected 401, got {r.status_code}")
            return False
        print("  OK: Unauthorized request correctly rejected")
        return True


async def test_data_endpoints() -> bool:
    """Test data retrieval endpoints."""
    headers = {"X-API-Key": API_KEY}
    endpoints = [
        ("sleep", f"/users/{USER_ID}/sleep?days=7"),
        ("activity", f"/users/{USER_ID}/activity?days=7"),
        ("recharge", f"/users/{USER_ID}/recharge?days=7"),
        ("exercises", f"/users/{USER_ID}/exercises?days=30"),
        ("cardio-load", f"/users/{USER_ID}/cardio-load?days=7"),
        ("heart-rate", f"/users/{USER_ID}/heart-rate?days=7"),
    ]

    async with httpx.AsyncClient() as client:
        for name, path in endpoints:
            r = await client.get(f"{API_BASE}{path}", headers=headers)
            if r.status_code != 200:
                print(f"  FAIL: {name} returned {r.status_code}")
                return False
            data = r.json()
            count = len(data) if isinstance(data, list) else "N/A"
            print(f"  OK: {name} - {count} records")
    return True


async def test_baseline_endpoints() -> bool:
    """Test baseline/analytics endpoints."""
    headers = {"X-API-Key": API_KEY}
    async with httpx.AsyncClient() as client:
        # Test baselines list
        r = await client.get(f"{API_BASE}/users/{USER_ID}/baselines", headers=headers)
        if r.status_code != 200:
            print(f"  FAIL: baselines returned {r.status_code}")
            return False
        baselines = r.json()
        print(f"  OK: baselines - {len(baselines)} metrics")

        # Test analytics status
        r = await client.get(f"{API_BASE}/users/{USER_ID}/analytics/status", headers=headers)
        if r.status_code != 200:
            print(f"  FAIL: analytics/status returned {r.status_code}")
            return False
        status = r.json()
        print(f"  OK: analytics/status - {status.get('min_data_days', '?')} min days")
    return True


async def test_pattern_endpoints() -> bool:
    """Test pattern detection endpoints."""
    headers = {"X-API-Key": API_KEY}
    async with httpx.AsyncClient() as client:
        # Test patterns list
        r = await client.get(f"{API_BASE}/users/{USER_ID}/patterns", headers=headers)
        if r.status_code != 200:
            print(f"  FAIL: patterns returned {r.status_code}")
            return False
        patterns = r.json()
        print(f"  OK: patterns - {len(patterns)} detected")

        # Test anomalies
        r = await client.get(f"{API_BASE}/users/{USER_ID}/anomalies", headers=headers)
        if r.status_code != 200:
            print(f"  FAIL: anomalies returned {r.status_code}")
            return False
        anomalies = r.json()
        print(f"  OK: anomalies - {anomalies.get('anomaly_count', 0)} found")

        # Test invalid pattern name returns 404
        r = await client.get(
            f"{API_BASE}/users/{USER_ID}/patterns/invalid_pattern_name", headers=headers
        )
        if r.status_code != 404:
            print(f"  FAIL: invalid pattern should return 404, got {r.status_code}")
            return False
        print("  OK: invalid pattern returns 404")
    return True


async def test_openapi() -> bool:
    """Test OpenAPI schema endpoint."""
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{BASE_URL}/schema/openapi.json")
        if r.status_code != 200:
            print(f"  FAIL: OpenAPI schema returned {r.status_code}")
            return False
        schema = r.json()
        paths = len(schema.get("paths", {}))
        print(f"  OK: OpenAPI schema - {paths} paths documented")
    return True


async def main() -> int:
    """Run all E2E tests."""
    print("=" * 60)
    print("Polar Flow Server - End-to-End Tests")
    print("=" * 60)
    print(f"Base URL: {BASE_URL}")
    print(f"User ID: {USER_ID}")
    print(f"API Key: {API_KEY[:10]}...")
    print("=" * 60)

    tests = [
        ("Health Check", test_health),
        ("Authorization", test_unauthorized),
        ("Data Endpoints", test_data_endpoints),
        ("Baseline Endpoints", test_baseline_endpoints),
        ("Pattern Endpoints", test_pattern_endpoints),
        ("OpenAPI Schema", test_openapi),
    ]

    passed = 0
    failed = 0

    for name, test_func in tests:
        print(f"\n[{name}]")
        try:
            if await test_func():
                passed += 1
            else:
                failed += 1
        except Exception as e:
            print(f"  ERROR: {e}")
            failed += 1

    print("\n" + "=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 60)

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
