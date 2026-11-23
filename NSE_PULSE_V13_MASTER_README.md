# NSE-PULSE V13 --- Project Master README

> **Purpose:** This document is the single project-level summary for
> NSE-PULSE V13. It describes the goal, frozen research, V13 engine
> architecture, scoring system, market context, Score ≥77 research
> candidate, Below-72 diagnostic work, frontend/backend state,
> validation status, known limitations, and the remaining roadmap.

------------------------------------------------------------------------

## 1. PROJECT GOAL

**NSE-PULSE V13** is an NSE stock-screening and signal-generation system
designed to identify technically qualified intraday breakout/breakdown
setups, evaluate their confirmation quality, calculate execution/risk
levels, score the setup, and present the result through a live
dashboard.

The long-term goal is **not simply to produce more signals**.

The goal is to build a system that is:

-   technically rule-based,
-   point-in-time safe,
-   auditable,
-   explainable,
-   resistant to lookahead/data contamination,
-   validated on unseen data before production,
-   and eventually suitable for controlled paper trading / forward
    validation.

The project treats **research, engine logic, validation, and deployment
as separate stages**.

------------------------------------------------------------------------

# 2. SAFETY / ENVIRONMENT LOCKS

There are three important project locations:

  ----------------------------------------------------------------------------------------------------
  Version                 Path                                                 Rule
  ----------------------- ---------------------------------------------------- -----------------------

  V13 development         `E:\project\nse-screener prediction-v13-dev`   Current development
                                                                               project
  ----------------------------------------------------------------------------------------------------

Current V13 ports:

-   Backend: `8001`
-   Frontend: `3001`

Backend:

``` powershell
python -m uvicorn app.main:app --reload --port 8001
```

Frontend:

``` powershell
npm run dev -- -p 3001
```

Frontend API proxy targets:

``` text
http://127.0.0.1:8001/api/
```

------------------------------------------------------------------------

# 3. CURRENT PROJECT STATUS

## Current phase

**Phase 14--21: Frontend / Dashboard Integration and Validation**

Current sub-milestone:

> **V13 Score Transparency + Below-72 Diagnostic Layer**

The project has **NOT yet reached**:

-   Phase 22--23 local E2E completion,
-   paper trading,
-   forward validation,
-   production decision.

Those stages must remain blocked until the current frontend/diagnostic
milestone is accepted.

------------------------------------------------------------------------

# 4. ORIGINAL RESEARCH / FROZEN STATE

The V13 research was built around NSE-500 historical data.

The original V13 baseline full-NSE-500 result was:

``` text
Universe:              500 / 500
Qualified:             1601
Triggered / Closed:    1597
Wins:                    80
Losses:                 251
EOD:                   1266

Closed Win Rate:       5.01%
Average R:            -0.050R
Total R:              -79.26R
Maximum DD:           101.37R
```

A point-in-time daily DMA variant produced:

``` text
Closed WR:             ~6.95%
Average R:             -0.021R
Total R:              -65.97R
Maximum DD:            92.02R
```

These results establish why the project needs further validation and
filtering rather than assuming the baseline engine is profitable.

------------------------------------------------------------------------

# 5. V13 RESEARCH SPEC

The V13.1 research specification separates the system into:

## Detection

The engine considers:

-   Opening Range breakout/breakdown
-   breakout/breakdown structure
-   volume
-   EMA alignment
-   RSI
-   VWAP
-   ATR
-   previous-day levels
-   true velocity
-   market context
-   sector context

## Confirmation

Confirmation is based on:

### Bullish

1.  Retest of OR High
2.  Reclaim close above OR High
3.  Three consecutive completed closes above OR High
4.  Next 5-minute candle OPEN used for delayed entry

### Bearish

Mirror of the bullish process:

1.  Retest of OR Low
2.  Reclaim close below OR Low
3.  Three consecutive completed closes below OR Low
4.  Next 5-minute candle OPEN

Rules:

-   same-session only,
-   no lookahead,
-   if SL/T1 occurs before delayed entry, the setup is missed/invalid,
-   confirmation is distinct from initial detection.

------------------------------------------------------------------------

# 6. SIGNAL STATES

V13 intentionally separates:

### WATCH

A setup that crosses the production score threshold but is not
necessarily trade-ready.

### CONFIRMED

The technical setup has passed the required confirmation logic.

### TRADE-READY

A setup that has satisfied the relevant execution/risk conditions.

These states must **not** be collapsed into one label.

Similarly, score classification is separate from trade status.

------------------------------------------------------------------------

# 7. RISK MODEL

V13 exposes:

-   entry
-   stop-loss
-   target 1
-   target 2
-   risk amount
-   R:R to T1
-   R:R to T2
-   confidence/grade fields where supplied by the engine

The engine's execution levels are **signal-time anchored**.

They are not automatically a fresh market-entry recommendation at the
current LTP.

For example, a bullish setup may currently trade above T2 after the
signal was generated; a bearish setup may currently trade below its
original entry.

