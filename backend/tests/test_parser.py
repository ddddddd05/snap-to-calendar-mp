"""本地规则解析器（不配 AI Key 时使用）的离线测试。运行：在 backend/ 下执行 python -m pytest"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from parser import _extract_chinese_date, _extract_chinese_time, parse_text_locally  # noqa: E402


def _day(offset: int) -> str:
    return (datetime.now() + timedelta(days=offset)).strftime("%Y-%m-%d")


def _next_weekday(target: int, next_week: bool = False) -> str:
    """target: 1=周一 … 7=周日。与解析器口径一致：本周已过的日子算下周。"""
    diff = target - datetime.now().isoweekday()
    if next_week:
        diff += 7
    elif diff < 0:
        diff += 7
    return _day(diff)


# ---------- 日程 ----------

def test_event_title_is_not_truncated_and_location_keeps_room_number():
    r = parse_text_locally("【教务处通知】本周五 14:00-16:00 在教学楼A302 进行毕业设计开题答辩")
    assert len(r["events"]) == 1
    ev = r["events"][0]
    assert ev["title"] == "毕业设计开题答辩"
    assert ev["location"] == "教学楼A302"
    assert (ev["startTime"], ev["endTime"]) == ("14:00", "16:00")
    assert ev["date"] == _next_weekday(5)
    assert r["expenses"] == []


def test_group_chat_notice_with_greeting_and_reminder():
    text = "同学们好，明天下午 14:30-16:00 在学生活动中心201 举行志愿者培训，请提前15分钟到场签到。"
    ev = parse_text_locally(text)["events"][0]
    assert ev["title"] == "志愿者培训"
    assert ev["location"] == "学生活动中心201"
    assert ev["date"] == _day(1)
    assert (ev["startTime"], ev["endTime"]) == ("14:30", "16:00")


def test_long_title_is_kept_up_to_40_chars():
    text = "明天 9:00 在3号楼201 进行人工智能与大数据技术在智慧城市交通调度中的应用研究中期汇报"
    ev = parse_text_locally(text)["events"][0]
    assert ev["title"].startswith("人工智能与大数据技术")
    assert ev["title"].endswith("中期汇报")
    assert ev["location"] == "3号楼201"


def test_chinese_time_range():
    assert _extract_chinese_time("下午2点到4点半开会") == ("14:00", "16:30")
    assert _extract_chinese_time("晚上七点至九点") == ("19:00", "21:00")
    assert _extract_chinese_time("上午11点到1点") == ("11:00", "13:00")


def test_period_applies_to_digital_time():
    assert _extract_chinese_time("晚上 7:30 开班会") == ("19:30", "20:30")
    assert _extract_chinese_time("下午 2:00-4:00") == ("14:00", "16:00")
    assert _extract_chinese_time("14:00-16:00") == ("14:00", "16:00")


# ---------- 日期 ----------

def test_next_week_adds_seven_days():
    assert _extract_chinese_date("下周五开会") == _next_weekday(5, next_week=True)
    assert _extract_chinese_date("本周五开会") == _next_weekday(5)
    assert _extract_chinese_date("星期三上课") == _next_weekday(3)
    assert _extract_chinese_date("下星期一交作业") == _next_weekday(1, next_week=True)


def test_full_date():
    assert _extract_chinese_date("2026-12-01 期末考试") == "2026-12-01"
    assert _extract_chinese_date("2027年1月5日 返校") == "2027-01-05"


# ---------- 账单 ----------

def test_two_amounts_in_one_sentence_become_two_expenses():
    r = parse_text_locally("今天中午在食堂吃了黄焖鸡 22.5元，晚上买奶茶 18元。", "expense")
    exps = r["expenses"]
    assert [e["amount"] for e in exps] == [22.5, 18.0]
    assert exps[0]["item"] == "食堂黄焖鸡"
    assert "奶茶" in exps[1]["item"] and "黄焖鸡" not in exps[1]["item"]
    assert all(e["category"] == "餐饮" for e in exps)
    assert all(e["date"] == _day(0) for e in exps)
    assert r["events"] == []


def test_yuan_sign_and_kuai():
    exps = parse_text_locally("打车 ¥36，买书 45块", "expense")["expenses"]
    assert [(e["amount"], e["category"]) for e in exps] == [(36.0, "交通"), (45.0, "学习")]


def test_single_expense_line_unchanged():
    exps = parse_text_locally("昨天看电影 59.9元", "expense")["expenses"]
    assert len(exps) == 1
    assert exps[0]["amount"] == 59.9
    assert exps[0]["date"] == _day(-1)
    assert exps[0]["category"] == "娱乐"


def test_auto_mode_mixed_lines():
    text = "【班级通知】明天下午 3:00 在图书馆302 开班会\n今天中午黄焖鸡 22.5元，奶茶 18元"
    r = parse_text_locally(text, "auto")
    assert len(r["events"]) == 1 and r["events"][0]["title"] == "开班会"
    assert [e["amount"] for e in r["expenses"]] == [22.5, 18.0]


def test_expense_with_place_is_not_an_event_in_auto_mode():
    r = parse_text_locally("今天中午在食堂吃了黄焖鸡 22.5元，晚上买奶茶 18元。", "auto")
    assert r["events"] == []
    assert len(r["expenses"]) == 2


def test_calendar_mode_ignores_money():
    r = parse_text_locally("今天中午黄焖鸡 22.5元", "calendar")
    assert r["expenses"] == []
