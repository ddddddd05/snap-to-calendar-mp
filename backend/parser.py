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

    ymd = re.search(r"(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})", text)
    if ymd:
        return f"{ymd.group(1)}-{int(ymd.group(2)):02d}-{int(ymd.group(3)):02d}"

    md = re.search(r"(\d{1,2})月(\d{1,2})[日号]", text)
    if md:
        return f"{now.year}-{int(md.group(1)):02d}-{int(md.group(2)):02d}"

    wk = re.search(r"(本|这|下)?(?:周|星期|礼拜)([一二三四五六日天])", text)
    if wk:
        wk_map = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "日": 7, "天": 7}
        target = wk_map[wk.group(2)]
        current = now.isoweekday()
        diff = target - current
        if wk.group(1) == "下":
            diff = target - current + 7
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


_CN_NUM = r"[0-9一二两三四五六七八九十]{1,3}"
_PERIOD = r"(早上|上午|中午|下午|晚上)"


def _to_24h(period: Optional[str], h: int) -> int:
    if period in ("下午", "晚上") and h < 12:
        return h + 12
    if period == "中午" and h < 11:
        return h + 12
    return h


def _cn_minutes(half: Optional[str], minute: Optional[str]) -> str:
    if half == "半":
        return "30"
    if minute:
        m_val = _cn_num_to_int(minute)
        return f"{m_val:02d}" if m_val is not None else "00"
    return "00"


def _extract_chinese_time(text: str) -> tuple[str, str]:
    rng = re.search(r"(\d{1,2})[:：](\d{2})\s*[-~—到至]\s*(\d{1,2})[:：](\d{2})", text)
    if rng:
        period = re.search(_PERIOD + r"\s*$", text[: rng.start()])
        p = period.group(1) if period else None
        return (
            f"{_to_24h(p, int(rng.group(1))):02d}:{rng.group(2)}",
            f"{_to_24h(p, int(rng.group(3))):02d}:{rng.group(4)}",
        )

    single = re.search(r"(\d{1,2})[:：](\d{2})", text)
    if single:
        period = re.search(_PERIOD + r"\s*$", text[: single.start()])
        h = _to_24h(period.group(1) if period else None, int(single.group(1)))
        m = single.group(2)
        return f"{h:02d}:{m}", f"{(h + 1) % 24:02d}:{m}"

    # 中文时间段：下午2点到4点半 / 晚上七点至九点
    cn_rng = re.search(
        _PERIOD + r"?\s*(" + _CN_NUM + r")点(半|(" + _CN_NUM + r")分?)?\s*[-~—到至]\s*(" + _CN_NUM + r")点(半|(" + _CN_NUM + r")分?)?",
        text,
    )
    if cn_rng:
        h1, h2 = _cn_num_to_int(cn_rng.group(2)), _cn_num_to_int(cn_rng.group(5))
        if h1 is not None and h2 is not None:
            p = cn_rng.group(1)
            sh, eh = _to_24h(p, h1), _to_24h(p, h2)
            if eh < sh:  # 如“上午11点到1点”
                eh += 12
            return (
                f"{sh:02d}:{_cn_minutes(cn_rng.group(3), cn_rng.group(4))}",
                f"{eh % 24:02d}:{_cn_minutes(cn_rng.group(6), cn_rng.group(7))}",
            )

    cn = re.search(_PERIOD + r"?\s*(" + _CN_NUM + r")点(半|(" + _CN_NUM + r")分?)?", text)
    if cn:
        h = _cn_num_to_int(cn.group(2))
        if h is not None:
            h = _to_24h(cn.group(1), h)
            m = _cn_minutes(cn.group(3), cn.group(4))
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


# 地点：先吃掉地名主体，再带上后面的房间号（如 教学楼A302、学生活动中心201、3号楼201）
_LOC_RE = re.compile(
    r"(?:在|地点[：:]?\s*)\s*"
    r"([A-Za-z0-9一-龥\-]*?(?:会议室|教室|中心|校区|食堂|礼堂|操场|楼|室|厅|馆|院)"
    r"[A-Za-z]?[0-9\-]*)"
)
_DATE_WORDS_RE = re.compile(
    r"(?:本|这|下)?(?:周|星期|礼拜)[一二三四五六日天]|明天|后天|今天|昨天|\d{4}[-/年]\d{1,2}[-/月]\d{1,2}[日号]?|\d{1,2}月\d{1,2}[日号]"
)
_TIME_WORDS_RE = re.compile(
    r"\d{1,2}[:：]\d{2}(?:\s*[-~—到至]\s*\d{1,2}[:：]\d{2})?"
    r"|" + _CN_NUM + r"点(?:半|" + _CN_NUM + r"分?)?(?:\s*[-~—到至]\s*" + _CN_NUM + r"点(?:半|" + _CN_NUM + r"分?)?)?"
    r"|" + _PERIOD
)
_MONEY_RE = re.compile(r"[¥￥]\s*(\d+(?:\.\d{1,2})?)|(\d+(?:\.\d{1,2})?)\s*(?:元|块钱|块)")


