"""Outcome detection: fill in what happened after a decision from signals that already exist.

Detectors read the store itself (overrides, reversal links, failed actions, human redos),
git history (reverts, merges) and event feeds from business systems (Stripe, Zendesk, Jira,
GitHub, PagerDuty, or any JSONL), plus an opt-in "no complaint after N days" rule. Results
are new outcome records (``recorded_by`` a system actor, evidence attached); a human-recorded
outcome is never overridden.
"""

from decisiontrace.outcomes.base import Signal, apply, plan

__all__ = ["Signal", "apply", "plan"]
