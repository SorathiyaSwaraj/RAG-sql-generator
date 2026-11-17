"""Loads the per-database configuration file."""

from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from schema_rag.models import Dialect


class DatabaseConfig(BaseModel):
    dialect: Dialect
    dump_path: Path
    field_docs_dir: Path | None = None
    exclude_tables: list[str] = Field(default_factory=list)


class Settings(BaseModel):
    data_dir: Path = Path("data")
    databases: dict[str, DatabaseConfig]

    def database_dir(self, name: str) -> Path:
        return self.data_dir / name

    def database(self, name: str) -> DatabaseConfig:
        if name not in self.databases:
            raise KeyError(f"unknown database {name!r}, configured: {sorted(self.databases)}")
        return self.databases[name]


def load_settings(path: Path) -> Settings:
    with path.open(encoding="utf-8") as file:
        return Settings.model_validate(yaml.safe_load(file))
