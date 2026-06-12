#!/usr/bin/env python3
"""
generate_traffic.py — send a batch of requests to populate X-Ray traces.

Usage:
    python scripts/generate_traffic.py <API_ENDPOINT> [--count N]

Example:
    python scripts/generate_traffic.py https://abc123.execute-api.us-east-1.amazonaws.com/trace

Sends N requests spread across three fault modes:
  - healthy  (no ?fault param)   → fast, green trace
  - slow     (?fault=slow)       → ~2 s, worker subsegment dominates
  - error    (?fault=error)      → 500, trace flagged with fault

After this script finishes, wait ~30 s then open:
  CloudWatch → X-Ray → Service map   (to see the topology)
  CloudWatch → X-Ray → Traces        (to find individual traces by annotation)
"""

import argparse
import sys
import time
import urllib.request
import urllib.error

FAULT_MODES = ["none", "slow", "error"]


def hit(base_url: str, fault: str) -> tuple[int, str]:
    url = base_url if fault == "none" else f"{base_url}?fault={fault}"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            return resp.status, resp.read(200).decode()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(200).decode()
    except Exception as exc:
        return 0, str(exc)


def main():
    parser = argparse.ArgumentParser(description="Generate X-Ray demo traffic")
    parser.add_argument("endpoint", help="API endpoint URL (the /trace path)")
    parser.add_argument("--count", type=int, default=5,
                        help="Requests per fault mode (default 5; total = 3×N)")
    args = parser.parse_args()

    base = args.endpoint.rstrip("/")
    total = args.count * len(FAULT_MODES)
    print(f"Sending {total} requests ({args.count} per mode) to {base}\n")

    results = {m: [] for m in FAULT_MODES}

    for fault in FAULT_MODES:
        print(f"── Mode: {fault or 'healthy'} ──")
        for i in range(1, args.count + 1):
            status, body = hit(base, fault)
            icon = "✓" if status == 200 else "✗"
            print(f"  [{i}/{args.count}] {icon} HTTP {status}  {body[:80]}")
            results[fault].append(status)
            # Small pause so requests don't blur into a single X-Ray sampling window
            time.sleep(0.5)
        print()

    # Summary
    print("── Summary ──")
    for fault, statuses in results.items():
        label = fault if fault != "none" else "healthy"
        ok = sum(1 for s in statuses if s == 200)
        print(f"  {label:8s}: {ok}/{len(statuses)} 200 OK")

    print("\nDone. Allow ~30 s for traces to appear in the X-Ray console.")
    print("CloudWatch → X-Ray → Service map")
    print("CloudWatch → X-Ray → Traces  (filter by annotation fault_mode)")


if __name__ == "__main__":
    main()
