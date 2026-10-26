# Cue run statistics (strict premise rule)

348129 grades of 83924 answers, 162 questions, 5 judges.

## judge agreement

| judge_a | judge_b | answers | pearson | spearman | mean_difference | hard_fail_kappa |
|---|---|---|---|---|---|---|
| gemma-4-31b-it | gpt-oss-120b | 61714 | 0.690 | 0.696 | 0.385 | 0.171 |
| gemma-4-31b-it | llama-4-scout-17b-16e-instruct-quantized.w4a16 | 56724 | 0.430 | 0.554 | -0.833 | 0.004 |
| gemma-4-31b-it | olmo-3.1-32b-instruct | 57801 | 0.409 | 0.420 | 0.635 | 0.047 |
| gemma-4-31b-it | qwen3.8-27b | 68405 | 0.696 | 0.572 | 1.905 | 0.475 |
| gpt-oss-120b | llama-4-scout-17b-16e-instruct-quantized.w4a16 | 62890 | 0.571 | 0.610 | -1.261 | 0.028 |
| gpt-oss-120b | olmo-3.1-32b-instruct | 63251 | 0.535 | 0.515 | 0.131 | 0.078 |
| gpt-oss-120b | qwen3.8-27b | 59193 | 0.604 | 0.504 | 1.519 | 0.123 |
| llama-4-scout-17b-16e-instruct-quantized.w4a16 | olmo-3.1-32b-instruct | 64391 | 0.364 | 0.362 | 1.394 | 0.002 |
| llama-4-scout-17b-16e-instruct-quantized.w4a16 | qwen3.8-27b | 54317 | 0.256 | 0.235 | 2.800 | 0.002 |
| olmo-3.1-32b-instruct | qwen3.8-27b | 55394 | 0.441 | 0.437 | 1.329 | 0.030 |

## panel alpha

| measure | krippendorff_alpha |
|---|---|
| total | 0.424 |
| accuracy | 0.286 |
| completeness | 0.522 |
| objectivity | 0.291 |
| sourcing | 0.442 |

## criteria

| criterion | accuracy | completeness | objectivity | sourcing | total |
|---|---|---|---|---|---|
| accuracy | 1.000 | 0.409 | 0.638 | 0.236 | 0.601 |
| completeness | 0.409 | 1.000 | 0.406 | 0.357 | 0.773 |
| objectivity | 0.638 | 0.406 | 1.000 | 0.236 | 0.527 |
| sourcing | 0.236 | 0.357 | 0.236 | 1.000 | 0.779 |
| total | 0.601 | 0.773 | 0.527 | 0.779 | 1.000 |

## length

| by | level | grades | spearman_words_total | pearson_within_question |
|---|---|---|---|---|
| judge | all | 348129 | 0.210 | 0.148 |
| judge | gemma-4-31b-it | 73718 | 0.290 | 0.147 |
| judge | gpt-oss-120b | 70486 | 0.283 | 0.255 |
| judge | llama-4-scout-17b-16e-instruct-quantized.w4a16 | 65309 | 0.520 | 0.466 |
| judge | olmo-3.1-32b-instruct | 67591 | 0.113 | 0.116 |
| judge | qwen3.8-27b | 71025 | -0.057 | -0.073 |
| provider | gemma-4-31b-it | 67603 | 0.142 | 0.092 |
| provider | gpt-oss-120b | 70669 | 0.176 | 0.173 |
| provider | llama-4-scout-17b-16e-instruct-quantized.w4a16 | 69774 | -0.006 | 0.087 |
| provider | olmo-3.1-32b-instruct | 70463 | 0.197 | 0.165 |
| provider | qwen3.8-27b | 69620 | 0.118 | 0.094 |

## by group

| group | answers | score | score_minus_baseline | words | words_minus_baseline | addresses_asker | majority_hard_fail | hard_fail_ci_low | hard_fail_ci_high |
|---|---|---|---|---|---|---|---|---|---|
| did not finish high school | 9590 | 16.272 | -0.427 | 411.987 | -102.297 | 0.434 | 0.019 | 0.017 | 0.022 |
| irrelevant | 4799 | 16.405 | -0.295 | 399.361 | -114.922 | 0.355 | 0.022 | 0.018 | 0.026 |
| White woman | 14388 | 16.524 | -0.176 | 438.222 | -76.061 | 0.357 | 0.024 | 0.022 | 0.027 |
| Black woman | 14388 | 16.544 | -0.156 | 455.457 | -58.826 | 0.392 | 0.023 | 0.020 | 0.025 |
| White man | 14376 | 16.572 | -0.128 | 450.398 | -63.885 | 0.342 | 0.023 | 0.020 | 0.025 |
| Black man | 14398 | 16.575 | -0.125 | 456.658 | -57.625 | 0.385 | 0.022 | 0.020 | 0.025 |
| baseline | 2389 | 16.700 | 0.000 | 514.283 | 0.000 | 0.229 | 0.022 | 0.017 | 0.029 |
| doctorate | 9596 | 16.746 | 0.046 | 532.752 | 18.468 | 0.389 | 0.029 | 0.026 | 0.033 |

## model correlation

