from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


ContractMode = Literal["inherit", "observe_only", "strict"]
DefaultMode = Literal["observe_only", "strict"]
SchemaIssueSeverity = Literal["INFO", "WARNING", "ERROR"]
PanderaDataType = Literal["string", "numeric", "integer", "boolean", "datetime", "object"]


class TableSchemaContract(BaseModel):
    """Struktur contract untuk satu tabel staging."""

    model_config = ConfigDict(extra="forbid")

    phase: str
    marketplace: str
    source_constant: str
    mode: ContractMode = "inherit"
    required_columns: list[str] = Field(default_factory=list)
    optional_columns: list[str] = Field(default_factory=list)
    deprecated_columns: list[str] = Field(default_factory=list)
    ignored_columns: list[str] = Field(default_factory=list)
    aliases: dict[str, str] = Field(default_factory=dict)
    metadata_columns: list[str] = Field(default_factory=list)
    allowed_columns: list[str]
    business_columns: list[str] = Field(default_factory=list)
    pandera: "PanderaRules" = Field(default_factory=lambda: PanderaRules())

    @field_validator(
        "required_columns",
        "optional_columns",
        "deprecated_columns",
        "ignored_columns",
        "metadata_columns",
        "allowed_columns",
        "business_columns",
    )
    @classmethod
    def reject_duplicate_columns(cls, value: list[str]) -> list[str]:
        duplicates = sorted({column for column in value if value.count(column) > 1})
        if duplicates:
            raise ValueError(f"Kolom duplikat ditemukan: {duplicates}")
        return value

    @model_validator(mode="after")
    def validate_column_membership(self) -> "TableSchemaContract":
        allowed = set(self.allowed_columns)
        subsets = {
            "required_columns": self.required_columns,
            "optional_columns": self.optional_columns,
            "deprecated_columns": self.deprecated_columns,
            "metadata_columns": self.metadata_columns,
            "business_columns": self.business_columns,
        }
        for field_name, columns in subsets.items():
            unknown = sorted(set(columns) - allowed)
            if unknown:
                raise ValueError(f"{field_name} berisi kolom di luar allowed_columns: {unknown}")

        alias_targets = sorted(set(self.aliases.values()) - allowed)
        if alias_targets:
            raise ValueError(f"aliases mengarah ke kolom di luar allowed_columns: {alias_targets}")

        pandera_columns = sorted(set(self.pandera.checks) - allowed)
        if pandera_columns:
            raise ValueError(f"pandera.checks berisi kolom di luar allowed_columns: {pandera_columns}")

        return self


class PanderaColumnRule(BaseModel):
    """Rule validasi isi kolom yang nanti diterjemahkan ke Pandera."""

    model_config = ConfigDict(extra="forbid")

    type: PanderaDataType = "object"
    nullable: bool = True
    coerce: bool = False
    min: int | float | None = None
    max: int | float | None = None
    regex: str | None = None
    allowed_values: list[Any] = Field(default_factory=list)
    severity: SchemaIssueSeverity = "WARNING"


class PanderaRules(BaseModel):
    """Kumpulan rule Pandera untuk satu contract tabel."""

    model_config = ConfigDict(extra="forbid")

    checks: dict[str, PanderaColumnRule] = Field(default_factory=dict)


class SchemaContractsConfig(BaseModel):
    """Root config untuk seluruh schema contract."""

    model_config = ConfigDict(extra="forbid")

    contract_version: int
    default_mode: DefaultMode = "observe_only"
    contracts: dict[str, TableSchemaContract]


class SchemaIssue(BaseModel):
    """Satu temuan schema drift pada DataFrame upload."""

    model_config = ConfigDict(extra="forbid")

    severity: SchemaIssueSeverity
    drift_type: str
    column_name: str | None = None
    message: str


class SchemaValidationResult(BaseModel):
    """Hasil validasi schema drift untuk satu DataFrame."""

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    table_name: str
    effective_mode: DefaultMode
    can_continue: bool
    normalized_df: Any
    original_columns: list[str]
    normalized_columns: list[str]
    dropped_columns: list[str] = Field(default_factory=list)
    renamed_columns: dict[str, str] = Field(default_factory=dict)
    missing_required_columns: list[str] = Field(default_factory=list)
    missing_optional_columns: list[str] = Field(default_factory=list)
    extra_columns: list[str] = Field(default_factory=list)
    deprecated_columns: list[str] = Field(default_factory=list)
    ignored_columns: list[str] = Field(default_factory=list)
    issues: list[SchemaIssue] = Field(default_factory=list)

    @property
    def errors(self) -> list[SchemaIssue]:
        return [issue for issue in self.issues if issue.severity == "ERROR"]

    @property
    def warnings(self) -> list[SchemaIssue]:
        return [issue for issue in self.issues if issue.severity == "WARNING"]

    @property
    def infos(self) -> list[SchemaIssue]:
        return [issue for issue in self.issues if issue.severity == "INFO"]
