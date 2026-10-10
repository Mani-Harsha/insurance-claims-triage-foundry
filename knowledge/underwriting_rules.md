# Synthetic underwriting knowledge — version 1

These eight rules describe this assignment's mock policies, not actual insurer terms or legal advice. The machine-readable counterpart is `rules.json`. Both files are versioned and checked for matching rule IDs. This document is uploaded to Foundry File Search; the structured counterpart is indexed by local vector retrieval. Every deterministic decision includes retrieved evidence.

## UW01 — Covered perils
Homeowners: water_damage, theft, fire. Auto: collision, theft, liability. Other perils require investigation.

## UW02 — Per-claim limit
The amount must not exceed the policy limit. Equality passes coverage but is subject to UW05.

## UW03 — Active period
The loss date must be within active_from and active_to, inclusive. Coverage is based on the loss date.

## UW04 — Early policy claim
Reports from inception through day 7 require investigator review, regardless of amount. A report before inception also requires review.

## UW05 — Near-limit amount
Amounts between 98% and 100% of the limit, inclusive, require investigator review (within 2% of the limit). Above-limit amounts fail UW02.

## UW06 — Similar flagged history
A similar peril on the same policy with an earlier flagged loss within 365 days requires investigator review. Exclude the current claim and future/same-day events. This pattern is not proof of fraud.

## UW07 — Delayed reporting
Reports more than 30 days after the loss require supporting documentation.

## UW08 — Human decision
Validation or service failures require more documentation. Coverage failures/anomalies route to an investigator. Clean evidence permits an auto approve recommendation. Every recommendation is pending an adjuster's recorded decision. All data and recommendations are synthetic. Never accuse a policyholder of fraud.
