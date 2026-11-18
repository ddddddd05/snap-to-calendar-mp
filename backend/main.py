import csv
import io
import os
from typing import List, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from parser import call_vision_ai, ocr_image_locally, parse_text_locally

load_dotenv()

app = FastAPI(title="Snap-to-Calendar API", version="1.0.0")

# 允许本地调试与小程序/网页跨域请求
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ExtractRequest(BaseModel):
    text: str = ""
    imageBase64: Optional[str] = None
    mode: str = "auto"  # auto | calendar | expense


class ExpenseItem(BaseModel):
    date: str = ""
    item: str = ""
    category: str = "其他"
    amount: float = 0.0
    note: str = ""


class ExportCsvRequest(BaseModel):
    expenses: List[ExpenseItem]


@app.get("/health")
def health():
    has_key = bool(os.getenv("AI_API_KEY", "").strip())
    return {"status": "ok", "aiConfigured": has_key}


@app.post("/api/extract")
async def extract(req: ExtractRequest):
    text = (req.text or "").strip()
    has_image = bool(req.imageBase64)
    if not text and not has_image:
        raise HTTPException(status_code=400, detail="请至少提供截图或文字内容")

    api_key = os.getenv("AI_API_KEY", "").strip()
    provider = os.getenv("AI_PROVIDER", "openai").strip()
    base_url = os.getenv("AI_BASE_URL", "https://api.openai.com/v1").strip()
    model = os.getenv("AI_MODEL", "gpt-4o-mini").strip()

    if api_key:
        try:
            data = await call_vision_ai(
                text=text,
                image_base64=req.imageBase64,
                mode=req.mode,
                provider=provider,
                base_url=base_url,
                model=model,
                api_key=api_key,
            )
            return {"source": "ai", **data}
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"AI 识别失败: {exc}")

    # 未配置 AI_API_KEY 时：有图先走本地免费 OCR 识图，再结合文本走本地规则解析
    combined_text = text
    ocr_text = ""
    if has_image and req.imageBase64:
        try:
            ocr_text = ocr_image_locally(req.imageBase64)
            combined_text = "\n".join(part for part in [ocr_text, text] if part)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"本地 OCR 识图失败: {exc}")

    if not combined_text.strip():
        raise HTTPException(status_code=400, detail="图片中未识别到有效文字")

    data = parse_text_locally(combined_text, req.mode)
    return {"source": "local-ocr" if ocr_text else "local", "ocrText": ocr_text, **data}


@app.post("/api/export-csv")
def export_csv(req: ExportCsvRequest):
    if not req.expenses:
        raise HTTPException(status_code=400, detail="账单列表为空")

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["日期", "项目/商户", "分类", "金额(元)", "备注"])

    total = 0.0
    for exp in req.expenses:
        total += exp.amount
        writer.writerow([exp.date, exp.item, exp.category, f"{exp.amount:.2f}", exp.note])

    writer.writerow(["合计", f"共 {len(req.expenses)} 笔", "", f"{total:.2f}", ""])

    # 加 UTF-8 BOM 防止 Excel 打开中文乱码
    content_bytes = ("\ufeff" + buf.getvalue()).encode("utf-8")
    return StreamingResponse(
        io.BytesIO(content_bytes),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="expenses.csv"'},
    )
