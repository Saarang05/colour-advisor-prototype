# Synthetic results (invented process, not client data)

300 simulated changeovers, seed 7. Accept at mean dE2000 <= 1.0.

Starting error before any correction: median mean-dE2000 = 2.51, 10th-90th percentile 1.37 to 4.39.

Headline settings: measurement noise 0.15 Lab units, engineer's mental-model error 50%, advisor starting-model error 25%.

CAUTION: neither manual loop below is calibrated to real QC engineers. 'Crude' only changes one channel at a time; 'Expert by eye' does combined changes but never learns from the lab. Treat them as a bracket, not a baseline. The real baseline comes from the client's lab logs.

| Measure | Manual (crude) | Manual (expert by eye) | Advisor |
|---|---|---|---|
| Median rounds to accept | 7 | 1 | 1 |
| Accepted within 1 round | 8% | 84% | 84% |
| Accepted within 2 rounds | 13% | 90% | 89% |
| Not accepted after 8 rounds | 37% | 9% | 10% |
| Median variants printed | 42 | 6 | 3 |
| Median TRUE dE2000 at the end | 1.01 | 0.66 | 0.63 |
| False accepts (true dE2000 > 1.5) | 0% | 0% | 0% |

Share of events where NO change to the file can reach dE2000 <= 1.0 (best achievable is above tolerance): 6%. These are mostly kiln-type shifts. A real tool must say so instead of iterating.

Same comparison restricted to the 256 events where the file CAN fix it (best achievable dE2000 <= 0.7):

| Measure (fixable events only) | Manual (crude) | Manual (expert by eye) | Advisor |
|---|---|---|---|
| Median rounds to accept | 6 | 1 | 1 |
| Accepted within 1 round | 9% | 95% | 95% |
| Accepted within 2 rounds | 16% | 100% | 98% |
| Not accepted after 8 rounds | 29% | 0% | 1% |

## Sensitivity (advisor, share accepted within 2 rounds / not accepted at all)

| Noise (Lab sd) \ starting-model error | 15% | 25% | 50% | 100% |
|---|---|---|---|---|
| 0.05 | 90% / 9% | 89% / 9% | 84% / 11% | 53% / 17% |
| 0.15 | 89% / 10% | 89% / 10% | 81% / 10% | 53% / 21% |
| 0.3 | 87% / 9% | 87% / 10% | 77% / 12% | 48% / 24% |
| 0.6 | 49% / 19% | 49% / 19% | 38% / 26% | 20% / 51% |

## Sensitivity (manual loop, same noise levels)

| Noise (Lab sd) | Within 2 rounds | Not accepted | Median rounds |
|---|---|---|---|
| 0.05 | 16% | 32% | 6 |
| 0.15 | 13% | 37% | 7 |
| 0.3 | 11% | 50% | 8 |
| 0.6 | 6% | 76% | 8 |
