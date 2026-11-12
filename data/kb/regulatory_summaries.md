# Regulatory Summaries (RiskDesk paraphrase, checked against primary sources on 12 November 2026)

These are paraphrases in RiskDesk's own words, not quotations, except where a short phrase is marked. Sources: Bank of England SS1/23 page (bankofengland.co.uk); Federal Reserve SR 26-2 letter and footnote 3 (federalreserve.gov); Basel market-risk framework (bis.org). Re-check before any external use, since both UK and US texts are updated from time to time.

## PRA SS1/23 overview
PRA SS1/23, Model risk management principles for banks, was published on 17 May 2023 and took effect on 17 May 2024. The current version was published and took effect on 23 April 2026, following the LIAF01/26 amendments round. The page does not say what the 2026 update changed; check the linked PDF. The statement applies to UK-incorporated banks, building societies and certain PRA-designated investment firms that hold internal model approval for credit, market or counterparty credit risk capital.

## PRA SS1/23 principles
SS1/23 sets out five principles: (1) model identification and model risk classification; (2) governance; (3) model development, implementation and use; (4) independent model validation; (5) model risk mitigants. The principles apply regardless of technology and cover models used to inform business decisions, whether built in-house or bought from vendors.

## PRA SS1/23 model inventory and tiering
Under principle 1, a firm should have a formal definition of a model and a detailed model inventory, with each model classified by risk. The tier should reflect the materiality of the decisions the model supports, not only its complexity.

## PRA SS1/23 independent validation
Under principle 4, validation should be independent of model development. It should test the conceptual soundness of the approach, its implementation and its outcomes. Validators should challenge assumptions and document their findings.

## PRA SS1/23 ongoing monitoring
Models should be monitored for performance drift, data quality and changes in use, and triggers for re-validation should be defined in advance and recorded. Monitoring and mitigants sit under principles 3 and 5.

## SR 26-2 overview
SR 26-2 is revised guidance on model risk management issued by the Federal Reserve on 17 April 2026. It supersedes SR 11-7 (issued 4 April 2011) and SR 21-8 (the BSA/AML model risk statement). The OCC and FDIC issued parallel documents. The letter is expected to be most relevant to banking organisations with over 30 billion US dollars in total assets regulated by the Federal Reserve.

## SR 26-2 model definition and scope
Footnote 3 of SR 26-2 states that generative AI and agentic AI models are novel and rapidly evolving, and are therefore not within the scope of the guidance. It adds that a banking organisation's risk management and governance practices should still guide the controls for any tools, processes or systems not covered, and that the principles apply to traditional statistical and quantitative models and to non-generative, non-agentic AI models. So a generative or agentic AI component, such as RiskDesk's drafting agent, is outside SR 26-2 by the letter's own terms, but still needs governance.

## SR 26-2 governance expectations
Governance should assign clear ownership of each model, require documentation, and provide effective challenge by people who are not the model's developers. Expectations scale with materiality.

## Basel market-risk framework summary
The Basel market-risk framework sets capital requirements for trading book exposures. Under MAR33.2 and MAR33.3, internal models must compute Expected Shortfall daily, both bank-wide and for each desk using the internal models approach, at a 97.5th percentile one-tailed confidence level. Internal models must also be backtested. Backtesting uses 250 observations at 99%. The Basel traffic-light zones are green for 0 to 4 exceptions, amber for 5 to 9 (MAR32 Table 1, confirmed in the primary PDF), and red for 10 or more. Green results do not by themselves show a model is accurate, and red results usually signal a model problem. Capital add-ons by zone are set in the Basel text and should be read from the source.

## Audit trail expectations
Supervisors expect an audit trail that shows who changed a model or a limit, when, why and with what approval. Records should be tamper-evident.

## Human oversight of automated decisions
Where automation influences a risk decision, a human should be able to review the evidence, override the outcome and record the reason. Automated actions that change a limit or a position need explicit approval.