The frontend must preserve this distinction.

------------------------------------------------------------------------

# 8. H3 CONFIRMATION RESEARCH

An exact 18-case H3 experiment produced:

``` text
18 total
7 confirmed
2 delayed target
1 delayed SL
4 EOD
```

For the 7 confirmed trades:

``` text
Average: +0.3476R
Total:   +2.433R
```

This sample was explicitly considered **too small to establish
production validity**.

------------------------------------------------------------------------

# 9. SEPTEMBER H3 HOLDOUT

September holdout:

``` text
Requested/results/raw matched: 289
H3 confirmed:                   98
Confirmation rate:             33.91%
```

Delayed-entry outcomes:

``` text
Delayed target: 20
Delayed SL:     32
Delayed avg:    -0.0180R
Delayed total:  -1.7647R
```

Final outcomes:

``` text
EOD:        46
SL_FIRST:   32
T1_FIRST:   19
T2_FIRST:    1
```

------------------------------------------------------------------------

# 10. SEPTEMBER H3 REGIME FINDINGS

September H3 regime analysis:

  Regime       N    Avg R   Total R     PF
  --------- ---- -------- --------- ------
  ALIGNED     41   -0.072    -2.938   0.85
  NEUTRAL     11   -0.386    -4.247   0.06
  OPPOSED     46   +0.118    +5.420   1.33

The most interesting subgroup was:

> **BULL NIFTY × BEARISH STOCK**

September:

``` text
N:            32
Win rate:     62.5%
Target rate:   3.12%
SL rate:      12.5%
Average R:    +0.284R
Total R:      +9.087R
PF:             1.93
```

However, this result was later shown to be unstable across time and did
not survive true August OOS testing.

------------------------------------------------------------------------

# 11. SEPTEMBER TIMING

Signal → H3 timing:

``` text
Mean:   101.5 minutes
Median:  82.5 minutes
Min:     35 minutes
Max:    280 minutes
```

Descriptive timing buckets:

  Bucket         N     Avg R
  ----------- ---- ---------
  MID           37   -0.132R
  LATE          20   -0.121R
  VERY_LATE     41   +0.135R

These are descriptive observations, not deployed rules.

------------------------------------------------------------------------

# 12. RELATIVE WEAKNESS INVESTIGATION

The BULL NIFTY × BEARISH STOCK subgroup initially looked attractive.

September:

``` text
N = 32
Total = +9.087R
```

But chronology was unstable:

  Period             N    Avg R   Total R     PF
  --------------- ---- -------- --------- ------
  P1 Sep 1--3       14   -0.115    -1.617   0.72
  P2 Sep 4--7       13   +0.231    +2.999   1.74
  P3 Sep 8--9        0      ---       ---    ---
  P4 Sep 10--11      5   +1.541    +7.704    inf

Approximately **85% of the +9.087R** came from Sep 10--11.

Therefore this was judged unstable.

------------------------------------------------------------------------

# 13. TRUE AUGUST OOS TEST

August was used as a true unseen/OOS evaluation of the relative-weakness
idea.

Results:

``` text
Candidates:        686
Bearish:           385
Bullish:           301
Sessions:           21
Clean H3 trades:   209
```

Overall:

``` text
N:          209
Average R: -0.133R
Total R:  -27.875R
PF:          0.72
```

The BULL NIFTY × BEARISH STOCK subgroup:

``` text
N:           91
Average R: -0.301R
Total R:   -27.428R
PF:           0.47
Max DD:      29.64R
```

**Conclusion:**

The static relative-weakness filter was **NOT deployed**.

This is an important example of the project's fail-closed research
discipline: a promising in-sample September observation was rejected
after true OOS testing.

------------------------------------------------------------------------

# 14. IMMUTABLE COMBINED RESEARCH POPULATION

Combined August + September research population:

``` text
Total rows: 123
Total R:   -18.340954441577008R
```

This 123-row population became the basis for the score-threshold
investigation.

------------------------------------------------------------------------

# 15. SCORE DISTRIBUTION RESEARCH

Exact score-level results:

    Score    N       Avg R      Total R
  ------- ---- ----------- ------------
       72   29   -0.347519   -10.078062
       73   34   -0.403747   -13.727411
       74   17   +0.071296    +1.212026
       75   13   -0.170085    -2.211109
       76   13   -0.182652    -2.374479
       77    6   +0.760245    +4.561470
       78    3   -0.107644    -0.322931
       79    4   +0.706846    +2.827385
       80    1   -1.000000    -1.000000
       82    1   +0.296772    +0.296772
       85    1   +2.093218    +2.093218
       87    1   +0.382166    +0.382166

The strongest change in observed behaviour was around the high-70s.

------------------------------------------------------------------------

# 16. SCORE ≥77 RESEARCH RESULT

A threshold search was performed.

The important candidate became:

> **Score ≥77**

Combined result:

``` text
N:            17
Total R:      +8.838079567015813R
Average R:    +0.5198870333538713R
Wins:         13
Losses:        4
Win rate:     76.4706%
PF:            3.43047
Max DD:        1R
Best trade:   +2.0932R
Worst trade:  -1R
```

