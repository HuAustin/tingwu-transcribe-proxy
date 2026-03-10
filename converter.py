"""将通义听悟转写结果转换为 OpenAI Whisper API 兼容格式。"""

from typing import Any


def _extract_full_text(tingwu_data: dict[str, Any]) -> str:
    """从听悟 Paragraphs 中提取完整文本。"""
    transcription = tingwu_data.get("Transcription", {})
    paragraphs = transcription.get("Paragraphs", [])
    parts: list[str] = []
    for para in paragraphs:
        words = para.get("Words", [])
        parts.append("".join(w.get("Text", "") for w in words))
    return "".join(parts)


def _extract_segments(tingwu_data: dict[str, Any]) -> list[dict[str, Any]]:
    """从听悟 Paragraphs 中提取按句子分组的 segments，精确匹配 OpenAI 格式。"""
    transcription = tingwu_data.get("Transcription", {})
    paragraphs = transcription.get("Paragraphs", [])
    segments: list[dict[str, Any]] = []
    seg_id = 0

    for para in paragraphs:
        words = para.get("Words", [])
        sentences: dict[int, list[dict]] = {}
        for w in words:
            sid = w.get("SentenceId", 0)
            sentences.setdefault(sid, []).append(w)

        for _, sentence_words in sorted(sentences.items()):
            if not sentence_words:
                continue
            text = "".join(w.get("Text", "") for w in sentence_words)
            start_ms = sentence_words[0].get("Start", 0)
            end_ms = sentence_words[-1].get("End", 0)
            start_sec = start_ms / 1000.0
            end_sec = end_ms / 1000.0
            segments.append({
                "id": seg_id,
                "seek": int(start_ms / 20),
                "start": start_sec,
                "end": end_sec,
                "text": text,
                "tokens": [],
                "temperature": 0.0,
                "avg_logprob": 0.0,
                "compression_ratio": 1.0,
                "no_speech_prob": 0.0,
            })
            seg_id += 1

    return segments


def _get_duration(tingwu_data: dict[str, Any]) -> float:
    audio_info = tingwu_data.get("Transcription", {}).get("AudioInfo", {})
    return audio_info.get("Duration", 0) / 1000.0


def _get_language(tingwu_data: dict[str, Any]) -> str:
    return (
        tingwu_data.get("Transcription", {})
        .get("AudioInfo", {})
        .get("Language", "cn")
    )


def to_openai_json(tingwu_data: dict[str, Any]) -> dict[str, Any]:
    return {"text": _extract_full_text(tingwu_data)}


def to_openai_verbose_json(tingwu_data: dict[str, Any]) -> dict[str, Any]:
    return {
        "task": "transcribe",
        "language": _get_language(tingwu_data),
        "duration": _get_duration(tingwu_data),
        "text": _extract_full_text(tingwu_data),
        "segments": _extract_segments(tingwu_data),
        "words": [],
    }


def to_text(tingwu_data: dict[str, Any]) -> str:
    return _extract_full_text(tingwu_data)


def _format_timestamp_srt(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _format_timestamp_vtt(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def to_srt(tingwu_data: dict[str, Any]) -> str:
    segments = _extract_segments(tingwu_data)
    lines: list[str] = []
    for seg in segments:
        lines.append(str(seg["id"] + 1))
        lines.append(
            f"{_format_timestamp_srt(seg['start'])} --> {_format_timestamp_srt(seg['end'])}"
        )
        lines.append(seg["text"])
        lines.append("")
    return "\n".join(lines)


def to_vtt(tingwu_data: dict[str, Any]) -> str:
    segments = _extract_segments(tingwu_data)
    lines: list[str] = ["WEBVTT", ""]
    for seg in segments:
        lines.append(
            f"{_format_timestamp_vtt(seg['start'])} --> {_format_timestamp_vtt(seg['end'])}"
        )
        lines.append(seg["text"])
        lines.append("")
    return "\n".join(lines)


FORMATTERS = {
    "json": to_openai_json,
    "verbose_json": to_openai_verbose_json,
    "text": to_text,
    "srt": to_srt,
    "vtt": to_vtt,
}
