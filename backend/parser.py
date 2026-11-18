import base64
import io
import json
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
import httpx

_ocr_engine = None


def ocr_image_locally(image_base64: str) -> str:
    """使用本地免费 RapidOCR 识别图片中的中文/英文文本。"""
    global _ocr_engine
    if _ocr_engine is None:
        from rapidocr_onnxruntime import RapidOCR

        _ocr_engine = RapidOCR()

    from PIL import Image

    raw_b64 = image_base64.split(",", 1)[1] if "," in image_base64 else image_base64
    img_bytes = base64.b64decode(raw_b64)
    img = Image.open(io.BytesIO(img_bytes)).convert("RGB")

    import numpy as np

    result, _ = _ocr_engine(np.array(img))
    if not result:
        return ""
    # result 每项格式: [box, text, score]
    lines = [item[1] for item in result if len(item) >= 2 and item[1].strip()]
    return "\n".join(lines)


def _today_str(offset_days: int = 0) -> str:
    return (datetime.now() + timedelta(days=offset_days)).strftime("%Y-%m-%d")


def _extract_chinese_date(text: str) -> str:
    now = datetime.now()
    if "明天" in text:
        return _today_str(1)
    if "后天" in text:
        return _today_str(2)
    if "昨天" in text:
        return _today_str(-1)

    md = re.search(r"(\d{1,2})月(\d{1,2})[日号]", text)
    if md:
        return f"{now.year}-{int(md.group(1)):02d}-{int(md.group(2)):02d}"

    wk = re.search(r"(?:本周|这周|下周)?周([一二三四五六日天])", text)
    if wk:
        wk_map = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "日": 7, "天": 7}
        target = wk_map[wk.group(1)]
        current = now.isoweekday()
        diff = target - current
        if "下周" in wk.group(0):
            diff += 7
        elif diff < 0:
            diff += 7
        return _today_str(diff)

    return _today_str(0)


def _cn_num_to_int(s: str) -> Optional[int]:
    if s.isdigit():
        return int(s)
    digit_map = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    if s == "十":
        return 10
    if "十" in s:
        parts = s.split("十")
        tens = digit_map.get(parts[0], 1) if parts[0] else 1
        ones = digit_map.get(parts[1], 0) if len(parts) > 1 and parts[1] else 0
        return tens * 10 + ones
    if len(s) == 1 and s in digit_map:
        return digit_map[s]
    return None


def _extract_chinese_time(text: str) -> tuple[str, str]:
    rng = re.search(r"(\d{1,2})[:：](\d{2})\s*[-~到至]\s*(\d{1,2})[:：](\d{2})", text)
    if rng:
        return (
            f"{int(rng.group(1)):02d}:{rng.group(2)}",
            f"{int(rng.group(3)):02d}:{rng.group(4)}",
        )

    single = re.search(r"(\d{1,2})[:：](\d{2})", text)
    if single:
        h = int(single.group(1))
        m = single[2] if isinstance(single, tuple) else single.group(2)
        return f"{h:02d}:{m}", f"{(h + 1) % 24:02d}:{m}"

    cn = re.search(r"(早上|上午|中午|下午|晚上)?\s*([0-9一二两三四五六七八九十]{1,3})点(半|([0-9一二三四五六七八九十]{1,3})分?)?", text)
    if cn:
        h = _cn_num_to_int(cn.group(2))
        if h is not None:
            if cn.group(1) in ("下午", "晚上") and h < 12:
                h += 12
            elif cn.group(1) == "中午" and h < 11:
                h += 12
            if cn.group(3) == "半":
                m = "30"
            elif cn.group(4):
                m_val = _cn_num_to_int(cn.group(4))
                m = f"{m_val:02d}" if m_val is not None else "00"
            else:
                m = "00"
            return f"{h:02d}:{m}", f"{(h + 1) % 24:02d}:{m}"

    return "09:00", "10:00"


def _guess_category(text: str) -> str:
    if re.search(r"饭|吃|面|鸡|奶茶|咖啡|食堂|外卖|早餐|午餐|晚餐", text):
        return "餐饮"
    if re.search(r"地铁|打车|滴滴|公交|高铁|机票|车费", text):
        return "交通"
    if re.search(r"书|打印|文具|课程|资料", text):
        return "学习"
    if re.search(r"电影|游戏|KTV|门票", text):
        return "娱乐"
    if re.search(r"淘宝|京东|超市|买", text):
        return "购物"
    return "其他"


