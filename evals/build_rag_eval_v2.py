"""Build evals/rag_eval_v2.jsonl: paraphrased retrieval questions with gold section IDs.

The questions avoid copying the headings. Every gold ID is checked against the knowledge base, so a
typo fails here rather than silently lowering recall.

Limitation: the author wrote these questions and also wrote the knowledge base. An independent
reviewer should write a fresh set before any retrieval claim is made.
"""
import json
import os
import sys

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)
from riskdesk.config import KB_DIR, RAG_V2_PATH  # noqa: E402
from riskdesk.rag.index import chunk_section  # noqa: E402

Q = [
    ("Who needs to hear about a desk that has moved into the early-warning band, and by what time?", "escalation_matrix#level-1-desk-head"),
    ("Which manager is told on the same day that a limit has been exceeded?", "escalation_matrix#level-2-market-risk-manager"),
    ("A limit excess has run for several days. Who decides whether a temporary excess is allowed?", "escalation_matrix#level-3-head-of-market-risk"),
    ("Under what conditions does an automated investigation go to a person for resolution?", "escalation_matrix#human-review-queue-for-agent-cases"),
    ("How fast must a faulty or late quote be reported to whoever owns the feed?", "escalation_matrix#data-incidents"),
    ("How long must records of escalation decisions be kept?", "escalation_matrix#documentation"),
    ("Who owns the limits, and who owns the positions they constrain?", "limit_policy#scope-and-ownership"),
    ("What percentage of a hard limit triggers an early-warning status?", "limit_policy#hard-limits-and-warning-levels"),
    ("Can an excess be closed by raising the limit, and what must the analyst do first?", "limit_policy#breach-response"),
    ("What test must a price pass before we treat a move as real market behaviour?", "limit_policy#data-quality-before-market-conclusions"),
    ("At what level relative to baseline VaR does a hard limit count as set in error?", "limit_policy#limit-calibration"),
    ("Which scenarios feed the stress loss limit?", "limit_policy#stress-limit"),
    ("In what units is vega added up for the vega limit?", "limit_policy#vega-limit"),
    ("Is changing the lookback length of the VaR a change that needs validation?", "limit_policy#model-and-methodology-changes"),
    ("What does a 99% one-day VaR figure actually promise?", "market_risk_reference#value-at-risk-definition"),
    ("How does the historical approach revalue a book without assuming any distribution?", "market_risk_reference#historical-simulation"),
    ("Why might a normal-distribution risk estimate miss losses on a book full of options?", "market_risk_reference#parametric-delta-normal-var"),
    ("How do you generate correlated scenarios for a simulation-based VaR?", "market_risk_reference#monte-carlo-var"),
    ("What does the average of the worst tail losses measure, and why is it preferred?", "market_risk_reference#expected-shortfall"),
    ("How can a portfolio's VaR be split across positions so the parts add up to the total?", "market_risk_reference#component-and-marginal-var"),
    ("Which sensitivity captures exposure to changes in implied volatility?", "market_risk_reference#greeks"),
    ("What question does a severe scenario answer that a statistical measure cannot?", "market_risk_reference#stress-testing"),
    ("How many exceptions over 250 days put a model into the highest-concern zone?", "market_risk_reference#var-backtesting"),
    ("Which likelihood-based test checks whether the exception rate matches the confidence level?", "market_risk_reference#kupiec-proportion-of-failures-test"),
    ("Which UK authority issued the model risk statement, and when did its current version take effect?", "regulatory_summaries#pra-ss1-23-overview"),
    ("How many principles does the UK model risk statement set out, and what are they?", "regulatory_summaries#pra-ss1-23-principles"),
    ("What should a firm keep for each model, and how is its risk category decided?", "regulatory_summaries#pra-ss1-23-model-inventory-and-tiering"),
    ("Who must be separate from the model developers when a model is tested?", "regulatory_summaries#pra-ss1-23-independent-validation"),
    ("What signals should trigger a re-test of a model after it goes live?", "regulatory_summaries#pra-ss1-23-ongoing-monitoring"),
    ("Which US letter replaced the 2011 model risk guidance, and when?", "regulatory_summaries#sr-26-2-overview"),
    ("Does the new US model risk letter cover agentic AI systems?", "regulatory_summaries#sr-26-2-model-definition-and-scope"),
    ("What does the US letter expect about who owns each model?", "regulatory_summaries#sr-26-2-governance-expectations"),
    ("What does the Basel market risk standard require for backtesting internal models?", "regulatory_summaries#basel-market-risk-framework-summary"),
    ("What properties should a log of limit changes have so auditors can rely on it?", "regulatory_summaries#audit-trail-expectations"),
    ("When an automated system affects a risk decision, what must a person be able to do?", "regulatory_summaries#human-oversight-of-automated-decisions"),
    ("How does a limit warning differ from a breach in the status classification?", "limit_policy#hard-limits-and-warning-levels"),
    ("What must a desk head be told about before any action on a warning?", "escalation_matrix#level-1-desk-head"),
    ("What does the theta sensitivity describe?", "market_risk_reference#greeks"),
    ("Which approach to VaR assumes returns follow a bell curve?", "market_risk_reference#parametric-delta-normal-var"),
    ("How are the stress scenarios that feed a limit chosen?", "limit_policy#stress-limit"),
    ("Who may approve a change to a hard limit?", "limit_policy#limit-calibration"),
    ("Which team is told when a price is judged faulty?", "escalation_matrix#data-incidents"),
    ("Is changing the confidence level of a model a methodology change?", "limit_policy#model-and-methodology-changes"),
    ("What role does a second-line reviewer play when a limit changes?", "limit_policy#limit-calibration"),
    ("What happens if an early warning persists for three days?", "escalation_matrix#level-1-desk-head"),
    ("Can an agent apply a new limit value on its own?", "limit_policy#limit-calibration"),
    ("What happens to the record of who decided an escalation?", "escalation_matrix#documentation"),
    ("How are past windows of market moves used to shock a current portfolio?", "market_risk_reference#historical-simulation"),
    ("Which measure is a sum of contributions that add exactly to the total?", "market_risk_reference#component-and-marginal-var"),
    ("How do you test a model's exception count against its expected count?", "market_risk_reference#kupiec-proportion-of-failures-test"),
    ("How many exceptions are expected per 250 days at 99%?", "market_risk_reference#var-backtesting"),
    ("What controls must a live AI tool have when it touches risk decisions?", "regulatory_summaries#human-oversight-of-automated-decisions"),
    ("What should a monitoring plan's re-validation triggers be based on?", "regulatory_summaries#pra-ss1-23-ongoing-monitoring"),
    ("Is vega measured per vol point or per unit of volatility in the limit?", "limit_policy#vega-limit"),
    ("Who may allow a limit to stay exceeded temporarily?", "escalation_matrix#level-3-head-of-market-risk"),
    ("What was the outcome of incident INC-0007?", "INC-0007"),
    ("What happened in incident 12?", "INC-0012"),
    ("Describe incident INC-0020.", "INC-0020"),
    ("What is recorded for incident INC-0033?", "INC-0033"),
]


def main() -> None:
    sections = {c.section_id: c for c in chunk_section(KB_DIR)}
    rows = []
    for q, gold in Q:
        if gold.startswith("INC-"):
            matches = [sid for sid in sections if sid.startswith("incident_logs#" + gold.lower() + "-")]
            assert len(matches) == 1, f"incident {gold} not unique/found: {matches}"
            gold = matches[0]
        assert gold in sections, f"unknown gold section: {gold}"
        rows.append({"q": q, "chunk": gold})
    with open(RAG_V2_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(json.dumps(r) for r in rows) + "\n")
    print(f"wrote {len(rows)} questions to {RAG_V2_PATH}")


if __name__ == "__main__":
    main()
