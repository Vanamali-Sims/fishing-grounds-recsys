# Model card — fishing-grounds-recsys

## Intended use

Portfolio / research demo. Score 0.1° ocean cells a commercial fishing vessel has not fished, using implicit ALS on AIS apparent-fishing-effort (2023–2024, Australian EEZ). The same factors flag low-score observed activity as a **prompt for a human**, not a verdict.

Not intended for enforcement, catch advice, or navigation.

## Users and items

| Recsys noun | Here |
| --- | --- |
| user | Vessel MMSI (noisy identity) |
| item | 0.1° cell, lower-left corner |
| implicit weight | Apparent fishing hours |

Absence is not dislike. Transit (`fishing_ratio < 0.05`) is dropped at matrix time, not in silver.

## Models

- **Implicit ALS** (Hu, Koren & Volinsky 2008). Confidence `1 + α log1p(hours)`. Reported: 32 factors, α=10, reg=0.1, 12 iterations.
- **Content fold-in.** Ridge map from gear, flag, log length/tonnage/power → ALS user factors, fit on warm vessels. Used when the train row is empty.
- **Season.** Southern-hemisphere climatology (DJF/MAM/JJA/SON). ALS scores are multiplied by a 0.25–1.0 weight from mean yearly hours in that season. This is a prior, not a second latent model.
- **Effort forecast.** Same climatology ranked as predicted hours. Not a dynamical or weather model.

## Evaluation

Temporal split: train through 2024-09-30, test Q4 2024. Relevance is **new grounds** (warm) or first-seen vessels (cold). Leak check: train history vs new-grounds must score precision 0.

Australian EEZ, 177 warm vessels with Q4 new grounds:

| Model | P@10 | MAP@10 |
| --- | --- | --- |
| Popularity | 0.0011 | 0.0011 |
| Popularity-by-gear | 0.0040 | 0.0021 |
| Implicit ALS | 0.0814 | 0.0798 |
| Content fold-in (warm) | 0.0192 | 0.0132 |

Cold-start (9 vessels): fold-in P@10 = 0.0556; popularity-by-gear P@10 = 0.000.

## Constraints

Recommendations can drop cells with `in_mpa=True` from WDPA Sep 2026 Australian marine/coastal polygons (centroid-in-polygon). This is a coarse filter: multiple-use zones that still allow fishing are treated as protected. It is not a zoning engine.

## Failure modes

- AIS coverage changes look like effort changes.
- MMSI reuse / sharing mixes vessels.
- 2024 GFW classifications are provisional.
- Small / non-AIS fleets are invisible.
- Season weight can bury a true new ground that is unused in that season in the training years.
- Forecast will repeat last year’s seasonal map if the fishery shifts.

## Data and licence

GFW v3 apparent effort, CC BY-NC 4.0. GEBCO 2026 (southern-Australia subset). Marine Regions EEZ v12. GFW Named Anchorages. WDPA/WDPCA Sep 2026 AUS geodatabase. See [DATA.md](../DATA.md).

## Contact / responsibility

Low ALS scores are not evidence of illegal fishing. Do not use this system to target vessels or open closed water.
