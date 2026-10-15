"""Read-only checks that a deployment is really up. Creates no data, so it is safe against production.

    python scripts/postdeploy_check.py --base-url https://carecircle.example.com --expect-sha abc1234567 --expect-prod
"""
import argparse
import json
import ssl
import sys
import time
import urllib.error
import urllib.request


def fetch(base, path, timeout=15, insecure=False):
    request = urllib.request.Request(base.rstrip("/") + path, headers={"Accept": "application/json,text/html"})
    context = ssl._create_unverified_context() if insecure else None
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
            return response.status, dict(response.headers), response.read()
    except urllib.error.HTTPError as err:
        return err.code, dict(err.headers), err.read()
    except Exception as err:  # certificate, DNS, refused, timeout: a failed check, not a crash
        print(f"        ({type(err).__name__}: {str(err)[:110]})")
        return 0, {}, b""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--expect-sha", default="")
    parser.add_argument("--expect-prod", action="store_true", help="the API docs must be hidden and the app must say it is a production environment")
    parser.add_argument("--wait-scheduler", action="store_true", help="wait (up to 90 s) for the scheduler to complete a tick")
    parser.add_argument("--insecure", action="store_true", help="accept a self-signed certificate (private networks only)")
    args = parser.parse_args()
    base, results = args.base_url, []

    def check(name, ok, detail=""):
        results.append(ok)
        print(f"  {'PASS' if ok else 'FAIL'}  {name}{(' · ' + str(detail)) if detail else ''}")

    for attempt in range(20):  # the proxy may need a few seconds after a restart
        try:
            status, _, raw = fetch(base, "/api/health", insecure=args.insecure)
            if status == 200: break
        except Exception:
            status, raw = 0, b"{}"
        time.sleep(3)
    health = json.loads(raw or b"{}") if status == 200 else {}
    check("health endpoint answers", status == 200 and health.get("status") == "ok", f"HTTP {status}")
    check("database reachable", health.get("database") == "ok")
    if args.expect_sha:
        check("running the expected version", str(health.get("git_sha", "")).startswith(args.expect_sha[:7]), f"{health.get('git_sha')} vs {args.expect_sha}")
    if args.expect_prod: check("production environment", health.get("env") == "prod", health.get("env"))

    status, headers, raw = fetch(base, "/api/v1/meta", insecure=args.insecure)
    meta = json.loads(raw) if status == 200 else {}
    check("meta endpoint", status == 200, f"version {meta.get('version')} · features {','.join(meta.get('features', []))}")
    if meta: print(f"        AI: speech {meta.get('ai', {}).get('speech')} · text {meta.get('ai', {}).get('text')} · demo_mode {meta.get('demo_mode')}")

    status, headers, raw = fetch(base, "/", insecure=args.insecure)
    lowered = {k.lower(): v for k, v in headers.items()}
    check("web app is served", status == 200 and b"<div id=\"root\"" in raw or b"root" in raw[:4000], f"HTTP {status}")
    check("content security policy set", "content-security-policy" in lowered)
    if base.startswith("https://"): check("HSTS set", "strict-transport-security" in lowered)

    status, _, _ = fetch(base, "/api/v1/patients", insecure=args.insecure)
    check("API requires sign-in", status == 401, f"HTTP {status}")
    if args.expect_prod:
        status, _, _ = fetch(base, "/api/openapi.json", insecure=args.insecure)
        check("API schema is not published", status == 404, f"HTTP {status}")

    if args.wait_scheduler:
        ticked = False
        for _ in range(30):
            _, _, raw = fetch(base, "/api/health", insecure=args.insecure)
            scheduler = (json.loads(raw or b"{}") or {}).get("scheduler", {})
            if scheduler.get("last_tick_at") or scheduler.get("leader") is False or scheduler.get("enabled") is False:
                ticked = True
                break
            time.sleep(3)
        check("scheduler is running (or another instance owns it)", ticked, scheduler)

    failed = results.count(False)
    print(f"\n{'ALL CHECKS PASSED' if not failed else str(failed) + ' CHECK(S) FAILED'}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