This is **promising research evidence**, not proof of future
profitability.

------------------------------------------------------------------------

# 17. AUGUST / SEPTEMBER SCORE ≥77

### August

``` text
N:             9
Total R:      +3.289045R
Average R:    +0.365449R
Wins:          6
Losses:        3
Win rate:     66.67%
PF:            2.09635
Max DD:        1R
```

### September

``` text
N:             8
Total R:      +5.549034R
Average R:    +0.693629R
Wins:          7
Losses:        1
Win rate:     87.5%
PF:            9.7199
Max DD:        0.63636R
```

The threshold worked positively in both months in this frozen research
population.

------------------------------------------------------------------------

# 18. OTHER HIGH-SCORE BANDS

Score 77--79:

``` text
N:          13
Total R:   +7.065924R
Average:   +0.543533R
Wins:       10
Losses:      3
PF:          3.68018
```

Score 80+:

``` text
N:           4
Total R:    +1.772156R
Average:    +0.443039R
Wins:        3
Losses:      1
PF:           2.77216
```

------------------------------------------------------------------------

# 19. AUGUST-TRAINED THRESHOLD → SEPTEMBER

Using August to select the threshold and applying it unchanged to
September:

``` text
August ≥77:
N = 9
Total = +3.289045R
Average = +0.365449R
Win rate = 66.667%
```

September ≥77:

``` text
N = 8
Total = +5.549034R
Average = +0.693629R
Win rate = 87.5%
```

This was important because the threshold was not selected solely on
September.

------------------------------------------------------------------------

# 20. THRESHOLD STABILITY / LOO

Leave-one-date-out testing remained positive for both months.

For September, even removing Sep 10 left:

``` text
Total = +1.220392R
N = 5
```

This reduces, but does not eliminate, concern about concentration.

------------------------------------------------------------------------

# 21. RANDOMIZATION TESTS

## Same-N score shuffle

100,000 permutations:

``` text
Observed total: +8.838R
Better/equal:   186
Empirical p:    0.00186998
Percentile:     99.814%
```

## Threshold-selection permutation

100,000 permutations searching thresholds 72--85:

``` text
Observed best threshold: 77
Observed N:              17
Observed total:          +8.838R

Better/equal:             584
Adjusted p:               0.00584994
Percentile:              99.416%
```

Random best-threshold distribution:

``` text
Mean: +1.2286R
P95:  +5.4809R
P99:  +8.0369R
```

These tests make Score ≥77 a serious research candidate.

They do **not** make it a production rule yet.

------------------------------------------------------------------------

# 22. FROZEN OOS STATUS

The rule:

``` text
Score ≥77
```

was frozen as:

> **FROZEN OOS CANDIDATE / RESEARCH-PASS**

It is **NOT** yet a production hard filter.

Freeze manifest:

``` text
Rule:                 Score ≥77
Cutoff:               2026-09-10 22:15
Historical rows:      123
Historical total R:  -18.340954441577008
Score ≥77 rows:       17
Score ≥77 total R:    +8.838079567015813
Future rows at freeze: 0
Status:               FROZEN_OOS_RULE
```

Manifest SHA256:

``` text
33589D821E3B6A8639FF1F53D0D827860E0DF1E43346A32926F82D5CF352629E
```

Forward ledger source:

``` text
v13_1_score77_forward_oos_results.csv
```

Current state:

``` text
NO_FORWARD_SOURCE_YET
```

There are no legitimate post-cutoff forward results yet.

**Do not force historical rows into the forward ledger.**

------------------------------------------------------------------------

# 23. MASTER OOS GATE

Current gate status:

``` text
Manifest integrity:          PASS
Historical lock:             PASS
Cutoff:                      2026-09-10 22:15
Historical rows:             123
Future rows at freeze:       0
Forward Score ≥77 rows:      0
Status:                      NO_FORWARD_SIGNALS
```

This means the project has a frozen candidate but has not yet
demonstrated live forward performance.

------------------------------------------------------------------------

# 24. NIFTY MARKET CONTEXT

V13 has a point-in-time NIFTY context module.

The context includes:

-   NIFTY direction
-   NIFTY close
-   ATR %
-   bar range %
-   range expansion
-   slope5
-   slope12
-   extension in ATR
-   signal time
-   bars used

The market context is calculated point-in-time:

``` text
data = data[data.index <= signal_time]
```

Minimum required history is 20 bars.

Direction is based on the sign of the 5-bar slope.

------------------------------------------------------------------------

# 25. VERIFIED NIFTY FORMULAS

Several NIFTY metrics were reverse-engineered exactly.

## ATR %

``` text
rolling 14-bar mean True Range / last close × 100
```

## Bar range %

The investigated exact sample was:

``` text
(High - Low) / Open × 100
```

## Slope5

``` text
((Close_now / Close_5_bars_ago) - 1) × 100 / 5
```

## Slope12

