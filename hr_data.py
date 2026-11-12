# ============================================================
# hr_data.py — ข้อมูลที่ HR กรอกเองต่อใบสมัคร (ใช้แทนค่าที่อ่านจากไฟล์)
# ============================================================

import copy
import re

NUMBER_FIELDS = {
    "salary_expectation": ("เงินเดือนที่ต้องการ", 0, 10_000_000),
    "age": ("อายุ", 15, 75),
    "gpa": ("GPA", 0, 4),
    "experience_years": ("ประสบการณ์ (ปี)", 0, 60),
}
LABELS = {"salary_expectation": "เงินเดือนที่ต้องการ", "age": "อายุ", "gender": "เพศ",
          "gpa": "GPA", "experience_years": "ประสบการณ์"}


def clean_hr_data(payload: dict) -> dict:
    """ตรวจค่าที่ HR ส่งมา — ช่องว่างหมายถึงลบค่านั้น"""
    if not isinstance(payload, dict):
        raise ValueError("รูปแบบข้อมูลไม่ถูกต้อง")
    data = {}
    for key, (label, low, high) in NUMBER_FIELDS.items():
        raw = payload.get(key)
        if raw is None or str(raw).strip() == "":
            continue
        try:
            value = float(str(raw).replace(",", ""))
        except ValueError:
            raise ValueError(f"{label} ต้องเป็นตัวเลข")
        if not low <= value <= high:
            raise ValueError(f"{label} ต้องอยู่ระหว่าง {low:g} ถึง {high:g}")
        data[key] = int(value) if key == "age" else round(value, 2)
    if payload.get("gender") in ("male", "female"):
        data["gender"] = payload["gender"]
    note = str(payload.get("note") or "").strip()
    if note:
        data["note"] = note[:1000]
    tags = payload.get("tags") or []
    if isinstance(tags, str):
        tags = re.split(r"[,\n]+", tags)
    tags = [str(t).strip()[:30] for t in tags if str(t).strip()][:10]
    if tags:
        data["tags"] = tags
    return data


def apply_hr_data(parsed: dict, data: dict) -> dict:
    """คืน parsed ชุดใหม่ที่ใช้ค่าจาก HR แทนค่าที่อ่านได้ และจดว่าช่องไหนมาจาก HR"""
    if not data:
        return parsed
    out = dict(parsed)
    p = copy.deepcopy(parsed.get("profile") or {})
    used = []
    if "gpa" in data:
        p["gpa"] = data["gpa"]
        p["gpa_evidence"] = f"HR กรอก: GPA {data['gpa']:.2f}"
        used.append(f"GPA {data['gpa']:.2f}")
    if "experience_years" in data:
        p["experience_months"] = int(round(data["experience_years"] * 12))
        p["experience_source"] = "hr"
        p["jobs"] = []
        used.append(f"ประสบการณ์ {data['experience_years']:g} ปี")
    if "age" in data:
        p["age"] = data["age"]
        p["age_source"] = "hr"
        used.append(f"อายุ {data['age']} ปี")
    if "gender" in data:
        p["gender"] = data["gender"]
        used.append("เพศ" + ("ชาย" if data["gender"] == "male" else "หญิง"))
    if "salary_expectation" in data:
        p["salary_expectation"] = data["salary_expectation"]
        used.append(f"เงินเดือนที่ต้องการ {data['salary_expectation']:,.0f} บาท")
    p["hr_fields"] = used
    out["profile"] = p
    return out
