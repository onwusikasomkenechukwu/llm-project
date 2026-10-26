
## vs baseline: total

| term | strict | 95% CI | q | robust CI | robust q | lenient |
|---|---|---|---|---|---|---|
| group=Black man | -0.12 | -0.18 to -0.06 | 0.000 | -0.18 to -0.06 | 0.000 | -0.14 |
| group=Black woman | -0.15 | -0.21 to -0.09 | 0.000 | -0.20 to -0.09 | 0.000 | -0.17 |
| group=White man | -0.12 | -0.18 to -0.06 | 0.000 | -0.18 to -0.07 | 0.000 | -0.15 |
| group=White woman | -0.16 | -0.22 to -0.10 | 0.000 | -0.22 to -0.11 | 0.000 | -0.19 |
| group=did not finish high school | -0.43 | -0.49 to -0.36 | 0.000 | -0.50 to -0.36 | 0.000 | -0.45 |
| group=doctorate | +0.04 | -0.02 to +0.11 | 0.163 | -0.02 to +0.10 | 0.151 | +0.02 |
| group=irrelevant | -0.29 | -0.36 to -0.23 | 0.000 | -0.36 to -0.23 | 0.000 | -0.31 |

## race-gender: total

| term | strict | 95% CI | q | robust CI | robust q | lenient |
|---|---|---|---|---|---|---|
| cue_type=label | +0.10 | +0.09 to +0.12 | 0.000 | +0.09 to +0.12 | 0.000 | +0.10 |
| cue_type=name | -0.01 | -0.02 to +0.01 | 0.455 | -0.02 to +0.01 | 0.439 | -0.00 |
| cue_type=profile | -0.10 | -0.11 to -0.08 | 0.000 | -0.12 to -0.08 | 0.000 | -0.10 |
| race | +0.01 | -0.01 to +0.03 | 0.484 | -0.01 to +0.03 | 0.439 | +0.01 |
| race:cue_type=label | +0.03 | +0.00 to +0.06 | 0.105 | +0.01 to +0.06 | 0.022 | +0.03 |
| race:cue_type=name | +0.01 | -0.02 to +0.04 | 0.756 | -0.02 to +0.03 | 0.770 | +0.01 |
| race:cue_type=profile | -0.04 | -0.07 to -0.01 | 0.040 | -0.06 to -0.01 | 0.004 | -0.04 |
| race:provider=gemma-4-31b-it | +0.01 | -0.04 to +0.05 | 0.808 | -0.02 to +0.04 | 0.662 | +0.00 |
| race:provider=gpt-oss-120b | +0.05 | +0.00 to +0.09 | 0.079 | +0.00 to +0.09 | 0.057 | +0.04 |
| race:provider=llama-4-scout-17b-16e-instruct-quantized.w4a16 | -0.02 | -0.07 to +0.02 | 0.468 | -0.06 to +0.02 | 0.439 | -0.02 |
| race:provider=olmo-3.1-32b-instruct | -0.04 | -0.08 to +0.00 | 0.153 | -0.08 to -0.00 | 0.057 | -0.04 |
| race:provider=qwen3.8-27b | +0.01 | -0.04 to +0.05 | 0.785 | -0.02 to +0.04 | 0.662 | +0.01 |
| gender | -0.04 | -0.06 to -0.01 | 0.006 | -0.05 to -0.02 | 0.000 | -0.03 |
| race:gender | +0.01 | -0.03 to +0.06 | 0.756 | -0.02 to +0.04 | 0.548 | +0.00 |
| channel | +0.04 | +0.02 to +0.07 | 0.001 | +0.01 to +0.07 | 0.022 | +0.05 |
| channel:cue_type=label | -0.07 | -0.10 to -0.03 | 0.000 | -0.09 to -0.04 | 0.000 | -0.07 |
| channel:cue_type=name | +0.01 | -0.03 to +0.04 | 0.785 | -0.02 to +0.03 | 0.812 | -0.00 |
| channel:cue_type=profile | +0.06 | +0.03 to +0.09 | 0.001 | +0.04 to +0.09 | 0.000 | +0.07 |
| race:channel | +0.03 | -0.01 to +0.08 | 0.265 | -0.00 to +0.07 | 0.137 | +0.04 |

## education: total

