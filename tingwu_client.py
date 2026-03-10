import json
import time
import asyncio
import logging
from dataclasses import dataclass
from typing import Any

import httpx
from aliyunsdkcore.client import AcsClient
from aliyunsdkcore.request import CommonRequest
from aliyunsdkcore.auth.credentials import AccessKeyCredential

from config import settings

logger = logging.getLogger(__name__)

TINGWU_DOMAIN = "tingwu.cn-beijing.aliyuncs.com"
TINGWU_VERSION = "2023-09-30"

LANGUAGE_MAP = {
    "zh": "cn", "cn": "cn", "chinese": "cn",
    "en": "en", "english": "en",
    "yue": "yue", "cantonese": "yue",
    "ja": "ja", "japanese": "ja",
    "ko": "ko", "korean": "ko",
    "auto": "auto",
}


@dataclass
class TingwuResult:
    task_id: str
    status: str
    transcription_url: str | None = None
    raw_response: dict | None = None


def _get_acs_client() -> AcsClient:
    credentials = AccessKeyCredential(
        settings.access_key_id, settings.access_key_secret
    )
    return AcsClient(region_id="cn-beijing", credential=credentials)


def _make_request(method: str, uri: str, query_params: dict | None = None,
                  body: dict | None = None) -> dict:
    client = _get_acs_client()
    request = CommonRequest()
    request.set_accept_format("json")
    request.set_domain(TINGWU_DOMAIN)
    request.set_version(TINGWU_VERSION)
    request.set_protocol_type("https")
    request.set_method(method)
    request.set_uri_pattern(uri)
    request.add_header("Content-Type", "application/json")

    if query_params:
        for k, v in query_params.items():
            request.add_query_param(k, v)

    if body:
        request.set_content(json.dumps(body).encode("utf-8"))

    response = client.do_action_with_exception(request)
    return json.loads(response)


def normalize_language(lang: str | None) -> str:
    if not lang:
        return "cn"
    lang = lang.lower().strip()
    return LANGUAGE_MAP.get(lang, lang)


def create_task(
    file_url: str,
    language: str = "cn",
    diarization_enabled: bool = True,
    speaker_count: int = 0,
) -> str:
    """创建离线转写任务，返回 TaskId。"""
    body = {
        "AppKey": settings.tingwu_app_key,
        "Input": {
            "SourceLanguage": normalize_language(language),
            "TaskKey": f"proxy_{int(time.time())}",
            "FileUrl": file_url,
        },
        "Parameters": {
            "Transcription": {
                "DiarizationEnabled": diarization_enabled,
                "Diarization": {"SpeakerCount": speaker_count},
            },
        },
    }

    logger.info("创建听悟任务: language=%s, diarization=%s", language, diarization_enabled)
    resp = _make_request("PUT", "/openapi/tingwu/v2/tasks",
                         query_params={"type": "offline"}, body=body)

    if resp.get("Code") != "0":
        raise RuntimeError(f"创建任务失败: {resp.get('Message', resp)}")

    task_id = resp["Data"]["TaskId"]
    logger.info("任务已创建: TaskId=%s", task_id)
    return task_id


def get_task_info(task_id: str) -> TingwuResult:
    """查询任务状态和结果。"""
    uri = f"/openapi/tingwu/v2/tasks/{task_id}"
    resp = _make_request("GET", uri)

    data = resp.get("Data", {})
    status = data.get("TaskStatus", "UNKNOWN")
    transcription_url = None
    if "Result" in data and "Transcription" in data["Result"]:
        transcription_url = data["Result"]["Transcription"]

    return TingwuResult(
        task_id=task_id,
        status=status,
        transcription_url=transcription_url,
        raw_response=resp,
    )


async def wait_for_completion(task_id: str) -> TingwuResult:
    """轮询等待任务完成，返回最终结果。"""
    deadline = time.time() + settings.tingwu_timeout
    interval = settings.tingwu_poll_interval

    while time.time() < deadline:
        result = get_task_info(task_id)
        logger.info("任务 %s 状态: %s", task_id, result.status)

        if result.status == "COMPLETED":
            return result
        if result.status == "FAILED":
            raise RuntimeError(
                f"任务失败: {result.raw_response.get('Message', 'unknown error')}"
            )

        await asyncio.sleep(interval)

    raise TimeoutError(f"任务 {task_id} 在 {settings.tingwu_timeout}s 内未完成")


async def download_transcription(url: str) -> dict[str, Any]:
    """下载并解析转写结果 JSON。"""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.json()
