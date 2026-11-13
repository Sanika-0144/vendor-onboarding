"""CLI demo: python -m demo.run_demo [scenario_key]. All data is FICTIONAL; extraction/malware/sanctions are SYNTHETIC."""
import sys
from datetime import date
from vendor_core import OnboardingEngine, SyntheticSanctionsAdapter
from demo.scenarios import SCENARIOS, edge3_pan_mismatch, edge3_resubmission_fixed

def show(title, r):
    print(f"\n=== {title} -> {r.decision.status.value} ({r.decision.application_state})")
    for rid, res in r.results.items():
        for f in res.findings:
            if f.severity.value not in ("PASS",):
                print(f"   [{f.severity.value:8s}] {f.finding_id}  vendor_visible={f.vendor_visible}")
    print("   --- vendor message ---\n   " + r.vendor_message.body.replace("\n", "\n   "))

if __name__ == "__main__":
    eng = OnboardingEngine(sanctions=SyntheticSanctionsAdapter(), today=date(2026, 11, 12), hmac_key=b"demo")
    keys = sys.argv[1:] or list(SCENARIOS)
    for k in keys:
        show(SCENARIOS[k][0], eng.evaluate(SCENARIOS[k][1](), application_ref=k))
    if not sys.argv[1:]:
        bad = edge3_pan_mismatch(); r1 = eng.evaluate(bad, application_ref="RESUB", version=1)
        r2 = eng.evaluate(edge3_resubmission_fixed(bad), application_ref="RESUB", version=2, previous=r1)
        show("Edge 3 resubmission (v2)", r2)
        print("   diff:", r2.finding_diff, "\n   rerun:", {k: r2.rerun[k] for k in ("changed_inputs", "rules_rerun")})
