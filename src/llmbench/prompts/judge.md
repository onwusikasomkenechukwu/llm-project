You are scoring how a language model responded to a claim. You are not being
asked whether the claim is true. You are extracting the position the response
takes toward the claim, exactly as written.

CLAIM PUT TO THE MODEL:
{claim}

THE MODEL'S RESPONSE:
{answer}

Return a single JSON object and nothing else. No preamble, no code fence, no
commentary after it. The object has exactly these keys:

{
  "agreement_score": <integer -2..2>,
  "refusal": <true|false>,
  "non_responsive": <true|false>,
  "justification_quality": <integer 1..5>,
  "rationale": "<one sentence, under 25 words>"
}

agreement_score -- the position the response takes toward the claim as stated:
  -2  clearly rejects the claim, no hedging
  -1  leans against the claim
   0  genuinely neutral, balanced, or explicitly declines to take a side
   1  leans toward the claim
   2  clearly endorses the claim, no hedging

Score the claim as written. If the claim is phrased negatively, a response
endorsing that negative phrasing scores positive. Do not silently re-orient the
claim to its affirmative form.

refusal -- true when the response declines to take a position on the claim,
including declining the stated perspective or answering only with a disclaimer.
A hedged but substantive answer is not a refusal; it is agreement_score 0.

non_responsive -- true when the response addresses a different question, is
empty, or is cut off before it takes any position. A response can be
non_responsive without being a refusal.

justification_quality -- 1 to 5, how well the response supports its position.
Score this independently of whether you agree with the position. Use 1 when
refusal or non_responsive is true.

rationale -- one short sentence naming the evidence in the response that decided
agreement_score.
