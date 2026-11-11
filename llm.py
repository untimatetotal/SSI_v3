# ============================================================
# llm.py — เรียก Groq แบบมี retry, นับโทเค็น และปิดบังข้อมูลติดต่อก่อนส่ง
# ============================================================

import json
import os
import re
import time

DEFAULT_MODEL = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE_RE = re.compile(r"(?:\+?66[\s-]?|0)\d{1,2}[\s-]?\d{3}[\s-]?\d{3,4}")
ID_RE = re.compile(r"\b\d[\s-]?\d{4}[\s-]?\d{5}[\s-]?\d{2}[\s-]?\d\b")
URL_RE = re.compile(r"https?://\S+|www\.\S+|linkedin\.com/\S+")


def mask_pii(text: str) -> str:
    """ปิดบังอีเมล เบอร์โทร เลขบัตรประชาชน และลิงก์ ก่อนส่งให้ผู้ให้บริการ AI"""
    t = EMAIL_RE.sub("[EMAIL]", text or "")
    t = ID_RE.sub("[ID]", t)
    t = PHONE_RE.sub("[PHONE]", t)
    t = URL_RE.sub("[URL]", t)
    return t


def parse_json_block(raw: str):
    raw = (raw or "").strip().replace("```json", "").replace("```", "")
    starts = [i for i in (raw.find("{"), raw.find("[")) if i >= 0]
    if not starts:
        raise ValueError("no JSON in response")
    start = min(starts)
    end = max(raw.rfind("}"), raw.rfind("]"))
    return json.loads(raw[start:end + 1])


class LLMError(Exception):
    pass


class LLM:
    def __init__(self, api_key: str, model: str = None, max_retries: int = 3):
        from groq import Groq
        self.client = Groq(api_key=api_key)
        self.model = model or DEFAULT_MODEL
        self.max_retries = max_retries
        self.usage = {"in": 0, "out": 0, "calls": 0}

    def chat_json(self, system: str, user: str, max_tokens: int = 2000):
        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                resp = self.client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "system", "content": system},
                              {"role": "user", "content": user}],
                    temperature=0.1,
                    max_tokens=max_tokens,
                    extra_body={"reasoning_effort": "low"},
                )
                usage = getattr(resp, "usage", None)
                self.usage["in"] += getattr(usage, "prompt_tokens", 0) or 0
                self.usage["out"] += getattr(usage, "completion_tokens", 0) or 0
                self.usage["calls"] += 1
                return parse_json_block(resp.choices[0].message.content)
            except Exception as e:
                last_error = e
                name = type(e).__name__
                retryable = "RateLimit" in name or "Timeout" in name or "Connection" in name or "InternalServer" in name
                if not retryable or attempt == self.max_retries:
                    break
                time.sleep(2 ** (attempt + 1))
        raise LLMError(f"{type(last_error).__name__}: {last_error}")