| term | strict | 95% CI | q | robust CI | robust q | lenient |
|---|---|---|---|---|---|---|
| cue_type=label | +0.06 | +0.04 to +0.08 | 0.000 | +0.04 to +0.08 | 0.000 | +0.06 |
| cue_type=profile | -0.06 | -0.08 to -0.04 | 0.000 | -0.08 to -0.04 | 0.000 | -0.06 |
| edu | -0.47 | -0.51 to -0.43 | 0.000 | -0.54 to -0.41 | 0.000 | -0.47 |
| edu:cue_type=label | -0.07 | -0.11 to -0.03 | 0.002 | -0.10 to -0.03 | 0.000 | -0.06 |
| edu:cue_type=profile | +0.07 | +0.03 to +0.11 | 0.002 | +0.03 to +0.10 | 0.000 | +0.06 |
| edu:provider=gemma-4-31b-it | -0.28 | -0.36 to -0.20 | 0.000 | -0.35 to -0.19 | 0.000 | -0.28 |
| edu:provider=gpt-oss-120b | +0.31 | +0.23 to +0.39 | 0.000 | +0.21 to +0.40 | 0.000 | +0.34 |
| edu:provider=llama-4-scout-17b-16e-instruct-quantized.w4a16 | +0.12 | +0.04 to +0.20 | 0.004 | +0.03 to +0.20 | 0.012 | +0.12 |
| edu:provider=olmo-3.1-32b-instruct | +0.00 | -0.07 to +0.08 | 0.906 | -0.07 to +0.09 | 0.801 | -0.01 |
| edu:provider=qwen3.8-27b | -0.15 | -0.23 to -0.07 | 0.000 | -0.24 to -0.07 | 0.000 | -0.17 |
| channel | +0.05 | +0.01 to +0.09 | 0.017 | +0.01 to +0.09 | 0.012 | +0.06 |
| channel:cue_type=label | -0.04 | -0.08 to -0.00 | 0.044 | -0.07 to -0.01 | 0.013 | -0.05 |
| channel:cue_type=profile | +0.04 | +0.00 to +0.08 | 0.044 | +0.01 to +0.07 | 0.013 | +0.05 |
| edu:channel | +0.29 | +0.21 to +0.37 | 0.000 | +0.20 to +0.36 | 0.000 | +0.28 |

## vs baseline: sourcing

| term | strict | 95% CI | q | robust CI | robust q | lenient |
|---|---|---|---|---|---|---|
| group=Black man | -0.09 | -0.11 to -0.06 | 0.000 | -0.11 to -0.06 | 0.000 | -0.09 |
| group=Black woman | -0.10 | -0.13 to -0.08 | 0.000 | -0.13 to -0.08 | 0.000 | -0.11 |
| group=White man | -0.07 | -0.10 to -0.05 | 0.000 | -0.10 to -0.05 | 0.000 | -0.08 |
| group=White woman | -0.10 | -0.13 to -0.08 | 0.000 | -0.13 to -0.08 | 0.000 | -0.11 |
| group=did not finish high school | -0.29 | -0.31 to -0.26 | 0.000 | -0.32 to -0.25 | 0.000 | -0.29 |
| group=doctorate | +0.08 | +0.05 to +0.11 | 0.000 | +0.05 to +0.11 | 0.000 | +0.07 |
| group=irrelevant | -0.17 | -0.20 to -0.14 | 0.000 | -0.20 to -0.14 | 0.000 | -0.18 |

## race-gender: sourcing

| term | strict | 95% CI | q | robust CI | robust q | lenient |
|---|---|---|---|---|---|---|
| cue_type=label | +0.05 | +0.04 to +0.05 | 0.000 | +0.04 to +0.05 | 0.000 | +0.05 |
| cue_type=name | +0.00 | -0.01 to +0.01 | 0.947 | -0.01 to +0.01 | 0.969 | +0.00 |
| cue_type=profile | -0.05 | -0.05 to -0.04 | 0.000 | -0.05 to -0.04 | 0.000 | -0.05 |
| race | -0.01 | -0.02 to +0.00 | 0.385 | -0.01 to +0.00 | 0.356 | -0.00 |
| race:cue_type=label | +0.01 | -0.00 to +0.03 | 0.099 | +0.00 to +0.03 | 0.033 | +0.01 |
| race:cue_type=name | +0.00 | -0.01 to +0.02 | 0.947 | -0.01 to +0.01 | 0.969 | +0.00 |
| race:cue_type=profile | -0.01 | -0.03 to -0.00 | 0.078 | -0.03 to -0.00 | 0.025 | -0.01 |
| race:provider=gemma-4-31b-it | +0.01 | -0.01 to +0.03 | 0.385 | -0.00 to +0.03 | 0.208 | +0.01 |
| race:provider=gpt-oss-120b | +0.03 | +0.01 to +0.05 | 0.021 | +0.01 to +0.04 | 0.009 | +0.03 |
| race:provider=llama-4-scout-17b-16e-instruct-quantized.w4a16 | -0.01 | -0.03 to +0.01 | 0.301 | -0.04 to +0.01 | 0.246 | -0.01 |
| race:provider=olmo-3.1-32b-instruct | -0.02 | -0.04 to -0.01 | 0.032 | -0.04 to -0.01 | 0.019 | -0.03 |
| race:provider=qwen3.8-27b | +0.00 | -0.02 to +0.02 | 0.947 | -0.01 to +0.02 | 0.929 | +0.00 |
| gender | -0.02 | -0.03 to -0.01 | 0.000 | -0.03 to -0.01 | 0.000 | -0.02 |
| race:gender | +0.01 | -0.01 to +0.03 | 0.363 | -0.00 to +0.03 | 0.202 | +0.01 |
| channel | +0.01 | +0.00 to +0.02 | 0.025 | -0.00 to +0.03 | 0.148 | +0.02 |
| channel:cue_type=label | -0.04 | -0.06 to -0.03 | 0.000 | -0.06 to -0.03 | 0.000 | -0.05 |
| channel:cue_type=name | +0.01 | -0.01 to +0.02 | 0.385 | -0.00 to +0.02 | 0.255 | +0.01 |
| channel:cue_type=profile | +0.04 | +0.02 to +0.05 | 0.000 | +0.02 to +0.05 | 0.000 | +0.04 |
| race:channel | +0.01 | -0.01 to +0.03 | 0.511 | -0.01 to +0.02 | 0.517 | +0.01 |

