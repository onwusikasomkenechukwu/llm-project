# Cue run statistics (lenient premise rule)

379201 grades of 85050 answers, 162 questions, 5 judges.

## judge agreement

| judge_a | judge_b | answers | pearson | spearman | mean_difference | hard_fail_kappa |
|---|---|---|---|---|---|---|
| gemma-4-31b-it | gpt-oss-120b | 73164 | 0.623 | 0.654 | 0.503 | 0.126 |
| gemma-4-31b-it | llama-4-scout-17b-16e-instruct-quantized.w4a16 | 68076 | 0.400 | 0.505 | -0.947 | 0.005 |
| gemma-4-31b-it | olmo-3.1-32b-instruct | 69184 | 0.380 | 0.402 | 0.557 | 0.055 |
| gemma-4-31b-it | qwen3.8-27b | 83691 | 0.693 | 0.579 | 1.939 | 0.472 |
| gpt-oss-120b | llama-4-scout-17b-16e-instruct-quantized.w4a16 | 66251 | 0.610 | 0.634 | -1.427 | 0.026 |
| gpt-oss-120b | olmo-3.1-32b-instruct | 66290 | 0.569 | 0.547 | 0.062 | 0.072 |
| gpt-oss-120b | qwen3.8-27b | 72138 | 0.627 | 0.547 | 1.419 | 0.116 |
| llama-4-scout-17b-16e-instruct-quantized.w4a16 | olmo-3.1-32b-instruct | 67475 | 0.404 | 0.402 | 1.475 | 0.001 |
| llama-4-scout-17b-16e-instruct-quantized.w4a16 | qwen3.8-27b | 67098 | 0.317 | 0.285 | 2.877 | 0.005 |
| olmo-3.1-32b-instruct | qwen3.8-27b | 68184 | 0.471 | 0.471 | 1.372 | 0.045 |

## panel alpha

| measure | krippendorff_alpha |
|---|---|
| total | 0.436 |
| accuracy | 0.300 |
| completeness | 0.530 |
| objectivity | 0.263 |
| sourcing | 0.442 |

## criteria

| criterion | accuracy | completeness | objectivity | sourcing | total |
|---|---|---|---|---|---|
| accuracy | 1.000 | 0.438 | 0.639 | 0.268 | 0.628 |
| completeness | 0.438 | 1.000 | 0.423 | 0.383 | 0.785 |
| objectivity | 0.639 | 0.423 | 1.000 | 0.251 | 0.541 |
| sourcing | 0.268 | 0.383 | 0.251 | 1.000 | 0.782 |
| total | 0.628 | 0.785 | 0.541 | 0.782 | 1.000 |

## length

| by | level | grades | spearman_words_total | pearson_within_question |
|---|---|---|---|---|
| judge | all | 379201 | 0.208 | 0.121 |
| judge | gemma-4-31b-it | 85038 | 0.249 | 0.066 |
| judge | gpt-oss-120b | 73176 | 0.292 | 0.253 |
| judge | llama-4-scout-17b-16e-instruct-quantized.w4a16 | 68088 | 0.531 | 0.440 |
| judge | olmo-3.1-32b-instruct | 69196 | 0.120 | 0.122 |
| judge | qwen3.8-27b | 83703 | -0.017 | -0.081 |
| provider | gemma-4-31b-it | 76108 | 0.176 | 0.082 |
| provider | gpt-oss-120b | 74699 | 0.162 | 0.150 |
| provider | llama-4-scout-17b-16e-instruct-quantized.w4a16 | 75965 | 0.025 | 0.075 |
| provider | olmo-3.1-32b-instruct | 75555 | 0.176 | 0.160 |
| provider | qwen3.8-27b | 76874 | 0.166 | 0.093 |

## by group

| group | answers | score | score_minus_baseline | words | words_minus_baseline | addresses_asker | majority_hard_fail | hard_fail_ci_low | hard_fail_ci_high |
|---|---|---|---|---|---|---|---|---|---|
| did not finish high school | 9720 | 16.141 | -0.448 | 410.093 | -100.471 | 0.440 | 0.019 | 0.017 | 0.022 |
| irrelevant | 4860 | 16.274 | -0.316 | 397.785 | -112.779 | 0.362 | 0.023 | 0.019 | 0.027 |
| White woman | 14580 | 16.402 | -0.188 | 436.245 | -74.319 | 0.364 | 0.024 | 0.022 | 0.027 |
| Black woman | 14580 | 16.412 | -0.177 | 453.180 | -57.383 | 0.399 | 0.023 | 0.021 | 0.026 |
| White man | 14580 | 16.439 | -0.150 | 448.034 | -62.530 | 0.350 | 0.024 | 0.021 | 0.026 |
| Black man | 14580 | 16.445 | -0.144 | 454.667 | -55.896 | 0.391 | 0.023 | 0.021 | 0.025 |
| baseline | 2430 | 16.590 | 0.000 | 510.564 | 0.000 | 0.238 | 0.022 | 0.017 | 0.028 |
| doctorate | 9720 | 16.622 | 0.033 | 530.295 | 19.731 | 0.396 | 0.030 | 0.027 | 0.033 |

## model correlation

