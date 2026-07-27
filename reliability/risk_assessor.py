import difflib
from typing import Dict, List


def assess_risk(
    original_code: str,
    fixed_code: str,
    issues: List[Dict[str, str]],
) -> Dict[str, object]:
    """
    Simple, explicit risk assessment used as a guardrail layer.

    Returns a dict with:
    - score: int from 0 to 100
    - level: "low" | "medium" | "high"
    - reasons: list of strings explaining deductions
    - should_autofix: bool
    """

    reasons: List[str] = []
    score = 100

    if not fixed_code.strip():
        return {
            "score": 0,
            "level": "high",
            "reasons": ["No fix was produced."],
            "should_autofix": False,
        }

    original_lines = original_code.strip().splitlines()
    fixed_lines = fixed_code.strip().splitlines()

    # ----------------------------
    # Issue severity based risk
    # ----------------------------
    for issue in issues:
        severity = str(issue.get("severity", "")).lower()

        if severity == "high":
            score -= 40
            reasons.append("High severity issue detected.")
        elif severity == "medium":
            score -= 20
            reasons.append("Medium severity issue detected.")
        elif severity == "low":
            score -= 5
            reasons.append("Low severity issue detected.")

    # ----------------------------
    # Structural change checks
    # ----------------------------
    if len(fixed_lines) < len(original_lines) * 0.5:
        score -= 20
        reasons.append("Fixed code is much shorter than original.")

    if "return" in original_code and "return" not in fixed_code:
        score -= 30
        reasons.append("Return statements may have been removed.")

    if "except:" in original_code and "except:" not in fixed_code:
        # This is usually good, but still risky.
        score -= 5
        reasons.append("Bare except was modified, verify correctness.")

    # ----------------------------
    # Over-editing check
    # ----------------------------
    # The existing rules only catch a fix that is much *shorter*. A fix that
    # keeps a similar line count but rewrites most of the lines is still a
    # high-risk change (the agent did far more than the issues warranted).
    # Measure how much of the code churned and penalize heavy rewrites.
    if original_lines:
        similarity = difflib.SequenceMatcher(None, original_lines, fixed_lines).ratio()
        changed_fraction = 1.0 - similarity
        if changed_fraction > 0.6:
            score -= 30
            reasons.append(
                f"Fix rewrote {round(changed_fraction * 100)}% of the code (possible over-editing)."
            )

    # ----------------------------
    # Clamp score
    # ----------------------------
    score = max(0, min(100, score))

    # ----------------------------
    # Risk level
    # ----------------------------
    if score >= 75:
        level = "low"
    elif score >= 40:
        level = "medium"
    else:
        level = "high"

    # ----------------------------
    # Auto-fix policy
    # ----------------------------
    # Low overall risk is necessary but not sufficient. A single Medium severity
    # issue only costs 20 points, so it still lands at "low" (score 80) and would
    # auto-apply today. Tighten the policy: only auto-apply when every issue is
    # Low severity (or there are none). Anything Medium or higher defers to a
    # human, because those changes are the more costly ones to get wrong.
    max_severity_ok = all(
        str(issue.get("severity", "")).lower() in ("low", "", "unknown")
        for issue in issues
    )
    should_autofix = level == "low" and max_severity_ok

    if not max_severity_ok:
        reasons.append("A Medium or High severity issue is present; deferring to human review before auto-apply.")

    if not reasons:
        reasons.append("No significant risks detected.")

    return {
        "score": score,
        "level": level,
        "reasons": reasons,
        "should_autofix": should_autofix,
    }
