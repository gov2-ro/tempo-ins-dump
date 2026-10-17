"""Argument and result models of the shared analytical tools (`tempo-tools/2`).

Arguments are strict: no type coercion (a boolean is not an integer, a number
is not a string), unknown keys are rejected, and every bound below is checked
before any metadata or database work. Ask and the public MCP publish
`model_json_schema()` of these models; the service validates again regardless
of what a transport already checked.

Result models describe the minimum shape adapters may rely on. They allow
additional fields: a tool may add compatible facts, never drop these.
"""
from __future__ import annotations

from typing import Annotated, Any, Literal, Union

from pydantic import (BaseModel, ConfigDict, Field, StrictBool, StrictFloat, StrictInt,
                      StrictStr, field_validator, model_serializer, model_validator)

MAX_FILTER_COLUMNS = 16
MAX_VALUES_PER_COLUMN = 100
MAX_FILTER_VALUES = 1000
MAX_GROUP_COLUMNS = 8
MAX_AREAS = 60
VALUE_COLUMN = "OBS_VALUE"

Lang = Annotated[Literal["ro", "en"], Field(
    description="Language of the messages, warnings and labels (ro or en): the user's language. "
                "Codes, ids, filters and values do not change with it.")]
DatasetCode = Annotated[StrictStr, Field(
    min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_]+$",
    description="Exact dataset code from discover_indicators or describe_dataset, "
                "e.g. POP107D_grupe_judet")]
Column = Annotated[StrictStr, Field(
    min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_]+$",
    description="Dimension column name as describe_dataset lists it, e.g. REF_AREA, TIME_PERIOD")]
Year = Annotated[StrictStr, Field(pattern=r"^\d{4}$", description="Exact four-digit year, e.g. \"2020\"")]
FilterValue = Union[Annotated[StrictStr, Field(max_length=500)], StrictInt,
                    Annotated[StrictFloat, Field(allow_inf_nan=False)]]
Filters = Annotated[dict[Column, list[FilterValue]], Field(
    description="{column: [exact values]}. Values must be exact data values (find_dimension_values). "
                "An empty list imposes no constraint on that column.")]


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


def _check_filters(filters: dict) -> dict:
    if len(filters) > MAX_FILTER_COLUMNS:
        raise ValueError(f"at most {MAX_FILTER_COLUMNS} filter columns")
    total = 0
    for col, vals in filters.items():
        if col == VALUE_COLUMN:
            raise ValueError(f"{VALUE_COLUMN} is the observation value, not a dimension")
        if len(vals) > MAX_VALUES_PER_COLUMN:
            raise ValueError(f"at most {MAX_VALUES_PER_COLUMN} values for {col}")
        total += len(vals)
    if total > MAX_FILTER_VALUES:
        raise ValueError(f"at most {MAX_FILTER_VALUES} filter values in total")
    return filters


def _check_columns(cols: list, what: str) -> list:
    if len(set(cols)) != len(cols):
        raise ValueError(f"{what} must not repeat a column")
    if VALUE_COLUMN in cols:
        raise ValueError(f"{VALUE_COLUMN} is the observation value, not a dimension")
    return cols


# ------------------------------------------------------------------ arguments

class DiscoverIndicatorsArgs(_Args):
    query: StrictStr = Field(min_length=1, max_length=200,
                             description="The question or indicator words, Romanian or English")
    lang: Lang = "ro"
    limit: StrictInt = Field(5, ge=1, le=10, description="Concept and family cards to return")

    @field_validator("query")
    @classmethod
    def v_not_blank(cls, v):
        if not v.strip():
            raise ValueError("query must not be blank")
        return v


class DescribeDatasetArgs(_Args):
    dataset: DatasetCode
    lang: Lang = "ro"


class FindDimensionValuesArgs(_Args):
    dataset: DatasetCode
    column: Column
    query: StrictStr = Field("", max_length=200,
                             description="Accent- and case-insensitive substring; empty lists all")
    limit: StrictInt = Field(20, ge=1, le=100)
    offset: StrictInt = Field(0, ge=0, le=1_000_000)
    lang: Lang = "ro"