def _make_title(line: str, loc_match: Optional["re.Match[str]"]) -> str:
    """去掉标签、日期、时间、地点和客套话，只留下“要做什么”。"""
    t = re.sub(r"【.*?】|\[.*?\]", "", line)
    if loc_match:
        t = t.replace(loc_match.group(0), " ")
    t = _DATE_WORDS_RE.sub(" ", t)
    t = _TIME_WORDS_RE.sub(" ", t)
    t = re.sub(r"^\s*(?:各位|亲爱的)?(?:同学们?|老师们?|大家|家人们)好?[，,！!：:]?", "", t)
    segments = [s.strip(" 　") for s in re.split(r"[，,。；;！!\n]", t)]
    for seg in segments:
        seg = re.sub(r"^(?:将|要|会)?(?:进行|举行|举办|召开|开展|参加)", "", seg).strip()
        seg = re.sub(r"\s+", " ", seg)
        if len(seg) >= 2 and not seg.startswith(("请", "务必", "记得")):
            return seg[:40]
    fallback = re.sub(r"【.*?】", "", line).strip()
    return fallback[:40]


def _split_expense_clauses(line: str) -> List[str]:
    """一句话里有多笔钱时按标点拆开，每段一笔。"""
    if len(_MONEY_RE.findall(line)) <= 1:
        return [line]
    parts = [p.strip() for p in re.split(r"[，,；;。、\n]|\s{2,}", line) if p.strip()]
    clauses: List[str] = []
    for p in parts:
        if _MONEY_RE.search(p) or not clauses:
            clauses.append(p)
        else:  # 没有金额的片段并到前一段，作为补充说明
            clauses[-1] += "，" + p
    return clauses


def parse_text_locally(text: str, mode: str = "auto") -> Dict[str, List[Dict[str, Any]]]:
    """免 AI Key 的本地中文规则解析器，方便直接联调与无图文字提取。"""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    events: List[Dict[str, Any]] = []
    expenses: List[Dict[str, Any]] = []

    for line in lines:
        money = _MONEY_RE.search(line)
        has_time = bool(
            re.search(
                r"(\d{1,2}[:：]\d{2}|" + _CN_NUM + r"点|明天|后天|今天|(?:周|星期)[一二三四五六日天]|\d{1,2}月\d{1,2}[日号])",
                line,
            )
        )

        if mode != "calendar" and money:
            line_date = _extract_chinese_date(line)
            for clause in _split_expense_clauses(line):
                for m in _MONEY_RE.finditer(clause):
                    amount = float(m.group(1) or m.group(2))
                    item = clause.replace(m.group(0), "")
                    item = re.sub(r"(今天|昨天|前天|明天|早上|上午|中午|下午|晚上|花了|消费|支付|付了|买了|吃了|喝了)", "", item)
                    item = re.sub(r"[，,。；;：:\s]+", " ", item).strip()
                    item = re.sub(r"^(?:在|又|还)", "", item).strip()
                    has_own_date = bool(_DATE_WORDS_RE.search(clause))
                    expenses.append(
                        {
                            "date": _extract_chinese_date(clause) if has_own_date else line_date,
                            "item": item[:24] or "消费记录",
                            "category": _guess_category(clause) if _guess_category(clause) != "其他" else _guess_category(line),
                            "amount": amount,
                            "note": "本地文本提取",
                        }
                    )

        if mode != "expense":
            loc = _LOC_RE.search(line)
            # 记账的句子常带“今天”“在食堂”，带金额的行只有出现具体钟点时才当成日程
            has_clock = bool(re.search(r"\d{1,2}[:：]\d{2}|" + _CN_NUM + r"点", line))
            is_event = (has_time or loc) if not money else has_clock
            if is_event:
                title = _make_title(line, loc)
                if title:
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
