# BugHound Mini Model Card (Reflection)

Filled out after running BugHound in **both** modes (Heuristic and Gemini).

---

## 1) What is this system?

**Name:** BugHound 🐶

**Purpose:** A small agentic system that analyzes a Python snippet, proposes a fix
for the issues it finds, and runs a reliability/risk check to decide whether that
fix is safe enough to auto-apply or should be deferred to a human. It is a
demonstration of an agent that moves from *commenting* on code to *acting* on it,
with an explicit safety layer between the proposal and the action.

**Intended users:** Students and engineers learning agentic workflows, LLM
integration, and AI reliability concepts. It is a teaching tool, not a
production linter — its heuristics are intentionally simple so the decision points
are easy to inspect.

---

## 2) How does it work?

BugHound runs a five-stage agentic loop, defined in `BugHoundAgent.run()`:

1. **PLAN** – Logs that it is starting a scan + fix-proposal workflow. (Fixed plan,
   no branching.)
2. **ANALYZE** – Detects issues. Chooses its tool based on `_can_call_llm()`:
   - **Heuristic mode (offline):** three substring/regex rules — `print(` →
     Code Quality/Low, bare `except:` → Reliability/High, `TODO` →
     Maintainability/Medium.
   - **Gemini mode:** sends `analyzer_system.txt` + `analyzer_user.txt` to the
     model, which must return a JSON array of `{type, severity, msg}` objects.
     The agent then **validates** each issue (recognized severity + non-empty
     message) and falls back to heuristics if the output is unparseable or
     nothing valid survives.
3. **ACT** – Proposes a fix. If there are no issues, it returns the original code
   unchanged. Otherwise it uses the heuristic fixer (regex swaps) or the Gemini
   fixer (`fixer_system.txt` asks for a minimal, behavior-preserving rewrite,
   full code only). Empty or fenced-only LLM output falls back to heuristics.
4. **TEST** – Calls `assess_risk()` to score the change 0–100, assign a level
   (low/medium/high), and set `should_autofix`.
5. **REFLECT** – Logs whether the fix is safe enough to auto-apply under the
   current policy, or recommends human review.

**Heuristics vs. Gemini:** Heuristics are deterministic, offline, and free but
shallow (pure string matching). Gemini is context-aware but rate-limited (~20
requests/day on the free tier) and non-deterministic. Every Gemini path has a
heuristic fallback, so the system degrades safely when the API fails, is rate
limited, or returns malformed output.

---

## 3) Inputs and outputs

**Inputs:** Short Python snippets pasted into the UI or loaded from `sample_code/`.
Shapes tested:

- `sample_code/cleanish.py` – a clean function using `logging` (should be left
  alone).
- `sample_code/mixed_issues.py` – a function with a `print`, a bare `except:`, a
  `TODO`, and a `try/return` block (multiple, mixed-severity issues).
- `sample_code/print_spam.py` – a function with several `print` calls.
- `sample_code/flaky_try_except.py` – a bare-`except`-returns-`None` block.
- A **comment-only** snippet containing `TODO` and the text `prints(x)` inside
  comments (weird/edge case).
- An **empty file** (weird/edge case).

**Outputs:**

- **Detected issues** – a list of `{type, severity, msg}`. Example (mixed_issues):
  Code Quality/Low, Reliability/High, Maintainability/Medium.
- **Proposed fix** – rewritten code + a unified diff. Heuristic fixer prepends
  `import logging`, swaps `print(` → `logging.info(`, and converts `except:` →
  `except Exception as e:` with a placeholder comment.
- **Risk report** – `score`, `level`, `should_autofix`, and human-readable
  `reasons`. Examples observed:
  - `cleanish.py`: 100 / low / autofix YES (no changes made).
  - `mixed_issues.py`: 30 / high / autofix NO (high-severity issue dominates).
  - comment-only (`TODO`): 80 / low, but autofix **NO** after the Part 3 change.
  - empty file: 0 / high / autofix NO ("No fix was produced").

---

## 4) Reliability and safety rules

**Rule A — Empty fix ⇒ score 0, high, no auto-fix** (`risk_assessor.py`, top of
`assess_risk`).

- **Checks:** whether `fixed_code` is blank.
- **Why it matters:** an empty rewrite would wipe the user's code; treating it as
  maximally risky prevents a catastrophic auto-apply and forces the "no fix
  produced" warning in the UI.
- **False positive:** a snippet whose *correct* fix is genuinely "delete this
  file" would be flagged high-risk even though an empty result was intended (rare).
- **False negative:** it only catches a *fully* empty result. A fix that deletes
  90% of the code but leaves one line is not caught by this rule.

**Rule B — "Fixed code is much shorter than original" (< 50% of lines)**
(`risk_assessor.py`, structural checks).

- **Checks:** whether the fix has fewer than half the lines of the original.
- **Why it matters:** large deletions often mean the model dropped logic, error
  handling, or whole branches — a common LLM over-deletion failure.
- **False positive:** legitimately condensing verbose code (e.g., collapsing a
  10-line if/elif chain into a dict lookup) trips the rule even though behavior is
  preserved.