class QueryDataArgs(_Args):
    dataset: DatasetCode
    filters: Filters = Field(default_factory=dict)
    group_by: list[Column] = Field(default_factory=list, max_length=MAX_GROUP_COLUMNS,
                                   description="Columns to keep; every other dimension is collapsed "
                                               "only if the aggregation policy allows it. Empty = raw rows.")
    limit: StrictInt = Field(100, ge=1, le=200, description="Rows to return")
    approximate: StrictBool = Field(False, description="True only when the user accepted a labelled "
                                                       "unweighted approximation")
    lang: Lang = "ro"

    @field_validator("filters")
    @classmethod
    def v_filters(cls, v):
        return _check_filters(v)

    @field_validator("group_by")
    @classmethod
    def v_group_by(cls, v):
        return _check_columns(v, "group_by")


class Interval(_Args):
    from_: Year = Field(alias="from")
    to: Year

    @model_validator(mode="after")
    def v_ordered(self):
        if not self.from_ < self.to:
            raise ValueError("interval 'from' must be an earlier year than 'to'")
        return self


class _PeriodChanges(_Args):
    dataset: DatasetCode
    entity_columns: list[Column] = Field(min_length=1, max_length=MAX_GROUP_COLUMNS,
                                         description="Full entity key, e.g. [REF_AREA, REF_AREA_2] "
                                                     "for localities")
    intervals: list[Interval] = Field(min_length=1, max_length=4)
    filters: Filters = Field(default_factory=dict)
    metric: Literal["absolute", "percent"] = "absolute"
    order: Literal["asc", "desc"] = "asc"
    top_k: StrictInt = Field(20, ge=1, le=100, description="Rows per interval to return; ranking "
                                                          "always uses every eligible entity")
    entity_class: Literal["all", "cities"] = Field(
        "all", description="all = every entity of the selection. cities = only municipalities and "
                           "towns in the referenced catalogue (INS GOS102A SIRUTA keys; needs "
                           "REF_AREA_2 in entity_columns). Applied before eligibility, ranks and "
                           "top_k. The catalogue does not prove historical city status or unchanged "
                           "boundaries.")

    @model_serializer(mode="wrap")
    def _omit_default_class(self, handler):
        # The normalized request (citation, link, replay, bundle) of a caller that never chose a
        # class stays exactly what it was before the field existed; "cities" is always explicit.
        out = handler(self)
        if out.get("entity_class") == "all":
            out.pop("entity_class")
        return out

    @model_validator(mode="after")
    def v_class_needs_locality_key(self):
        if self.entity_class == "cities" and "REF_AREA_2" not in self.entity_columns:
            raise ValueError("entity_class 'cities' needs REF_AREA_2 among entity_columns "
                             "(SIRUTA locality keys)")
        return self

    @field_validator("filters")
    @classmethod
    def v_filters(cls, v):
        _check_filters(v)
        if "TIME_PERIOD" in v:
            raise ValueError("periods come from intervals; do not filter TIME_PERIOD")
        return v

    @field_validator("entity_columns")
    @classmethod
    def v_entities(cls, v):
        _check_columns(v, "entity_columns")
        if "TIME_PERIOD" in v:
            raise ValueError("TIME_PERIOD is the period, not an entity column")
        return v

    @field_validator("intervals")
    @classmethod
    def v_distinct(cls, v):
        keys = [(i.from_, i.to) for i in v]
        if len(set(keys)) != len(keys):
            raise ValueError("intervals must be distinct")
        return v


class ComparePeriodsArgs(_PeriodChanges):
    lang: Lang = "ro"


