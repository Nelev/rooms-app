# Eval report

Variants `baseline`, `no_critic`, `full`, `analyst_mode`; rebuilt from runs.csv; judge cost $0.1981.
12 runs, 0 failed; total model cost $0.3834. Means over each variant's runs:

| variant | runs | failed | latency_s | cost_usd | input_tokens | output_tokens | out_of_bounds | overlap_volume | clearance_pass_rate | blocked_openings | item_count | budget_fit | must_have_coverage | furniture_eur | judge_cost_usd | judge_functionality | judge_layout | judge_color_scheme | judge_atmosphere | judge_realism | feature_precision | feature_recall | position_error_cm |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| baseline | 3 | 0 | 16.81 | 0.02497 | 6756 | 815 | 0 | 0 | 0.9667 | 0 | 5.667 | 1 | 1 | 867.7 | 0.01634 | 3.889 | 4.111 | 5.667 | 3.667 | 1.889 |  |  |  |
| no_critic | 3 | 0 | 56.28 | 0.03312 | 9718 | 3095 | 0 | 2.611e-18 | 0.9167 | 0 | 4.667 | 1 | 1 | 789.3 | 0.01664 | 3.667 | 4.444 | 5.333 | 3.333 | 2 | 1 | 0 |  |
| full | 3 | 0 | 57.34 | 0.04247 | 1.376e+04 | 3097 | 0 | 1.48e-17 | 0.9167 | 0 | 5 | 1 | 1 | 769.7 | 0.01709 | 4 | 4.667 | 5.889 | 3.556 | 2 | 1 | 0 |  |
| analyst_mode | 3 | 0 | 46.93 | 0.02723 | 8868 | 2744 | 0 | 0 | 1 | 0 | 5.333 | 1 | 1 | 748.7 | 0.01597 | 3.667 | 4.444 | 5.778 | 3.444 | 2 | 1 | 0 |  |
| **all** | 12 | 0 | 44.34 | 0.03195 | 9776 | 2438 | 0 | 4.354e-18 | 0.95 | 0 | 5.167 | 1 | 1 | 793.8 | 0.01651 | 3.806 | 4.417 | 5.667 | 3.5 | 1.972 | 1 | 0 |  |