``` text
((Close_now / Close_12_bars_ago) - 1) × 100 / 12
```

## Extension ATR

``` text
(last close - EMA20) / rolling 14-bar mean TR
```

------------------------------------------------------------------------

# 26. RANGE EXPANSION --- IMPORTANT UNRESOLVED ITEM

**Range expansion formula has NOT been recovered exactly.**

An exhaustive hypothesis investigation was performed.

The best candidate found was based on a prior-60 high/low median.

Results:

``` text
Exact matches:             0 / 119
Within 0.1%:              75 / 119
Within 1%:               119 / 119

Mean relative error:       0.001333
Median absolute error:     0.000852
Maximum absolute error:    0.033204

Implied denominator:
Mean absolute difference:  0.017818
Median difference:         0.003600
Mean ratio:                 1.000594
Median ratio:               1.0000048
Min ratio:                  0.9952
Max ratio:                  1.00504
```

Because there was **no exact match**, the formula was intentionally
**not guessed**.

Current implementation therefore leaves:

``` text
nifty_range_expansion = None
```

This is a deliberate fail-closed decision.

**Do not invent a range-expansion formula.**

------------------------------------------------------------------------

# 27. CURRENT VERIFIED LIVE NIFTY CONTEXT

Latest verified live context during development:

``` text
Signal time:          2026-09-15 13:00
NIFTY direction:      BEARISH
NIFTY close:          23311.900390625
ATR %:                 0.13700862255277987
Bar range %:           0.06757061355357243
Range expansion:      None
Slope5:               -0.020997240011224605
Slope12:              -0.02667094593270432
Extension ATR:        -1.1600123177752772
Bars used:            516
```

These values are point-in-time context values and should not be
interpreted as a trading prediction by themselves.

------------------------------------------------------------------------

# 28. CURRENT ENGINE ARCHITECTURE

Main engine:

``` text
backend/app/v13_engine.py
```

Scanner:

``` text
backend/app/v13_scanner.py
```

Market context:

``` text
backend/app/v13_market_context.py
```

API:

``` text
backend/app/main.py
```

Frontend:

``` text
frontend/src/
```

Important engine model objects include:

-   V13Candidate
-   \_DirectionEvaluation

The engine now exposes:

``` text
score_breakdown
```

and:

``` text
breakout_candle_range
```

------------------------------------------------------------------------

# 29. SCORE BREAKDOWN

The current engine attribution is designed to expose these components:

``` text
1.  trend_structure
2.  ema_alignment
3.  vwap_alignment
4.  rsi_momentum
5.  volume
6.  opening_range
7.  previous_day_level
8.  candle_quality
9.  market_sector_alignment
10. true_velocity
11. extension_chase
12. trade_risk_penalties
```

The instrumentation records the local contribution of each section
without changing the underlying scoring rules.

The attribution was validated component-by-component:

``` text
trend_structure           PASS
ema_alignment             PASS
vwap_alignment            PASS
rsi_momentum              PASS
volume                    PASS
opening_range             PASS
previous_day_level        PASS
candle_quality             PASS
market_sector_alignment   PASS
true_velocity              PASS
extension_chase             PASS
trade_risk_penalties      PASS
```

------------------------------------------------------------------------

# 30. SCORE BREAKDOWN EXAMPLE

A historical AFCONS direct evaluation produced:

``` text
Trend Structure          +8
EMA Alignment           +10
VWAP Alignment          +10
RSI Momentum              +8
Volume                   +12
Opening Range            +18
Previous Day Level        +7
Candle Quality             0
Market/Sector Alignment    0
True Velocity              +6
Extension Chase             0
Trade/Risk Penalties      -5
--------------------------------
Final Score                74
```

The sum equals 74.

This validates that score transparency can explain how the engine
reached a final score.

------------------------------------------------------------------------

# 31. IMPORTANT BREAKOUT DISTANCE DISTINCTION

`breakout_distance_atr` is **NOT** the breakout candle range.

It represents the distance of the close from the opening-range boundary:

### Bullish

``` text
(close - opening_high) / ATR14
```

### Bearish

``` text
(opening_low - close) / ATR14
```

The actual breakout candle range is:

``` text
High - Low
```

The engine now exposes this separately as:

``` text
breakout_candle_range
```

Do not mix these two values.

------------------------------------------------------------------------

# 32. HISTORICAL DIAGNOSTIC FORENSICS

A diagnostic CSV was generated:

``` text
v13_latest_session_full_diagnostic.csv
```

Population:

``` text
1000 rows
```

because each of 500 stocks was evaluated in two directions.

Columns include:

``` text
symbol
name
sector
direction
status
score
setup_type
signal_time
price
ema20
rsi14
rel_vol
vwap
atr14
true_velocity
breakout_distance_atr
entry
stop
target_1
target_2
risk
rr1
rr2
reasons
penalties
error
```

Historical diagnostic results included:

