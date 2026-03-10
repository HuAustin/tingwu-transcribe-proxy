"""
MacWhisper-Tongyi: 通义听悟 → OpenAI Whisper API 兼容代理服务

启动方式:
  服务器模式:  python main.py
  CLI 模式:    python main.py transcribe <音频文件路径> [--language cn] [--format srt]
"""

import argparse
import asyncio
import json
import logging
import os
import subprocess
import sys
import tempfile
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, File, Form, UploadFile, HTTPException
from fastapi.responses import Response

import oss_client
import tingwu_client
import converter
from config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("macwhisper-tongyi")


@asynccontextmanager
async def lifespan(app: FastAPI):
    errors = settings.validate()
    if errors:
        for e in errors:
            logger.error("配置错误: %s", e)
        logger.error("请参考 .env.example 配置环境变量")
        sys.exit(1)
    logger.info("MacWhisper-Tongyi 代理已启动 → http://%s:%s", settings.server_host, settings.server_port)
    yield


app = FastAPI(
    title="MacWhisper-Tongyi Proxy",
    description="通义听悟 → OpenAI Whisper API 兼容代理",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/v1/models")
async def list_models():
    return {
        "object": "list",
        "data": [
            {
                "id": "tingwu-v2",
                "object": "model",
                "owned_by": "alibaba-cloud",
            }
        ],
    }


VIDEO_EXTENSIONS = {".mp4", ".wmv", ".m4v", ".flv", ".rmvb", ".dat", ".mov", ".mkv", ".webm", ".avi", ".mpeg", ".3gp", ".ogg"}
AUDIO_SIZE_THRESHOLD = 10 * 1024 * 1024  # 10MB 以上才提取


def extract_audio(file_bytes: bytes, filename: str) -> tuple[bytes, str]:
    """对大视频文件用 ffmpeg 提取音频轨道（mp3），大幅缩减体积。"""
    ext = os.path.splitext(filename)[1].lower()
    if ext not in VIDEO_EXTENSIONS or len(file_bytes) < AUDIO_SIZE_THRESHOLD:
        return file_bytes, filename

    with tempfile.TemporaryDirectory() as tmpdir:
        src = os.path.join(tmpdir, f"input{ext}")
        dst = os.path.join(tmpdir, "output.mp3")
        with open(src, "wb") as f:
            f.write(file_bytes)

        result = subprocess.run(
            ["ffmpeg", "-i", src, "-vn", "-acodec", "libmp3lame", "-q:a", "4", "-y", dst],
            capture_output=True, timeout=120,
        )
        if result.returncode != 0 or not os.path.exists(dst):
            logger.warning("ffmpeg 提取失败，使用原始文件: %s", result.stderr[-200:] if result.stderr else "")
            return file_bytes, filename

        with open(dst, "rb") as f:
            audio_bytes = f.read()

        new_name = os.path.splitext(filename)[0] + ".mp3"
        logger.info("音频提取: %s (%d bytes) → %s (%d bytes), 压缩 %.0f%%",
                     filename, len(file_bytes), new_name, len(audio_bytes),
                     (1 - len(audio_bytes) / len(file_bytes)) * 100)
        return audio_bytes, new_name


CONTENT_TYPE_MAP = {
    "json": "application/json",
    "verbose_json": "application/json",
    "srt": "text/plain; charset=utf-8",
    "vtt": "text/plain; charset=utf-8",
    "text": "text/plain; charset=utf-8",
}


@app.post("/v1/audio/transcriptions")
async def transcribe(
    file: UploadFile = File(...),
    model: str = Form(default="tingwu-v2"),
    language: str = Form(default=None),
    response_format: str = Form(default="json"),
    prompt: str = Form(default=None),
    temperature: float = Form(default=0),
):
    if response_format not in converter.FORMATTERS:
        raise HTTPException(400, f"不支持的格式: {response_format}")

    file_bytes = await file.read()
    filename = file.filename or "audio.wav"
    lang = language or "cn"

    object_key = None
    try:
        logger.info("收到文件: %s (%d bytes)", filename, len(file_bytes))

        upload_bytes, upload_name = await asyncio.get_running_loop().run_in_executor(
            None, extract_audio, file_bytes, filename
        )

        file_url, object_key = oss_client.upload_file(upload_bytes, upload_name)
        logger.info("已上传至 OSS: %s", object_key)

        task_id = tingwu_client.create_task(file_url=file_url, language=lang)
        result = await tingwu_client.wait_for_completion(task_id)

        if not result.transcription_url:
            raise HTTPException(500, "转写完成但未返回结果 URL")

        tingwu_data = await tingwu_client.download_transcription(result.transcription_url)
        logger.info("转写完成，格式转换 → %s", response_format)
        formatted = converter.FORMATTERS[response_format](tingwu_data)

        if isinstance(formatted, str):
            payload = formatted.encode("utf-8")
        else:
            payload = json.dumps(formatted, ensure_ascii=False).encode("utf-8")

        return Response(
            content=payload,
            media_type=CONTENT_TYPE_MAP.get(response_format, "application/json"),
            headers={"Content-Length": str(len(payload))},
        )

    except TimeoutError as e:
        raise HTTPException(504, str(e))
    except RuntimeError as e:
        raise HTTPException(502, str(e))
    except Exception as e:
        logger.exception("转写错误")
        raise HTTPException(500, f"内部错误: {e}")
    finally:
        if object_key:
            try:
                oss_client.delete_file(object_key)
                logger.info("已清理 OSS: %s", object_key)
            except Exception:
                logger.warning("清理失败: %s", object_key)


# ─── CLI 模式 ───────────────────────────────────────────────────


def cli_transcribe(args):
    errors = settings.validate()
    if errors:
        for e in errors:
            print(f"[错误] {e}", file=sys.stderr)
        print("请参考 .env.example 配置环境变量", file=sys.stderr)
        sys.exit(1)

    with open(args.file, "rb") as f:
        file_bytes = f.read()

    filename = args.file.split("/")[-1]
    print(f"[1/4] 上传文件至 OSS: {filename} ({len(file_bytes)} bytes)")
    file_url, object_key = oss_client.upload_file(file_bytes, filename)

    try:
        print("[2/4] 创建听悟转写任务...")
        task_id = tingwu_client.create_task(
            file_url=file_url,
            language=args.language,
        )
        print(f"       TaskId: {task_id}")

        print("[3/4] 等待转写完成...")
        result = asyncio.run(tingwu_client.wait_for_completion(task_id))

        if not result.transcription_url:
            print("[错误] 转写完成但未返回结果", file=sys.stderr)
            sys.exit(1)

        tingwu_data = asyncio.run(
            tingwu_client.download_transcription(result.transcription_url)
        )

        print(f"[4/4] 格式化输出 ({args.format}):")
        formatted = converter.FORMATTERS[args.format](tingwu_data)

        if isinstance(formatted, dict):
            output = json.dumps(formatted, ensure_ascii=False, indent=2)
        else:
            output = formatted

        if args.output:
            with open(args.output, "w", encoding="utf-8") as out:
                out.write(output)
            print(f"       结果已保存至: {args.output}")
        else:
            print()
            print(output)

    finally:
        try:
            oss_client.delete_file(object_key)
        except Exception:
            pass


def main():
    parser = argparse.ArgumentParser(
        description="MacWhisper-Tongyi: 通义听悟转写代理"
    )
    subparsers = parser.add_subparsers(dest="command")

    sub_serve = subparsers.add_parser("serve", help="启动 API 代理服务器")
    sub_serve.add_argument("--host", default=None)
    sub_serve.add_argument("--port", type=int, default=None)

    sub_cli = subparsers.add_parser("transcribe", help="CLI 模式转写音频文件")
    sub_cli.add_argument("file", help="音频/视频文件路径")
    sub_cli.add_argument("--language", "-l", default="cn", help="语言代码 (cn/en/yue/ja/ko/auto)")
    sub_cli.add_argument("--format", "-f", default="text", choices=list(converter.FORMATTERS.keys()))
    sub_cli.add_argument("--output", "-o", default=None, help="输出文件路径")

    args = parser.parse_args()

    if args.command == "transcribe":
        cli_transcribe(args)
    else:
        host = args.host if args.command == "serve" and args.host else settings.server_host
        port = args.port if args.command == "serve" and args.port else settings.server_port
        uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
