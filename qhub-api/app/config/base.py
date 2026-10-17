from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class EnvConfig(BaseSettings):
    # El .env vive en la raíz del servicio (junto a main.py), dos niveles por encima de
    # app/config/. Se resuelve de forma absoluta (como en la referencia) para que los
    # valores sean los mismos sin importar el directorio desde el que se arranque:
    # tests, `uvicorn main:app`, o el contenedor. Con la ruta relativa ".env" anterior,
    # correr desde otro cwd dejaría de encontrarlo.
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[2] / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )
