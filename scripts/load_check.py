"""Many demo users at once: logs in people from all four roles and has them use the app concurrently.

Read-only against the demo population (@carecircle.demo plus the core demo accounts). Fails if any request errors
or the slowest 5 % of requests exceed --max-p95 seconds.

    python scripts/load_check.py --base-url http://localhost:8000 --users 40 --seconds 20
"""
import argparse
import json
import statistics
import sys
import threading
import time
import urllib.error
import urllib.request

PASSWORD = "Demo@1234"
ROSTER = [
    # (email, role) — people from the demo population, a mix of every role
    *[(e, "PROFESSIONAL") for e in ("kavita.rao", "imran.shaikh", "priya.nair", "sandeep.joshi", "fatima.khan")],
    *[(e, "CARETAKER") for e in ("anjali.verma", "bhaskar.reddy", "charulatha.s", "deepak.menon", "esther.thomas", "farhan.ali", "geeta.kulkarni", "harish.gowda", "indira.pillai", "kavya.hegde")],
    *[(e, "PRIMARY_CONTACT") for e in ("vikram.krishnan", "sunita.das", "arvind.subramanian", "rekha.nambiar", "zoya.khan", "pooja.hegde", "naveen.kumar", "salma.rahim",
                                       "meenakshi.raman", "susan.mathew", "rajesh.nair", "gurpreet.singh", "anand.shenoy", "lavanya.rao", "prakash.babu")],
    *[(e, "PATIENT") for e in ("lalitha.krishnan.patient", "mohan.das.patient", "kamala.subramanian.patient", "gopal.nambiar.patient")],
]
CORE = [("anita.iyer@secondpatient.demo", "PRIMARY_CONTACT"), ("savitha@secondpatient.demo", "CARETAKER"),
        ("dr.arjun.nair@secondpatient.demo", "PROFESSIONAL"), ("ramesh.iyer@secondpatient.demo", "PATIENT")]


class Session:
    def __init__(self, base):
        self.base, self.cookie = base.rstrip("/"), ""

    def call(self, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(self.base + path, data=data, method=method,
                                         headers={"Content-Type": "application/json", "X-Requested-With": "second-patient", "Cookie": self.cookie})
        started = time.perf_counter()
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read()
                for header in response.headers.get_all("Set-Cookie") or []:
                    self.cookie = header.split(";")[0]
                return response.status, json.loads(raw) if raw else None, time.perf_counter() - started
        except urllib.error.HTTPError as err:
            return err.code, None, time.perf_counter() - started
        except Exception:
            return 0, None, time.perf_counter() - started


def workload(role, patients):
    common = [("GET", "/api/v1/auth/me"), ("GET", "/api/v1/patients"), ("GET", "/api/v1/notifications")]
    per_patient = []
    for pid in patients[:2]:
        per_patient += [("GET", f"/api/v1/patients/{pid}/activities?limit=100")]
        if role == "PRIMARY_CONTACT": per_patient += [("GET", f"/api/v1/command-center?patient_id={pid}"), ("GET", f"/api/v1/patients/{pid}/coverage-forecast"), ("GET", f"/api/v1/patients/{pid}/workload-balance")]
        if role == "PROFESSIONAL": per_patient += [("GET", f"/api/v1/patients/{pid}/adherence?days=30"), ("GET", f"/api/v1/patients/{pid}/prescriptions"), ("GET", f"/api/v1/patients/{pid}/appointments")]
    extra = []
    if role == "PROFESSIONAL": extra = [("GET", "/api/v1/insights/professional?days=30")]
    if role == "CARETAKER": extra = [("GET", "/api/v1/cover-offers/mine")]
    return common + per_patient + extra


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--users", type=int, default=40)
    parser.add_argument("--seconds", type=int, default=20)
    parser.add_argument("--max-p95", type=float, default=3.0)
    args = parser.parse_args()
    people = [(f"{e}@carecircle.demo", r) for e, r in ROSTER] + CORE
    people = (people * (args.users // len(people) + 1))[: args.users]
    latencies, failures, lock = [], [], threading.Lock()
    deadline = time.time() + args.seconds

    def worker(email, role):
        s = Session(args.base_url)
        status, _, took = s.call("POST", "/api/v1/auth/login", {"email": email, "password": PASSWORD})
        with lock:
            latencies.append(took)
            if status != 200: failures.append(f"login {email}: {status}")
        if status != 200: return
        _, listing, _ = s.call("GET", "/api/v1/patients")
        patients = [p["id"] for p in (listing or {}).get("items", [])]
        calls = workload(role, patients)
        while time.time() < deadline:
            for method, path in calls:
                status, _, took = s.call(method, path)
                with lock:
                    latencies.append(took)
                    if status != 200: failures.append(f"{role} {path.split('?')[0]}: {status}")
                if time.time() >= deadline: break

    threads = [threading.Thread(target=worker, args=p) for p in people]
    started = time.time()
    for t in threads: t.start()
    for t in threads: t.join()
    elapsed = time.time() - started
    latencies.sort()
    p50, p95 = statistics.median(latencies), latencies[int(0.95 * (len(latencies) - 1))]
    print(f"{len(people)} users · {len(latencies)} requests in {elapsed:.0f}s ({len(latencies) / elapsed:.0f}/s) · p50 {p50 * 1000:.0f} ms · p95 {p95 * 1000:.0f} ms · max {latencies[-1] * 1000:.0f} ms")
    kinds = {}
    for f in failures: kinds[f] = kinds.get(f, 0) + 1
    for f, n in sorted(kinds.items(), key=lambda x: -x[1])[:10]: print(f"  FAIL x{n}: {f}")
    ok = not failures and p95 <= args.max_p95
    print("PASS" if ok else f"FAIL ({len(failures)} errors, p95 {p95:.2f}s vs limit {args.max_p95}s)")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