- **False negative:** the 50% threshold is permissive — a fix that removes 40% of
  the code passes clean. It also misses rewrites that keep the same line count but
  change most of the content (the over-editing gap addressed in Part 4).

*(Additional rule reviewed: the High-severity −40 deduction penalizes the*
*presence of a serious issue, not the quality of the fix, so a correct fix for a*
*bare `except:` still lands at "medium" and never auto-applies — arguably
*over-conservative.)*

---

## 5) Observed failure modes

**1. False positive from substring matching (comment-only snippet).**
Input: a file that was *only* comments — `# this prints(x) but is only a comment`
and `# TODO nothing`. The heuristic analyzer flagged a Maintainability/Medium
issue because the substring `TODO` appears anywhere in the text, including inside
a comment where it is not real unfinished logic. The analyzer cannot tell code
from comments or string literals, so it hallucinates issues.

**2. Over-editing trusted silently (risk blind spot).**
Constructed input: a 3-line `add(a, b)` function with a Low-severity style issue,
paired with a fix that renamed the params and rewrote every line
(`compute_sum`, `log_result`, etc.). Before the Part 4 guardrail, the risk report
returned **95 / low / autofix YES** — the agent would have silently auto-applied a
near-total rewrite for a cosmetic issue. The scorer only checked whether the fix
got *shorter*, never how much of it *churned*.

*(A third, related mode: `MockClient` returns non-JSON on purpose, and the agent*
*correctly falls back to heuristics and logs it — a failure the system already*
*handles well.)*

---

## 6) Heuristic vs Gemini comparison

- **What Gemini detected that heuristics did not:** context-dependent problems the
  three hard-coded rules cannot express — e.g., swallowing errors by returning `0`
  from `except`, ambiguous naming, or logic that hides failures. Gemini can also
  phrase severity based on *intent* rather than a keyword match.
- **What heuristics caught consistently:** the exact three patterns they encode
  (`print(`, bare `except:`, `TODO`) — deterministically, every run, offline, and
  for free. Heuristics never "changed their mind" between runs.
- **How the fixes differed:** the heuristic fixer applies blunt, predictable regex
  swaps (and can corrupt `print(`/`except` inside strings). Gemini produces more
  natural rewrites but with less predictable scope, which is exactly what makes the
  over-editing guardrail necessary.
- **Did the risk scorer agree with intuition?** Mostly. It correctly flagged
  mixed_issues as high-risk. But it was **backwards** on good safety fixes
  (penalizing a correct bare-`except` fix) and **blind** to over-editing until we
  added the churn rule — so the scorer needed the Part 3 and Part 4 changes to
  match human judgment.

---

## 7) Human-in-the-loop decision

**Scenario:** BugHound proposes a fix that touches a **High- or Medium-severity
issue**, or that **rewrites more than 60% of the code**. In either case, the change
is high-consequence (error handling, control flow, or a near-total rewrite), and
the agent should **refuse to auto-apply** and require a human to review the diff.

- **Trigger:** `should_autofix = False` unless the fix is small (churn ≤ 60%) *and*
  every issue is Low severity or none. (Both triggers are now implemented.)
- **Where:** the **`risk_assessor`** — safety decisions belong in one auditable
  place, not scattered through the agent workflow or the UI. The agent and UI only
  *report* the decision; they do not make it.
- **Message to the user:** *"⚠️ This fix affects a Medium/High severity issue (or
  rewrites most of the code). BugHound will not auto-apply it — please review the
  diff before merging."*

---

## 8) Improvement idea

**Add a syntax-validity guardrail on the proposed fix.** Before `assess_risk`
runs, try to `compile(fixed_code)` (or `ast.parse`) the model's output. If it does
not parse as valid Python, treat it as a failed fix: force `should_autofix = False`,
mark the risk high, and fall back to the heuristic fixer with a logged reason.

- **Why it's low-complexity:** ~5 lines using the standard-library `ast` module,
  no new dependencies, and it slots into the existing fallback pattern.
- **Why it measurably increases reliability:** today the fixer accepts *any*
  non-empty string, so a truncated, prose-wrapped, or malformed rewrite can be
  presented as a "fix." A parse check turns "looks like code" into "provably
  parseable code," closing the biggest remaining gap between the strict fixer
  prompt and the lenient agent-side acceptance. It is directly testable with a
  `MockClient` that returns invalid Python, asserting the agent does not auto-fix.

---

*Changes made during this activity (all backed by offline tests, no API quota used):*

1. **Part 2 — output validation** (`bughound_agent.py`): the analyzer now drops
   issues with an unrecognized severity or empty message and falls back to
   heuristics if none are valid.
2. **Part 3 — tighter auto-fix policy** (`risk_assessor.py`): auto-fix requires all
   issues to be Low severity or none, so Medium-severity fixes defer to a human.
3. **Part 4 — over-editing guardrail** (`risk_assessor.py` + `tests/`): fixes that
   rewrite > 60% of lines are penalized and blocked from auto-apply, with a test
   that fails without the guardrail and passes with it.