| model_a | model_b | questions | pearson | ci_low | ci_high | spearman |
|---|---|---|---|---|---|---|
| gemma-4-31b-it | gpt-oss-120b | 162 | 0.659 | 0.562 | 0.738 | 0.672 |
| gemma-4-31b-it | llama-4-scout-17b-16e-instruct-quantized.w4a16 | 162 | 0.711 | 0.626 | 0.780 | 0.657 |
| gemma-4-31b-it | olmo-3.1-32b-instruct | 162 | 0.743 | 0.664 | 0.805 | 0.766 |
| gemma-4-31b-it | qwen3.8-27b | 162 | 0.870 | 0.827 | 0.903 | 0.796 |
| gpt-oss-120b | llama-4-scout-17b-16e-instruct-quantized.w4a16 | 162 | 0.687 | 0.596 | 0.761 | 0.741 |
| gpt-oss-120b | olmo-3.1-32b-instruct | 162 | 0.788 | 0.722 | 0.840 | 0.704 |
| gpt-oss-120b | qwen3.8-27b | 162 | 0.694 | 0.604 | 0.766 | 0.722 |
| llama-4-scout-17b-16e-instruct-quantized.w4a16 | olmo-3.1-32b-instruct | 162 | 0.769 | 0.697 | 0.825 | 0.724 |
| llama-4-scout-17b-16e-instruct-quantized.w4a16 | qwen3.8-27b | 162 | 0.704 | 0.617 | 0.774 | 0.696 |
| olmo-3.1-32b-instruct | qwen3.8-27b | 162 | 0.764 | 0.691 | 0.821 | 0.804 |

## test retest

| run_a | run_b | question_model_pairs | pearson | ci_low | ci_high | mean_abs_difference |
|---|---|---|---|---|---|---|
| 0 | 1 | 810 | 0.834 | 0.812 | 0.854 | 0.867 |
| 0 | 2 | 810 | 0.820 | 0.797 | 0.842 | 0.895 |
| 1 | 2 | 810 | 0.805 | 0.779 | 0.828 | 0.947 |

## gap by question

| gap | questions | mean | sd | share_negative | min | max | corr_with_baseline_score | ci_low | ci_high |
|---|---|---|---|---|---|---|---|---|---|
| education | 162 | -0.481 | 0.408 | 0.901 | -1.548 | 1.135 | -0.125 | -0.274 | 0.030 |
| race | 162 | 0.008 | 0.131 | 0.481 | -0.315 | 0.524 | 0.009 | -0.145 | 0.163 |

## gap between models

| gap | model_a | model_b | questions | pearson | ci_low | ci_high |
|---|---|---|---|---|---|---|
| education | gemma-4-31b-it | gpt-oss-120b | 162 | 0.219 | 0.067 | 0.361 |
| education | gemma-4-31b-it | llama-4-scout-17b-16e-instruct-quantized.w4a16 | 162 | 0.169 | 0.015 | 0.315 |
| education | gemma-4-31b-it | olmo-3.1-32b-instruct | 162 | 0.150 | -0.004 | 0.298 |
| education | gemma-4-31b-it | qwen3.8-27b | 162 | 0.379 | 0.239 | 0.504 |
| education | gpt-oss-120b | llama-4-scout-17b-16e-instruct-quantized.w4a16 | 162 | 0.226 | 0.074 | 0.367 |
| education | gpt-oss-120b | olmo-3.1-32b-instruct | 162 | 0.232 | 0.080 | 0.372 |
| education | gpt-oss-120b | qwen3.8-27b | 162 | 0.250 | 0.099 | 0.389 |
| education | llama-4-scout-17b-16e-instruct-quantized.w4a16 | olmo-3.1-32b-instruct | 162 | 0.062 | -0.093 | 0.214 |
| education | llama-4-scout-17b-16e-instruct-quantized.w4a16 | qwen3.8-27b | 162 | 0.142 | -0.012 | 0.290 |
| education | olmo-3.1-32b-instruct | qwen3.8-27b | 162 | 0.230 | 0.079 | 0.371 |
| race | gemma-4-31b-it | gpt-oss-120b | 162 | 0.074 | -0.082 | 0.225 |
| race | gemma-4-31b-it | llama-4-scout-17b-16e-instruct-quantized.w4a16 | 162 | 0.132 | -0.023 | 0.280 |
| race | gemma-4-31b-it | olmo-3.1-32b-instruct | 162 | -0.005 | -0.159 | 0.150 |
| race | gemma-4-31b-it | qwen3.8-27b | 162 | 0.085 | -0.070 | 0.237 |
| race | gpt-oss-120b | llama-4-scout-17b-16e-instruct-quantized.w4a16 | 162 | 0.143 | -0.012 | 0.291 |
| race | gpt-oss-120b | olmo-3.1-32b-instruct | 162 | -0.069 | -0.221 | 0.086 |
| race | gpt-oss-120b | qwen3.8-27b | 162 | 0.089 | -0.066 | 0.240 |
| race | llama-4-scout-17b-16e-instruct-quantized.w4a16 | olmo-3.1-32b-instruct | 162 | 0.050 | -0.105 | 0.203 |
| race | llama-4-scout-17b-16e-instruct-quantized.w4a16 | qwen3.8-27b | 162 | 0.200 | 0.047 | 0.344 |
| race | olmo-3.1-32b-instruct | qwen3.8-27b | 162 | 0.005 | -0.150 | 0.159 |