``` text
AFCONS       BEARISH  74
BLUESTARCO   BULLISH  74
FIVESTAR     BULLISH  74
JSWCEMENT    BEARISH  72
PAYTM        BULLISH  72
PWL          BULLISH  72
```

These are diagnostic observations from the historical snapshot, not
current trade recommendations.

------------------------------------------------------------------------

# 33. PRODUCTION ENGINE / DIAGNOSTIC ENGINE DISTINCTION

A temporary diagnostic engine was used during investigation to observe
latent scores below the production threshold.

That diagnostic copy was kept separate from production logic.

The intended final architecture is:

``` text
Production evaluator
        |
        +-- score >=72 --> production signal
        |
        +-- score <72 --> no active signal
```

and separately:

``` text
Diagnostic evaluator
        |
        +-- exact evaluation
        +-- can expose score <72
        +-- diagnostic only
```

The production threshold must remain intact.

------------------------------------------------------------------------

# 34. BELOW-72 FEATURE

The planned Below-72 feature answers:

> **Why did a technically evaluated setup fail to reach the V13
> activation threshold of 72?**

Below-72 signals should be exposed separately as:

``` text
BELOW_THRESHOLD
```

They must never become production signals.

Desired backend structure:

``` json
{
  "signals": [],
  "diagnostic_signals": []
}
```

The active `signals` collection remains production-only.

------------------------------------------------------------------------

# 35. SCORE CLASSIFICATION

The frontend/product classification requested for active signals is:

``` text
72–79  → WATCH
80–84  → STRONG
85+    → HIGH CONFIDENCE
```

Below threshold:

``` text
<72    → BELOW THRESHOLD
```

This is a **score-strength classification**, not a probability.

For example:

``` text
74 → WATCH
82 → STRONG
87 → HIGH CONFIDENCE
68 → BELOW THRESHOLD
```

Never display:

``` text
74%
82%
87%
```

as if these were win probabilities.

------------------------------------------------------------------------

# 36. SCORE ≠ TRADE STATUS

This distinction is critical.

A stock can have:

``` text
Score Classification: WATCH
```

while its actual engine state/action may be:

``` text
WATCH
```

or another legitimate engine state.

Likewise, a high score does not automatically mean:

``` text
TRADE-READY
```

Trade status comes from the engine's confirmation/execution logic.

Do not derive TRADE-READY solely from score.

------------------------------------------------------------------------

# 37. FRONTEND TARGET DESIGN

The dashboard should visually communicate:

``` text
NSE-PULSE V13
Market Regime: BEARISH
Last Update: ...
```

Summary cards:

``` text
Universe
Active Signals
WATCH
STRONG
HIGH CONFIDENCE
BELOW THRESHOLD
```

The diagnostic count must remain separate from active count.

------------------------------------------------------------------------

# 38. FRONTEND FILTERS

Desired filter set:

``` text
ALL
ACTIVE
WATCH
STRONG
HIGH CONFIDENCE
BELOW THRESHOLD
```

Definitions:

``` text
ALL:
active + diagnostic

ACTIVE:
score >=72

WATCH:
72–79

STRONG:
80–84

HIGH CONFIDENCE:
85+

BELOW THRESHOLD:
<72
```

Default can be `ALL` so transparency is immediately available.

------------------------------------------------------------------------

# 39. SIGNAL CARD

Each signal card should show, where available:

``` text
Symbol
Company name
Sector
Direction
V13 score
Score classification
Action/status
Setup type
LTP
Entry
Stop Loss
Target 1
Target 2
Risk
R:R
EMA20
RSI14
Relative Volume
VWAP
ATR14
True Velocity
```

No values should be fabricated.

------------------------------------------------------------------------

# 40. SCORE BREAKDOWN UI

Each card should have an expandable:

``` text
Score Breakdown
```

Example:

``` text
Trend Structure          +8
EMA Alignment           +10
VWAP Alignment          +10
RSI Momentum              +8
Volume                   +12
Opening Range            +18
Previous Day Level        +7
Candle Quality             0
Market/Sector Alignment    0
True Velocity              +6
Extension Chase             0
Trade/Risk Penalties      -5

Gross Score              +79
Adjustments                -5
Final Score                74
Classification           WATCH
```

For a below-threshold setup:

``` text
Final Score                68
Threshold                  72
Shortfall                   4
Classification     BELOW THRESHOLD
```

The shortfall is presentation-only.

------------------------------------------------------------------------

# 41. REASONS / PENALTIES

Show engine-provided reasons exactly.

Example:

``` text
Why it scored this way

✓ HH / HL structure
✓ Above EMA20
✓ Above VWAP
✓ RSI healthy
✓ High relative volume
✓ Confirmed OR breakout
✓ Above previous-day level
```

Penalties separately:

``` text
Penalties

• Weak/opposite true velocity
• Opening range unusually wide
```

Do not invent frontend-generated explanations.

------------------------------------------------------------------------

# 42. BELOW-72 CARD

Desired appearance:

``` text
XYZ
BULLISH

BELOW THRESHOLD

V13 SCORE
68 / 100

Threshold: 72
Shortfall: 4

Diagnostic only
Not an active V13 signal

▼ Score Breakdown
...
```