class RankEntitiesArgs(_Args):
    dataset: DatasetCode
    entity_columns: list[Column] = Field(min_length=1, max_length=MAX_GROUP_COLUMNS)
    year: Year | None = Field(None, description="Exact annual year; null = latest actual year")
    filters: Filters = Field(default_factory=dict)
    entity_class: Literal["all", "cities"] = "all"
    order: Literal["asc", "desc"] = "desc"
    top_k: StrictInt = Field(30, ge=1, le=100)
    lang: Lang = "ro"

    @field_validator("filters")
    @classmethod
    def v_filters(cls, v):
        _check_filters(v)
        if "TIME_PERIOD" in v:
            raise ValueError("use year instead of filtering TIME_PERIOD")
        return v

    @field_validator("entity_columns")
    @classmethod
    def v_entities(cls, v):
        return _check_columns(v, "entity_columns")


class RunRecipeArgs(_Args):
    recipe: StrictStr = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9_]+$",
                              description="Recipe id from discover_indicators")
    year: Year | None = Field(None, description="Exact year; null = latest year every source has")
    areas: list[Annotated[StrictStr, Field(min_length=1, max_length=100)]] | None = Field(
        None, max_length=MAX_AREAS, description="Exact area names; null = every area")
    lang: Lang = "ro"


class DatasetSelection(_Args):
    kind: Literal["dataset"]
    dataset: DatasetCode
    filters: Filters = Field(default_factory=dict)
    group_by: list[Column] = Field(default_factory=list, max_length=MAX_GROUP_COLUMNS)
    approximate: StrictBool = False

    @field_validator("filters")
    @classmethod
    def v_filters(cls, v):
        return _check_filters(v)

    @field_validator("group_by")
    @classmethod
    def v_group_by(cls, v):
        return _check_columns(v, "group_by")


class RecipeSelection(_Args):
    kind: Literal["recipe"]
    recipe: StrictStr = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9_]+$")
    year: Year = Field(description="The resolved year from run_recipe (never null in a citation)")
    areas: list[Annotated[StrictStr, Field(min_length=1, max_length=100)]] | None = Field(
        None, max_length=MAX_AREAS)


class PeriodChangesSelection(_PeriodChanges):
    kind: Literal["period_changes"]


class EntityRankingSelection(RankEntitiesArgs):
    kind: Literal["entity_ranking"]
    year: Year


Selection = Annotated[Union[DatasetSelection, RecipeSelection, PeriodChangesSelection, EntityRankingSelection],
                      Field(discriminator="kind")]


class GetEvidenceLinksArgs(_Args):
    selection: Selection
    generation_id: StrictStr = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._-]+$",
                                     description="provenance.generation.id of the result being cited")
    lang: Lang = "ro"


# ------------------------------------------------------------------ results

class _Open(BaseModel):
    model_config = ConfigDict(extra="allow")


class _Closed(BaseModel):
    model_config = ConfigDict(extra="forbid")


Status = Literal["ok", "partial", "needs_clarification", "unavailable", "error"]


class WarningItem(_Closed):
    code: str
    message: str
    subject: str | None = None


class RecoveryItem(_Closed):
    kind: Literal["clarify", "tool_call", "narrow", "retry"]
    message: str
    tool: str | None
    arguments: dict[str, Any] | None


class GenerationInfo(_Open):
    id: str | None
    status: Literal["present", "stale", "missing", "unreadable"]


class SourceInfo(_Open):
    dataset: str
    metric: str | None
    unit: str | None
    definition: str | None
    source_updated: str | None
    url: str | None
    notes: list[dict[str, Any]]


class ScopeInfo(_Open):
    description: str
    domain_complete: bool | None
    limitations: list[dict[str, Any]]


class Provenance(_Open):
    generation: GenerationInfo
    sources: list[SourceInfo]
    selection: dict[str, Any] | None
    effective_selection: dict[str, Any] | None
    aggregation: dict[str, Any]
    quality: dict[str, Any]
    scope: ScopeInfo


class Limits(_Closed):
    returned_rows: int = Field(ge=0)
    total_rows: int | None
    preview_truncated: bool
    source_complete: bool | None
    time_windowed: bool
    partial_period_dropped: str | None


