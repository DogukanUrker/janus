from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    github_app_id: str = ""
    github_app_slug: str = "janus-maintainer"
    github_private_key_path: str = "./janus.private-key.pem"
    github_webhook_secret: str = ""

    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    dashscope_api_key: str = ""
    dashscope_base_url: str = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
    model_mid: str = "qwen3.6-plus"
    model_max: str = "qwen3.7-max"
    model_coder: str = "qwen3-coder-plus"
    model_vl: str = "qwen3-vl-plus"

    database_url: str = "sqlite+aiosqlite:///janus.db"

    oss_access_key_id: str = ""
    oss_access_key_secret: str = ""
    oss_bucket: str = ""
    oss_endpoint: str = "https://oss-ap-southeast-1.aliyuncs.com"

    janus_env: str = "dev"

    @property
    def is_prod(self) -> bool:
        return self.janus_env == "prod"

    def validate_prod(self) -> None:
        if not self.is_prod:
            return
        missing = [
            name
            for name in (
                "github_app_id",
                "github_webhook_secret",
                "dashscope_api_key",
                "telegram_bot_token",
                "oss_access_key_id",
                "oss_bucket",
            )
            if not getattr(self, name)
        ]
        if missing:
            raise RuntimeError(f"missing required settings in prod: {', '.join(missing)}")


settings = Settings()