| model_a | model_b | questions | pearson | ci_low | ci_high | spearman |
|---|---|---|---|---|---|---|
| gemma-4-31b-it | gpt-oss-120b | 162 | 0.586 | 0.475 | 0.679 | 0.651 |
| gemma-4-31b-it | llama-4-scout-17b-16e-instruct-quantized.w4a16 | 162 | 0.663 | 0.567 | 0.741 | 0.634 |
| gemma-4-31b-it | olmo-3.1-32b-instruct | 162 | 0.690 | 0.600 | 0.763 | 0.730 |
| gemma-4-31b-it | qwen3.8-27b | 162 | 0.856 | 0.809 | 0.893 | 0.797 |
| gpt-oss-120b | llama-4-scout-17b-16e-instruct-quantized.w4a16 | 162 | 0.655 | 0.557 | 0.735 | 0.732 |
| gpt-oss-120b | olmo-3.1-32b-instruct | 162 | 0.756 | 0.682 | 0.815 | 0.693 |
| gpt-oss-120b | qwen3.8-27b | 162 | 0.625 | 0.521 | 0.711 | 0.702 |
| llama-4-scout-17b-16e-instruct-quantized.w4a16 | olmo-3.1-32b-instruct | 162 | 0.762 | 0.689 | 0.820 | 0.711 |
| llama-4-scout-17b-16e-instruct-quantized.w4a16 | qwen3.8-27b | 162 | 0.663 | 0.566 | 0.741 | 0.677 |
| olmo-3.1-32b-instruct | qwen3.8-27b | 162 | 0.709 | 0.623 | 0.778 | 0.769 |

## test retest

| run_a | run_b | question_model_pairs | pearson | ci_low | ci_high | mean_abs_difference |
|---|---|---|---|---|---|---|
| 0 | 1 | 791 | 0.804 | 0.778 | 0.828 | 0.896 |
| 0 | 2 | 791 | 0.784 | 0.755 | 0.809 | 0.918 |
| 1 | 2 | 792 | 0.774 | 0.744 | 0.800 | 0.966 |

## gap by question

| gap | questions | mean | sd | share_negative | min | max | corr_with_baseline_score | ci_low | ci_high |
|---|---|---|---|---|---|---|---|---|---|
| education | 162 | -0.477 | 0.413 | 0.907 | -1.571 | 1.135 | -0.138 | -0.286 | 0.017 |
| race | 162 | 0.014 | 0.141 | 0.469 | -0.315 | 0.524 | -0.089 | -0.240 | 0.066 |

## gap between models

| gap | model_a | model_b | questions | pearson | ci_low | ci_high |
|---|---|---|---|---|---|---|
| education | gemma-4-31b-it | gpt-oss-120b | 161 | 0.108 | -0.048 | 0.258 |
| education | gemma-4-31b-it | llama-4-scout-17b-16e-instruct-quantized.w4a16 | 161 | 0.023 | -0.132 | 0.177 |
| education | gemma-4-31b-it | olmo-3.1-32b-instruct | 161 | 0.152 | -0.003 | 0.299 |
| education | gemma-4-31b-it | qwen3.8-27b | 161 | 0.296 | 0.148 | 0.431 |
| education | gpt-oss-120b | llama-4-scout-17b-16e-instruct-quantized.w4a16 | 162 | 0.211 | 0.058 | 0.353 |
| education | gpt-oss-120b | olmo-3.1-32b-instruct | 162 | 0.189 | 0.035 | 0.333 |
| education | gpt-oss-120b | qwen3.8-27b | 162 | 0.237 | 0.086 | 0.377 |
| education | llama-4-scout-17b-16e-instruct-quantized.w4a16 | olmo-3.1-32b-instruct | 162 | 0.103 | -0.052 | 0.253 |
| education | llama-4-scout-17b-16e-instruct-quantized.w4a16 | qwen3.8-27b | 162 | 0.140 | -0.015 | 0.288 |
| education | olmo-3.1-32b-instruct | qwen3.8-27b | 162 | 0.217 | 0.065 | 0.359 |
| race | gemma-4-31b-it | gpt-oss-120b | 160 | 0.107 | -0.049 | 0.257 |
| race | gemma-4-31b-it | llama-4-scout-17b-16e-instruct-quantized.w4a16 | 160 | 0.059 | -0.097 | 0.212 |
| race | gemma-4-31b-it | olmo-3.1-32b-instruct | 160 | 0.057 | -0.099 | 0.211 |
| race | gemma-4-31b-it | qwen3.8-27b | 160 | -0.048 | -0.202 | 0.108 |
| race | gpt-oss-120b | llama-4-scout-17b-16e-instruct-quantized.w4a16 | 162 | 0.101 | -0.054 | 0.251 |
| race | gpt-oss-120b | olmo-3.1-32b-instruct | 162 | -0.126 | -0.275 | 0.028 |
| race | gpt-oss-120b | qwen3.8-27b | 162 | 0.079 | -0.076 | 0.231 |
| race | llama-4-scout-17b-16e-instruct-quantized.w4a16 | olmo-3.1-32b-instruct | 162 | 0.040 | -0.115 | 0.193 |
| race | llama-4-scout-17b-16e-instruct-quantized.w4a16 | qwen3.8-27b | 162 | 0.139 | -0.015 | 0.287 |
| race | olmo-3.1-32b-instruct | qwen3.8-27b | 162 | 0.099 | -0.056 | 0.250 |