class Envelope(_Closed):
    contract: Literal["tempo-tools/2"]
    tool: str
    status: Status
    reason: str | None
    message: str
    data: dict[str, Any]
    provenance: Provenance
    limits: Limits
    warnings: list[WarningItem]
    recovery: list[RecoveryItem] = Field(max_length=3)


# Minimum `data` of a successful (ok/partial) result, per tool. On a refusal or
# error `data` may be empty; discover_indicators keeps its shape when it asks
# for clarification.

class NextCall(_Closed):
    tool: str
    arguments: dict[str, Any]


class Candidate(_Open):
    """A dataset (`dataset` set) or a reviewed recipe (`recipe` set, `dataset` null)."""
    dataset: str | None
    recipe: str | None = None
    level: str | None
    quality: str | None
    domain: dict[str, Any] | None
    next_call: NextCall | None


class ConceptCard(_Open):
    id: str
    name: str
    definition: str | None
    unit: str | None
    coverage: dict[str, Any] | None
    recipe: str | None
    candidates: list[Candidate]


class DiscoverData(_Open):
    interpretation: dict[str, Any]
    concepts: list[ConceptCard]
    families: list[dict[str, Any]]
    choices: list[dict[str, Any]]


class TimeInfo(_Open):
    column: str | None
    first: str | None
    last: str | None
    frequency: str | None


class DimensionInfo(_Open):
    column: str
    label: str | None
    type: str | None
    option_count: int | None
    examples: list[Any]
    values_truncated: bool
    lookup: NextCall | None


class DescribeData(_Open):
    dataset: str
    name: str | None
    definition: str | None
    measure: str | None
    unit: str | None
    time: TimeInfo
    dimensions: list[DimensionInfo]
    parent: dict[str, Any] | None
    splits: list[dict[str, Any]]
    notes: list[dict[str, Any]]


class ValueItem(_Open):
    value: Any
    label: str | None


class FindValuesData(_Open):
    dataset: str
    column: str
    values: list[ValueItem]
    offset: int
    next_offset: int | None
    total: int | None
    values_truncated: bool
    period_bounds: dict[str, Any] | None


class QueryData(_Open):
    columns: list[str]
    rows: list[list[Any]]
    column_labels: dict[str, dict[str, Any]]
    selection: dict[str, Any] | None


class ChangeRow(_Open):
    entity: dict[str, Any]
    from_value: float
    to_value: float
    absolute: float
    percent: float | None
    rank: int | None


class IntervalResult(_Open):
    from_: str = Field(alias="from")
    to: str
    rows: list[ChangeRow]
    eligible_count: int
    excluded_count: int
    excluded: list[dict[str, Any]]
    exclusions_truncated: bool


class CompareData(_Open):
    dataset: str
    entity_columns: list[str]
    metric: str
    order: str
    intervals: list[IntervalResult]
    # only present when entity_class="cities": the class and how many source entities it left out
    entity_class: Literal["cities"] | None = None
    outside_class_count: int | None = None


class RankingData(_Open):
    dataset: str
    entity_columns: list[str]
    year: str
    unit: str | None
    rows: list[dict[str, Any]]
    eligible_count: int
    excluded_count: int


class RecipeInfo(_Open):
    id: str
    version: Any
    name: str | None
    definition: str | None
    formula: str | None
    value_source: str


class RecipeData(_Open):
    recipe: RecipeInfo
    year: str
    rows: list[dict[str, Any]]
    excluded: list[dict[str, Any]]
    exclusion_counts: dict[str, int]
    exclusions_truncated: bool
    check: dict[str, Any] | None


class LinkItem(_Closed):
    kind: Literal["dataset", "live_selection", "csv", "evidence"]
    url: str
    description: str
    generation_mode: Literal["live_rerun", "expected_generation"]


class LinksData(_Open):
    selection: dict[str, Any]
    links: list[LinkItem]