## education: sourcing

| term | strict | 95% CI | q | robust CI | robust q | lenient |
|---|---|---|---|---|---|---|
| cue_type=label | +0.04 | +0.03 to +0.05 | 0.000 | +0.03 to +0.05 | 0.000 | +0.04 |
| cue_type=profile | -0.04 | -0.05 to -0.03 | 0.000 | -0.05 to -0.03 | 0.000 | -0.04 |
| edu | -0.37 | -0.39 to -0.35 | 0.000 | -0.40 to -0.33 | 0.000 | -0.36 |
| edu:cue_type=label | -0.06 | -0.08 to -0.05 | 0.000 | -0.08 to -0.05 | 0.000 | -0.06 |
| edu:cue_type=profile | +0.06 | +0.05 to +0.08 | 0.000 | +0.05 to +0.08 | 0.000 | +0.06 |
| edu:provider=gemma-4-31b-it | -0.15 | -0.19 to -0.11 | 0.000 | -0.19 to -0.10 | 0.000 | -0.16 |
| edu:provider=gpt-oss-120b | +0.13 | +0.09 to +0.16 | 0.000 | +0.07 to +0.17 | 0.000 | +0.14 |
| edu:provider=llama-4-scout-17b-16e-instruct-quantized.w4a16 | +0.13 | +0.09 to +0.16 | 0.000 | +0.09 to +0.16 | 0.000 | +0.13 |
| edu:provider=olmo-3.1-32b-instruct | +0.03 | -0.01 to +0.06 | 0.125 | -0.02 to +0.08 | 0.203 | +0.02 |
| edu:provider=qwen3.8-27b | -0.13 | -0.17 to -0.10 | 0.000 | -0.17 to -0.09 | 0.000 | -0.13 |
| channel | -0.01 | -0.03 to +0.00 | 0.155 | -0.03 to +0.01 | 0.203 | -0.01 |
| channel:cue_type=label | -0.03 | -0.05 to -0.01 | 0.001 | -0.05 to -0.02 | 0.000 | -0.03 |
| channel:cue_type=profile | +0.03 | +0.01 to +0.05 | 0.001 | +0.02 to +0.05 | 0.000 | +0.03 |
| edu:channel | +0.23 | +0.19 to +0.26 | 0.000 | +0.19 to +0.26 | 0.000 | +0.23 |

strict  total        vs baseline   348129 grades  83924 answers  162 questions
strict  total        race-gender   238705 grades  57550 answers  162 questions
strict  total        education      79579 grades  19186 answers  162 questions
strict  sourcing     vs baseline   348129 grades  83924 answers  162 questions
strict  sourcing     race-gender   238705 grades  57550 answers  162 questions
strict  sourcing     education      79579 grades  19186 answers  162 questions
lenient total        vs baseline   379201 grades  85050 answers  162 questions
lenient total        race-gender   260016 grades  58320 answers  162 questions
lenient total        education      86634 grades  19440 answers  162 questions
lenient sourcing     vs baseline   379201 grades  85050 answers  162 questions
lenient sourcing     race-gender   260016 grades  58320 answers  162 questions
lenient sourcing     education      86634 grades  19440 answers  162 questions