A below72 diagnostic card must not present itself as:

``` text
BUY
SELL
TRADE
TRADE READY
```

unless such action is independently generated by a valid production
signal.

------------------------------------------------------------------------

# 43. CURRENT BELOW-72 PATCH

A complete patch was prepared against the uploaded/current V13 source.

Patch archive:

``` text
v13_below72_diagnostic_patch.zip
```

Patch SHA256:

``` text
e48989a9214893673b3b93a0213c99c2d28e8b2e805de9e14957345f54d3ed43
```

The patch was designed to:

### Backend engine

Add:

``` text
allow_below_threshold=False
```

to the internal direction evaluator.

Add a diagnostic evaluator:

``` text
evaluate_v13_diagnostic(...)
```

Production behaviour remains gated at 72.

### Scanner

Add:

``` text
diagnostic_signals
```

and populate it only for below-threshold evaluations.

### Frontend types

Add:

``` text
BELOW_THRESHOLD
DIAGNOSTIC
V13ScoreBreakdown
diagnostic_signals
score_breakdown
```

### Adapter

Map diagnostic signals and score breakdown.

### Page

Default filter changed to `ALL`.

### SignalCard

Show diagnostic cards and expandable score breakdown.

------------------------------------------------------------------------

# 44. PATCH CURRENT STATUS

**Important: the Below-72 patch has been prepared but is not yet
confirmed applied to the Windows V13 project.**

Current Windows engine hash is:

``` text
00571B81C090F26605FF9EBBD7A070E6A01C446890131AE3E8BBA08B8E43988D
```

Current Windows scanner hash:

``` text
9E318577A70270819341E6AE986748DB0154A68651DAF5D4D2F254FA4B8FB79E
```

These match the expected pre-patch source state.

The patch is intentionally fail-closed: if source hashes differ, it
should stop rather than overwrite unknown changes.

------------------------------------------------------------------------

# 45. CURRENT API ISSUE

During the latest runtime test:

``` text
Uvicorn:                 PASS
Application startup:     PASS
/api/sectors:            HTTP 200
/api/v13/scan:           HTTP 503
```

The current source was still the pre-Below-72 patch version at that
point.

Therefore:

> The 503 must NOT be attributed to the Below-72 feature.

The exact `/api/v13/scan` error body/traceback still needs to be
captured before changing anything based on the 503.

No manual scoring or engine changes should be made to "fix" the 503.

------------------------------------------------------------------------

# 46. KNOWN ENGINE FORENSIC ISSUE --- FIVESTAR

A historical diagnostic row exists for FIVESTAR:

``` text
BULLISH
Score: 74
Setup: CONFIRMED_BREAKOUT_LONG
Signal time: 2026-09-11 15:15
```

But a direct production `_evaluate_direction()` call on the
corresponding historical slice returned `None`.

Therefore, there is an unresolved discrepancy between:

``` text
historical diagnostic evaluation
```

and:

``` text
current direct production evaluator
```

This must be investigated before assuming all diagnostic rows are
reproducible.

No engine rule should be changed until the discrepancy is isolated.

------------------------------------------------------------------------

# 47. KNOWN ENGINE FORENSIC ISSUE --- AFCONS

Direct `_evaluate_direction()` on AFCONS historical data returned score
74 for both bullish and bearish calls.

The bearish evaluation matched the expected diagnostic score breakdown.

The fact that both direction calls can produce the same setup is
suspicious and requires forensic inspection before any production
modification.

Do not infer the intended fix.

------------------------------------------------------------------------

# 48. SCANNER DETAIL

`v13_scanner.py` currently contains a duplicated identical assignment:

``` python
if market_context is None and context:
    market_context = context
```

It is currently functional but should be cleaned only as a controlled
infrastructure/code-quality change.

It is not currently established as the cause of the 503.

------------------------------------------------------------------------

# 49. MARKET REGIME TERMINOLOGY

The API field:

``` text
market_regime
```

represents the NIFTY direction/regime.

Example:

``` text
BEARISH
```

It should preferably be presented in the UI as:

``` text
Market Regime
```

rather than "Market Sentiment", because it is not a broad sentiment
model.

------------------------------------------------------------------------

# 50. DATA SAFETY PRINCIPLES

The project follows several hard rules:

### No lookahead

All calculations must use data available at or before the signal time.

### Point-in-time evaluation

Market context and historical setup logic must respect signal
timestamps.

### No future contamination

Future data must never be inserted into the frozen research population.

### No invented formula

If a metric cannot be recovered exactly, leave it unresolved rather than
approximate it.

### No fabricated live signals

A UI test must not manufacture a stock signal simply to demonstrate the
frontend.

### Fail closed

If population, hash, schema, timing, or research assumptions fail, stop
rather than silently continue.

------------------------------------------------------------------------

# 51. CURRENT V13 DATA POPULATION

The system is built around the NSE-500 universe.

