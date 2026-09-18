"""Config schema: one YAML file drives the whole experiment.

Every model sets extra="forbid" so a typo in the YAML is a startup error rather
than a silently different grid.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .ids import config_hash, validate_component

Polarity = Literal["pos", "neg"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RunCfg(Strict):
    name: str
    output_root: str = "runs"
    duplicates: int = Field(ge=1, description="D: duplicate runs per cell")
    shuffle_seed: int = 0

    @field_validator("name")
    @classmethod
    def _name_is_id_safe(cls, v: str) -> str:
        return validate_component(v, "run.name")


class QuestionsCfg(Strict):
    path: str = "data/questions.jsonl"
    polarities: list[Polarity] = ["pos", "neg"]
    limit: int | None = Field(default=None, ge=1)
    require_verified_negation: bool = True

    @field_validator("polarities")
    @classmethod
    def _unique_nonempty(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("questions.polarities must not be empty")
        if len(set(v)) != len(v):
            raise ValueError("questions.polarities contains duplicates")
        return v


class PerspectiveCfg(Strict):
    id: str
    label: str
    system_fragment: str

    @field_validator("id")
    @classmethod
    def _id_safe(cls, v: str) -> str:
        return validate_component(v, "perspective.id")


class AnswerPromptCfg(Strict):
    placement: Literal["system", "user_prefix"] = "system"
    system_template: str = "{perspective_fragment}"
    user_template: str
    max_tokens: int = Field(default=512, ge=1)
    temperature: float = Field(default=1.0, ge=0.0)

    @model_validator(mode="after")
    def _templates_have_slots(self) -> AnswerPromptCfg:
        if "{question_text}" not in self.user_template:
            raise ValueError("answer_prompt.user_template must contain {question_text}")
        if self.placement == "system" and "{perspective_fragment}" not in self.system_template:
            raise ValueError(
                "answer_prompt.system_template must contain {perspective_fragment} "
                'when placement is "system"'
            )
        return self


class PricingCfg(Strict):
    input_per_mtok: float = Field(ge=0.0)
    output_per_mtok: float = Field(ge=0.0)


class ProviderCfg(Strict):
    id: str
    adapter: str
    model: str
    api_key_env: str | None = None
    base_url: str | None = None
    max_concurrency: int = Field(default=4, ge=1)
    request_timeout_s: float = Field(default=120.0, gt=0)
    pricing: PricingCfg
    params: dict[str, Any] = Field(default_factory=dict)

    @field_validator("id")
    @classmethod
    def _id_safe(cls, v: str) -> str:
        return validate_component(v, "provider.id")

    @field_validator("model")
    @classmethod
    def _model_safe(cls, v: str) -> str:
        return validate_component(v, "provider.model")

    @model_validator(mode="after")
    def _reject_moving_alias(self) -> ProviderCfg:
        if self.model.endswith("-latest"):
            raise ValueError(
                f"provider {self.id!r} uses the moving alias {self.model!r}. Pin an "
                "explicit version: a run spanning weeks under an alias is not "
                "internally comparable."
            )
        return self


class JudgeCfg(Strict):
    provider: ProviderCfg
    run_index: int = Field(default=0, ge=0)
    rubric_version: str = "v1"
    prompt_path: str = "src/llmbench/prompts/judge.md"
    output_schema: str = "rubric_v1"
    max_repair_attempts: int = Field(default=1, ge=0)

    @field_validator("rubric_version")
    @classmethod
    def _rubric_safe(cls, v: str) -> str:
        return validate_component(v, "judge.rubric_version")


class BackoffCfg(Strict):
    base_s: float = Field(default=1.0, gt=0)
    multiplier: float = Field(default=2.0, ge=1.0)
    max_s: float = Field(default=60.0, gt=0)
    jitter: Literal["full", "equal", "none"] = "full"


class ReliabilityCfg(Strict):
    max_attempts: int = Field(default=6, ge=1)
    retry_on_http: list[int] = [408, 409, 429, 500, 502, 503, 504]
    retry_on_timeout: bool = True
    backoff: BackoffCfg = BackoffCfg()


class BudgetCfg(Strict):
    max_total_usd: float = Field(gt=0)
    per_phase_usd: dict[Literal["run", "judge"], float] = Field(default_factory=dict)
    estimate_headroom: float = Field(default=1.15, ge=1.0)
    abort_on_exceed: bool = True

    @model_validator(mode="after")
    def _phase_caps_fit(self) -> BudgetCfg:
        for phase, cap in self.per_phase_usd.items():
            if cap <= 0:
                raise ValueError(f"budget.per_phase_usd[{phase}] must be > 0")
            if cap > self.max_total_usd:
                raise ValueError(
                    f"budget.per_phase_usd[{phase}]={cap} exceeds "
                    f"max_total_usd={self.max_total_usd}"
                )
        return self


class ExperimentConfig(Strict):
    schema_version: int = 1
    run: RunCfg
    questions: QuestionsCfg = QuestionsCfg()
    perspectives: list[PerspectiveCfg]
    answer_prompt: AnswerPromptCfg
    providers: list[ProviderCfg]
    judge: JudgeCfg
    reliability: ReliabilityCfg = ReliabilityCfg()
    budget: BudgetCfg

    @field_validator("perspectives")
    @classmethod
    def _unique_perspectives(cls, v: list[PerspectiveCfg]) -> list[PerspectiveCfg]:
        if not v:
            raise ValueError("at least one perspective is required")
        ids = [p.id for p in v]
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        if dupes:
            raise ValueError(f"duplicate perspective ids: {dupes}")
        return v

    @field_validator("providers")
    @classmethod
    def _unique_providers(cls, v: list[ProviderCfg]) -> list[ProviderCfg]:
        if not v:
            raise ValueError("at least one provider is required")
        ids = [p.id for p in v]
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        if dupes:
            raise ValueError(f"duplicate provider ids: {dupes}")
        return v

    @model_validator(mode="after")
    def _judge_is_distinct(self) -> ExperimentConfig:
        if self.judge.provider.id in {p.id for p in self.providers}:
            raise ValueError(
                f"judge.provider.id={self.judge.provider.id!r} collides with an "
                "answering provider id. Give the judge its own id even when it is "
                "the same model, so concurrency and spend are tracked separately."
            )
        return self

    # -- derived -------------------------------------------------------------

    def semantic_dict(self) -> dict[str, Any]:
        """The parts of the config that change results, for config_hash.

        Operational knobs (concurrency, timeouts, retry policy, budget caps) are
        excluded: turning concurrency down must not make a resumed run look like
        a different experiment.
        """
        data = self.model_dump(mode="json")
        for provider in list(data["providers"]) + [data["judge"]["provider"]]:
            for operational in (
                "max_concurrency",
                "request_timeout_s",
                "base_url",
                "api_key_env",
            ):
                provider.pop(operational, None)
        data.pop("reliability", None)
        data.pop("budget", None)
        data["run"].pop("output_root", None)
        return data

    @property
    def config_hash(self) -> str:
        return config_hash(self.semantic_dict())

    def provider_by_id(self, provider_id: str) -> ProviderCfg:
        for p in self.providers:
            if p.id == provider_id:
                return p
        if self.judge.provider.id == provider_id:
            return self.judge.provider
        raise KeyError(f"unknown provider id: {provider_id}")

    def perspective_by_id(self, perspective_id: str) -> PerspectiveCfg:
        for p in self.perspectives:
            if p.id == perspective_id:
                return p
        raise KeyError(f"unknown perspective id: {perspective_id}")

    def cells_per_question(self) -> int:
        return (
            len(self.questions.polarities)
            * len(self.perspectives)
            * len(self.providers)
            * self.run.duplicates
        )

    def run_dir(self, root: Path | str | None = None) -> Path:
        base = Path(root) if root is not None else Path(self.run.output_root)
        return base / self.run.name


def load_config(path: str | Path) -> ExperimentConfig:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path} did not parse to a mapping")
    return ExperimentConfig.model_validate(raw)
