# Investor Profile Reference

Use this reference to shape `head-manager-interview` questions. It summarizes common investor-profile dimensions from financial suitability and appropriateness frameworks. It is not legal advice and does not turn TradingCodex into a regulated suitability determination system.

Sources checked on 2026-06-07:

- KOFIA Standard Investment Recommendation Rules: https://law.kofia.or.kr/service/law/lawFullScreenContent.do?historySeq=1421&seq=149
- Woori Bank investor profile questionnaire example: https://svc.wooribank.com/svc/jcc?__ID=c042641&withyou=RPRPS0671
- FINRA Rule 2111 Suitability: https://www.finra.org/rules-guidance/rulebooks/finra-rules/2111
- SEC Regulation Best Interest small entity compliance guide: https://www.sec.gov/resources-small-businesses/small-business-compliance-guides/regulation-best-interest
- ESMA MiFID II Article 25 suitability and appropriateness: https://www.esma.europa.eu/publications-and-data/interactive-single-rulebook/mifid-ii/article-25-assessment-suitability-and

## Common Dimensions

KOFIA emphasizes interview/questionnaire-based collection of investment purpose, financial situation, investment experience, age, risk-bearing capacity, income level, and financial asset weight. It also describes investor type classification with at least five levels and periodic review of question/classification quality.

Korean retail questionnaires commonly ask about product understanding, income source stability, annual income band, product experience, share of assets in investment products, investment purpose, acceptable loss level, derivative/product experience, current fund purpose, principal-protection attitude, loss tolerance, and intended investment period. One retail example states that investor-profile analysis can be reused for 12 months before refresh.

FINRA Rule 2111 and SEC Regulation Best Interest both describe customer or retail-customer investment profile factors such as age, other investments, financial situation and needs, tax status, investment objectives, investment experience, time horizon, liquidity needs, risk tolerance, and other disclosed information.

ESMA MiFID II Article 25 distinguishes knowledge and experience, financial situation including ability to bear losses, investment objectives, and risk tolerance; it also treats appropriateness information as product/service-specific.

## Interview Question Bank

Use only the questions needed for the current profile gap.

- Objectives: What is this capital for, and what would count as success?
- Horizon: When might the money be needed, and which portion is long-term?
- Liquidity: How much must remain liquid for living expenses, taxes, obligations, or emergencies?
- Income stability: Is income stable, variable, declining, or dependent on market/business cycles?
- Assets and debts: What broad ranges describe liquid assets, invested assets, illiquid assets, and debts?
- Tax: Are there taxable accounts, retirement accounts, foreign tax issues, or realized-gain constraints?
- Experience: Which products has the user actually bought, held, sold, or researched?
- Complex products: Has the user used margin, options, futures, structured products, leveraged/inverse ETFs, crypto derivatives, or private funds?
- Risk tolerance: What drawdown would feel uncomfortable, thesis-breaking, or unacceptable?
- Risk capacity: What loss could be absorbed without impairing required spending or obligations?
- Concentration: What maximum single-name, sector, country, or asset-class exposure is acceptable?
- Restrictions: Are any assets, sectors, brokers, jurisdictions, or strategies off-limits?
- Decision style: Does the user prefer concise calls, quantified scenarios, debate, checklists, or slow confirmation?
- Tone: Should the agent be blunt, cautious, Socratic, coaching-oriented, Korean-first, English-first, or bilingual?

## Interpretation Guidance

Keep tolerance and capacity separate. A user may emotionally tolerate volatility but lack capacity because of liquidity needs, debt, taxes, or near-term spending.

For conflicts, use the more conservative constraint in TradingCodex workflow planning and record the mismatch. Examples include high return targets with short horizons, high risk appetite with low emergency liquidity, or interest in complex products without experience.

Use broad labels only as shorthand, not as deterministic scoring. Reasonable labels include conservative, moderate-conservative, balanced, growth-oriented, aggressive, and speculative. Korean-style labels can include stable, stable-growth, risk-return neutral, active, and aggressive.

Never infer permission to trade from a profile label. TradingCodex still requires scenario gates, subagent artifacts, structured order intents, authorized approval, approval receipts, MCP execution, and audit events.