Current live scanner validation has shown:

``` text
Universe: 500
```

A prior successful API scan returned:

``` text
Universe: 500
Watchlist: 6
Trade-ready: 0
Market regime: BEARISH
```

However, the latest runtime test returned 503, so the API must be
restored/validated before treating current live counts as authoritative.

------------------------------------------------------------------------

# 52. WHAT IS COMPLETE

## Research

-   V13.1 research specification: **complete/frozen**
-   H3 logic: **researched**
-   September H3 holdout: **complete**
-   August true OOS H3: **complete**
-   relative weakness investigation: **complete and rejected for
    deployment**
-   score-threshold investigation: **complete**
-   Score ≥77 candidate: **research-pass**
-   randomization tests: **complete**
-   threshold-selection permutation test: **complete**
-   OOS freeze manifest: **complete**
-   contamination guard: **complete**

## Market context

-   NIFTY point-in-time context: **implemented**
-   ATR%: **verified**
-   bar range%: **verified**
-   slope5: **verified**
-   slope12: **verified**
-   extension ATR: **verified**
-   range expansion: **NOT recovered exactly**

## Engine transparency

-   score_breakdown instrumentation: **implemented**
-   contribution attribution validation: **PASS**
-   breakout candle range field: **implemented**

## Frontend/backend architecture

-   V13 API architecture: **implemented**
-   V13 scanner: **implemented**
-   V13 frontend: **implemented**
-   market regime display: **integrated**
-   score transparency design: **prepared**
-   Below-72 patch: **prepared**

------------------------------------------------------------------------

# 53. WHAT IS NOT COMPLETE

## Immediate

1.  Resolve the `/api/v13/scan` HTTP 503.
2.  Apply the Below-72 patch safely.
3.  Validate real live diagnostic signals if the current market actually
    produces them.
4.  Validate score classifications:
    -   72--79 WATCH
    -   80--84 STRONG
    -   85+ HIGH CONFIDENCE
    -   \<72 BELOW THRESHOLD
5.  Validate score breakdown totals against engine scores.
6.  Validate active vs diagnostic separation.
7.  Resolve/understand FIVESTAR diagnostic-vs-production discrepancy.
8.  Investigate AFCONS direction-evaluation anomaly.

## Later

9.  Complete frontend/E2E validation.
10. Obtain genuinely unseen post-2026-09-10 forward data.
11. Evaluate frozen Score ≥77 on that unseen data.
12. Only after sufficient forward validation, consider paper trading.
13. Complete paper-trading/forward-validation phases.
14. Make production decision.

------------------------------------------------------------------------

# 54. WHAT MUST NOT HAPPEN YET

Do NOT:

-   promote Score ≥77 to a production hard filter,
-   modify the research weights because of live observations,
-   add relative weakness as a production rule,
-   invent range expansion,
-   alter the 72 threshold,
-   treat 77 as a guaranteed winning threshold,
-   call score a probability,
-   mix diagnostic signals into production signals,
-   start paper trading before the required validation gates,
-   touch the original project,
-   touch live deployment,
-   use historical rows as fake forward/OOS rows.

------------------------------------------------------------------------

# 55. SCORE 77 VS SCORE CLASSIFICATION --- IMPORTANT

These are two different concepts.

## Research threshold

``` text
Score ≥77
```

This is the **frozen research candidate** discovered through
historical/OOS analysis.

## Frontend score classification

``` text
72–79 → WATCH
80–84 → STRONG
85+   → HIGH CONFIDENCE
```

Therefore:

``` text
77
```

is:

``` text
WATCH
```

while also being part of the:

``` text
Score ≥77 research candidate
```

Those concepts must not be conflated.

A score of 85 is classified HIGH CONFIDENCE in the UI, but this does
**not** mean the research has proven that ≥85 is the best production
threshold.

------------------------------------------------------------------------

# 56. WHY SCORE ≥77 IS NOT YET A PRODUCTION FILTER

The historical evidence is strong enough to call it:

``` text
RESEARCH-PASS
```

but the project deliberately requires unseen forward validation.

The frozen cutoff is:

``` text
2026-09-10 22:15
```

Anything after that cutoff belongs to the forward-validation population.

At freeze time:

``` text
Forward rows: 0
```

Therefore the next important scientific step is not to rewrite the
engine.

It is to collect genuinely unseen data and evaluate the frozen rule
unchanged.

------------------------------------------------------------------------

# 57. FORWARD VALIDATION PRINCIPLE

When post-cutoff data becomes available:

1.  Do not retrain the threshold.
2.  Do not change Score ≥77.
3.  Do not alter scoring.
4.  Do not optimize after seeing results.
5.  Apply the frozen rule exactly.
6.  Record every qualifying forward event.
7.  Record misses/invalids according to the predefined methodology.
8.  Compare actual forward results with the frozen expectations.

Only after sufficient forward evidence should the project decide whether
the rule deserves paper trading.

------------------------------------------------------------------------

# 58. PAPER TRADING IS A LATER PHASE