def parse_text_locally(text: str, mode: str = "auto") -> Dict[str, List[Dict[str, Any]]]:
    """免 AI Key 的本地中文规则解析器，方便直接联调与无图文字提取。"""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    events: List[Dict[str, Any]] = []
    expenses: List[Dict[str, Any]] = []

    for line in lines:
        money = re.search(r"(?:[¥￥]\s*(\d+(?:\.\d{1,2})?))|(?:(\d+(?:\.\d{1,2})?)\s*元)", line)
        has_time = bool(
            re.search(
                r"(\d{1,2}[:：]\d{2}|[早上午下晚]午?\s*[0-9一二两三四五六七八九十]{1,3}点|明天|后天|今天|周[一二三四五六日天]|\d{1,2}月\d{1,2}[日号])",
                line,
            )
        )

        if mode != "calendar" and money:
            amount = float(money.group(1) or money.group(2))
            item = re.sub(r"(今天|昨天|前天|中午|晚上|早上|花了|消费|支付|买了|吃了)", "", line.replace(money.group(0), "")).strip()
            expenses.append(
                {
                    "date": _extract_chinese_date(line),
                    "item": item[:24] or "消费记录",
                    "category": _guess_category(line),
                    "amount": amount,
                    "note": "本地文本提取",
                }
            )

        if mode != "expense" and (has_time or not money):
            loc = re.search(
                r"(?:在|地点[：:]?\s*)([A-Za-z0-9\u4e00-\u9fa5\-]+?(?:教室|会议室|楼|室|厅|馆|校区|A\d+|B\d+|C\d+|\d{3}))",
                line,
            )
            title = re.sub(r"【.*?】", "", line).strip()[:28]
            if title and (has_time or loc):
                start_t, end_t = _extract_chinese_time(line)
                events.append(
                    {
                        "title": title,
                        "date": _extract_chinese_date(line),
                        "startTime": start_t,
                        "endTime": end_t,
                        "location": loc.group(1) if loc else "",
                        "note": line,
                    }
                )

    return {"events": events, "expenses": expenses}


async def call_vision_ai(
    text: str,
    image_base64: Optional[str],
    mode: str,
    provider: str,
    base_url: str,
    model: str,
    api_key: str,
) -> Dict[str, List[Dict[str, Any]]]:
    """调用多模态大模型识别截图或复杂通知文本。"""
    today = _today_str(0)
    weekday = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][datetime.now().isoweekday() - 1]
    mode_hint = {
        "calendar": "只提取日程 events，expenses 返回空数组 []。",
        "expense": "只提取消费账单 expenses，events 返回空数组 []。",
    }.get(mode, "同时判断内容中是否包含日程或消费账单，能提尽提。")

    system_prompt = (
        f"你是一个精准的日程与账单提取助手。今天是 {today}（{weekday}）。{mode_hint}\n"
        "请严格只输出合法的 JSON 对象（不要输出任何 markdown 解释），格式：\n"
        '{"events":[{"title":"","date":"YYYY-MM-DD","startTime":"HH:MM","endTime":"HH:MM","location":"","note":""}],'
        '"expenses":[{"date":"YYYY-MM-DD","item":"","category":"餐饮/交通/购物/学习/娱乐/其他","amount":0,"note":""}]}'
    )
    user_prompt = f"请从以下内容中提取信息：\n{text}" if text else "请从这张截图中提取日程或消费账单信息。"

    async with httpx.AsyncClient(timeout=45.0) as client:
        if provider == "gemini":
            endpoint = f"{base_url.rstrip('/')}/models/{model}:generateContent?key={api_key}"
            parts: List[Dict[str, Any]] = [{"text": f"{system_prompt}\n\n{user_prompt}"}]
            if image_base64:
                raw_b64 = image_base64.split(",", 1)[1] if "," in image_base64 else image_base64
                parts.append({"inline_data": {"mime_type": "image/jpeg", "data": raw_b64}})
            resp = await client.post(endpoint, json={"contents": [{"parts": parts}], "generationConfig": {"temperature": 0.1}})
            resp.raise_for_status()
            raw_text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
        else:
            endpoint = f"{base_url.rstrip('/')}/chat/completions"
            user_content: List[Dict[str, Any]] = [{"type": "text", "text": user_prompt}]
            if image_base64:
                img_url = image_base64 if image_base64.startswith("data:") else f"data:image/jpeg;base64,{image_base64}"
                user_content.append({"type": "image_url", "image_url": {"url": img_url}})
            resp = await client.post(
                endpoint,
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": model,
                    "temperature": 0.1,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_content},
                    ],
                },
            )
            resp.raise_for_status()
            raw_text = resp.json()["choices"][0]["message"]["content"]

    cleaned = re.sub(r"```json\s*|```", "", raw_text, flags=re.IGNORECASE).strip()
    match = re.search(r"\{[\s\S]*\}", cleaned)
    if not match:
        raise ValueError("AI 返回结果无法解析为 JSON")
    parsed = json.loads(match.group(0))
    return {
        "events": parsed.get("events", []) if isinstance(parsed.get("events"), list) else [],
        "expenses": parsed.get("expenses", []) if isinstance(parsed.get("expenses"), list) else [],
    }
