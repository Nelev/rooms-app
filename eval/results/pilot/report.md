# Eval report

Variants `baseline`, `no_critic`, `full`; rebuilt from runs.csv; judge cost $0.0989.
7 runs, 1 failed; total model cost $0.1743. Means over each variant's runs:

| variant | runs | failed | latency_s | cost_usd | input_tokens | output_tokens | out_of_bounds | overlap_volume | clearance_pass_rate | blocked_openings | item_count | budget_fit | must_have_coverage | furniture_eur | judge_cost_usd | judge_functionality | judge_layout | judge_color_scheme | judge_atmosphere | judge_realism | feature_precision | feature_recall | position_error_cm |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| baseline | 3 | 0 | 16.81 | 0.02497 | 6756 | 815 | 0 | 0 | 0.9667 | 0 | 5.667 | 1 | 1 | 867.7 | 0.01634 | 3.889 | 4.111 | 5.667 | 3.667 | 1.889 |  |  |  |
| no_critic | 3 | 0 | 56.28 | 0.03312 | 9718 | 3095 | 0 | 2.611e-18 | 0.9167 | 0 | 4.667 | 1 | 1 | 789.3 | 0.01664 | 3.667 | 4.444 | 5.333 | 3.333 | 2 | 1 | 0 |  |
| full | 1 | 1 |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |
| **all** | 7 | 1 | 36.54 | 0.02905 | 8237 | 1955 | 0 | 1.306e-18 | 0.9417 | 0 | 5.167 | 1 | 1 | 828.5 | 0.01649 | 3.778 | 4.278 | 5.5 | 3.5 | 1.944 | 1 | 0 |  |
