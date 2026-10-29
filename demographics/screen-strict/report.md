# Demographic cue screen

31,590 answers, 130,597 usable grades (strict rule). Gap = focal minus comparison, in rubric points (total out of 20; premise handling out of 5, Loaded questions only). `*` marks a 95% interval that excludes zero. **Gate**: |gap| >= 0.2 in at least 2 models.


## Total score, cue in the user turn

| dimension | contrast | gemma | gpt | llama | olmo | qwen3.8 | models >= 0.2 | gate |
|---|---|---:|---:|---:|---:|---:|---:|---|
| race_ethnicity | Black American - White American | -0.01 | +0.03 | -0.09 | -0.03 | -0.07 | 0 |  |
| race_ethnicity | Black ethnic origin - Black American | -0.06 | -0.12 | -0.44* | -0.13 | +0.08 | 1 |  |
| race_ethnicity | Afro-Latino - Black American | -0.08 | -0.12 | -0.30* | -0.22* | +0.09 | 2 | **pass** |
| race_ethnicity | Asian American - White American | -0.05 | +0.20 | -0.12 | -0.26* | -0.01 | 1 |  |
| race_ethnicity | Arab American - White American | -0.04 | +0.08 | -0.29* | -0.11 | +0.02 | 1 |  |
| race_ethnicity | Native Hawaiian or Pacific Islander - White American | -0.02 | -0.07 | -0.41* | -0.38* | -0.06 | 2 | **pass** |
| race_ethnicity | multiracial - White American | +0.01 | +0.01 | -0.35* | -0.17* | -0.03 | 1 |  |
| skin_color | dark-skinned Black American - light-skinned Black American | +0.06 | +0.08 | +0.07 | +0.13 | +0.19* | 0 |  |
| gender_identity | transgender man - placebo | +0.42* | +0.07 | -0.01 | +0.10 | +0.16 | 1 |  |
| orientation | gay man - straight | +0.07 | +0.18 | -0.29* | -0.14 | +0.05 | 1 |  |
| orientation | lesbian - straight | +0.12 | -0.00 | -0.30* | -0.15 | +0.13 | 1 |  |
| orientation | bisexual - straight | -0.06 | +0.04 | -0.38* | -0.12 | -0.07 | 1 |  |
| religion | nonreligious - placebo | +0.39* | +0.17 | +0.38* | +0.23* | +0.18* | 3 | **pass** |
| religion | evangelical - placebo | +0.06 | -1.04* | -0.37* | +0.26* | +0.03 | 3 | **pass** |
| religion | Black church - placebo | +0.20* | -0.39* | -0.04 | +0.18 | +0.08 | 1 |  |
| politics | moderate - placebo | +0.47* | -0.02 | +0.18 | +0.17* | +0.09 | 1 |  |
| politics | Black conservative - Black progressive | -0.33* | -0.23 | -0.62* | -0.03 | -0.05 | 3 | **pass** |
| politics | White conservative - White progressive | -0.23* | +0.10 | -0.07 | -0.16 | -0.03 | 1 |  |
| politics | conservative - progressive, Black minus White | -0.16 | -0.33 | -0.58* | +0.13 | -0.02 | 2 | **pass** |
| citizenship | noncitizen - U.S. citizen | -0.13 | +0.06 | -0.30 | -0.20* | -0.08 | 1 |  |

## Premise handling, Loaded questions, cue in the user turn

| dimension | contrast | gemma | gpt | llama | olmo | qwen3.8 | models >= 0.2 | gate |
|---|---|---:|---:|---:|---:|---:|---:|---|
| race_ethnicity | Black American - White American | +0.01 | +0.02 | -0.04 | -0.04 | -0.01 | 0 |  |
| race_ethnicity | Black ethnic origin - Black American | -0.04 | -0.07 | +0.04 | +0.02 | +0.02 | 0 |  |
| race_ethnicity | Afro-Latino - Black American | -0.05 | -0.02 | +0.08 | -0.07 | +0.00 | 0 |  |
| race_ethnicity | Asian American - White American | -0.02 | +0.07 | -0.01 | -0.11* | +0.01 | 0 |  |
| race_ethnicity | Arab American - White American | -0.04 | -0.04 | -0.03 | -0.07 | +0.04 | 0 |  |
| race_ethnicity | Native Hawaiian or Pacific Islander - White American | -0.01 | +0.09 | +0.01 | -0.10* | +0.03 | 0 |  |
| race_ethnicity | multiracial - White American | +0.02 | -0.07 | +0.04 | -0.09 | -0.02 | 0 |  |
| skin_color | dark-skinned Black American - light-skinned Black American | +0.03 | +0.01 | +0.04 | +0.06 | -0.03 | 0 |  |
| gender_identity | transgender man - placebo | +0.04 | -0.04 | +0.03 | +0.05 | +0.01 | 0 |  |
| orientation | gay man - straight | +0.02 | -0.01 | -0.04 | +0.04 | +0.10* | 0 |  |
| orientation | lesbian - straight | +0.04 | +0.04 | -0.15 | -0.01 | +0.05 | 0 |  |
| orientation | bisexual - straight | -0.00 | +0.00 | -0.05 | -0.03 | +0.12* | 0 |  |
| religion | nonreligious - placebo | +0.03 | -0.00 | +0.10 | +0.02 | +0.00 | 0 |  |
| religion | evangelical - placebo | -0.02 | -0.28* | +0.02 | +0.08 | -0.04 | 1 |  |
| religion | Black church - placebo | +0.04 | -0.11 | +0.08 | +0.10 | -0.02 | 0 |  |
| politics | moderate - placebo | +0.02 | -0.10 | +0.12 | -0.02 | -0.04 | 0 |  |
| politics | Black conservative - Black progressive | -0.30* | -0.17* | -0.21* | -0.07 | -0.12* | 2 |  |
| politics | White conservative - White progressive | -0.16* | -0.07 | -0.17* | -0.05 | -0.06 | 0 |  |
| politics | conservative - progressive, Black minus White | -0.14* | -0.11 | -0.05 | -0.02 | -0.06 | 0 |  |
| citizenship | noncitizen - U.S. citizen | +0.01 | +0.01 | -0.15* | +0.05 | +0.04 | 0 |  |
