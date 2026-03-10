import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    access_key_id: str = os.getenv("ALIBABA_CLOUD_ACCESS_KEY_ID", "")
    access_key_secret: str = os.getenv("ALIBABA_CLOUD_ACCESS_KEY_SECRET", "")
    tingwu_app_key: str = os.getenv("TINGWU_APP_KEY", "")

    oss_bucket_name: str = os.getenv("OSS_BUCKET_NAME", "")
    oss_endpoint: str = os.getenv("OSS_ENDPOINT", "oss-cn-beijing.aliyuncs.com")
    oss_prefix: str = os.getenv("OSS_PREFIX", "tingwu-proxy/")
    oss_expire_seconds: int = int(os.getenv("OSS_EXPIRE_SECONDS", "7200"))

    server_host: str = os.getenv("SERVER_HOST", "0.0.0.0")
    server_port: int = int(os.getenv("SERVER_PORT", "8000"))
    tingwu_poll_interval: int = int(os.getenv("TINGWU_POLL_INTERVAL", "5"))
    tingwu_timeout: int = int(os.getenv("TINGWU_TIMEOUT", "600"))

    def validate(self) -> list[str]:
        errors = []
        if not self.access_key_id:
            errors.append("ALIBABA_CLOUD_ACCESS_KEY_ID 未设置")
        if not self.access_key_secret:
            errors.append("ALIBABA_CLOUD_ACCESS_KEY_SECRET 未设置")
        if not self.tingwu_app_key:
            errors.append("TINGWU_APP_KEY 未设置")
        if not self.oss_bucket_name:
            errors.append("OSS_BUCKET_NAME 未设置")
        return errors


settings = Settings()