Paper trading is not yet active.

The roadmap is:

``` text
Research
   ↓
Frozen candidate
   ↓
Unseen forward validation
   ↓
Paper trading
   ↓
Forward performance review
   ↓
Production decision
```

The project is currently around the **frontend/diagnostic validation
stage**, before genuine forward validation.

------------------------------------------------------------------------

# 59. LONG-TERM SUCCESS CRITERIA

The project succeeds only if it can demonstrate that:

1.  The engine is deterministic and auditable.
2.  No lookahead or future contamination exists.
3.  Score components can be explained.
4.  Failed setups can be diagnosed.
5.  Production signals are separated from diagnostics.
6.  The frozen research candidate survives unseen data.
7.  Paper-trading performance is acceptable.
8.  The system remains robust outside the exact historical sample used
    to discover it.

The final goal is therefore:

> **A transparent, point-in-time-safe, research-validated NSE intraday
> screening engine --- not merely a dashboard that generates
> attractive-looking signals.**

------------------------------------------------------------------------

# 60. ONE-PAGE CURRENT STATUS

``` text
PROJECT
NSE-PULSE V13

UNIVERSE
NSE-500

CURRENT PHASE
14–21 Frontend / Dashboard Integration & Validation

CURRENT MILESTONE
Score Transparency + Below-72 Diagnostic

PRODUCTION SCORE GATE
>=72

FRONTEND SCORE CLASSIFICATION
72–79  WATCH
80–84  STRONG
85+    HIGH CONFIDENCE

DIAGNOSTIC
<72    BELOW THRESHOLD

FROZEN RESEARCH CANDIDATE
Score >=77

HISTORICAL SCORE>=77
N=17
Total=+8.838R
Avg=+0.520R
WR=76.47%
PF=3.43
MaxDD=1R

OOS FREEZE
2026-09-10 22:15

FORWARD DATA
None yet

RANGE EXPANSION
Exact formula unresolved
Current value: None

CURRENT API
/ api / sectors → 200
/ api / v13 / scan → latest observed 503

BELOW-72 PATCH
Prepared
Not yet confirmed applied

NEXT PRIORITY
1. Diagnose 503
2. Apply patch
3. Validate score classification + diagnostic UI
4. Resolve engine forensic discrepancies
5. Complete E2E
6. Then wait for genuine post-cutoff forward data
7. Validate frozen Score>=77
8. Paper trade
9. Production decision
```

------------------------------------------------------------------------

# 61. GOLDEN RULES FOR FUTURE DEVELOPMENT

Before modifying V13, ask:

### Rule 1

**Does this change research logic?**

If yes → STOP unless explicitly approved.

### Rule 2

**Does this change scoring?**

If yes → STOP; this may invalidate the frozen research.

### Rule 3

**Does this use future data?**

If yes → STOP.

### Rule 4

**Is the exact formula known?**

If no → do not guess.

### Rule 5

**Is this production behaviour or diagnostic presentation?**

Keep them separate.

### Rule 6

**Can the result be independently reproduced?**

If no → investigate before changing logic.

### Rule 7

**Does a test require fake market data?**

Never fabricate a live trading signal.

------------------------------------------------------------------------

# 62. PROJECT PHILOSOPHY

NSE-PULSE V13 is being built with a deliberately conservative
philosophy:

> **Research first. Freeze the rule. Validate unseen. Explain every
> score. Fail closed. Only then consider deployment.**

A negative result is useful if it prevents an invalid rule from reaching
production.

The rejected relative-weakness filter is an example.

The unresolved range-expansion formula is another.

The Score ≥77 candidate is promising precisely because it was subjected
to additional randomization and threshold-selection tests --- but it is
still frozen until unseen forward evidence exists.

------------------------------------------------------------------------

# 63. FINAL PROJECT GOAL

The final system should look like this conceptually:

``` text
                 NSE-500 DATA
                       │
                       ▼
              Point-in-Time Engine
                       │
          ┌────────────┴────────────┐
          │                         │
          ▼                         ▼
   Active Evaluation          Diagnostic Evaluation
          │                         │
      score >=72                 score <72
          │                         │
          ▼                         ▼
   Production Signals        BELOW THRESHOLD
          │                         │
          └────────────┬────────────┘
                       ▼
                Explainable UI
                       │
             ┌─────────┼─────────┐
             ▼         ▼         ▼
           Score     Reasons   Risk Levels
        Breakdown   Penalties   Entry/SL/T1/T2
             │
             ▼
      Research / Validation
             │
             ▼
     Frozen OOS Candidate
        Score >=77
             │
             ▼
      Genuine Forward Data
             │
             ▼
        Paper Trading
             │
             ▼
      Production Decision
```

**The destination is not "make the scanner show more stocks."**

The destination is:

> **Build a scientifically controlled, transparent, explainable NSE
> intraday signal engine whose rules are frozen before unseen validation
> and whose production decisions can be audited from raw market data →
> technical conditions → score → classification → execution levels →
> outcome.**
