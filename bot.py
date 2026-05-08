"""
💙 중진교역 특전대 일일보고 텔레그램 봇
- 명령어 없이 양식 텍스트만 올리면 자동 인식/저장
- 최초 등록 불필요 - 첫 보고 시 자동 등록
- 메시지 수정 시 자동 반영
- 같은 날 중복 보고 시 최신 내용으로 덮어쓰기
- 미니앱 완전 제거
"""

import os
import re
import threading
from datetime import datetime, time as dtime
from http.server import HTTPServer, BaseHTTPRequestHandler
import pytz
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes, JobQueue
)
from supabase import create_client, Client

# ── Supabase ──────────────────────────────────────────────
SUPABASE_URL = "https://ybyneniwvtthhuhxarju.supabase.co"
SUPABASE_KEY = os.environ.get(
    "SUPABASE_KEY",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InlieW5lbml3dnR0aGh1aHhhcmp1Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzgxNjAyNDYsImV4cCI6MjA5MzczNjI0Nn0.yYl6kR6oGLFKc9e1yypAmkbXVr7wTu98Ts4m83i3H14"
)

BOT_TOKEN     = os.environ["BOT_TOKEN"]
ADMIN_CHAT_ID = int(os.environ["ADMIN_CHAT_ID"])

KST = pytz.timezone("Asia/Seoul")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ── 설정 조회 ─────────────────────────────────────────────
def get_setting(key, default=None):
    try:
        res = supabase.table("settings").select("value").eq("key", key).execute()
        if res.data:
            return res.data[0]["value"]
    except:
        pass
    return default

def get_group_chat_id():
    val = get_setting("group_chat_id")
    return int(val) if val else 0

def get_topic_id():
    val = get_setting("topic_id")
    return int(val) if val and str(val).strip() else None

def is_holiday(date_str):
    try:
        res = supabase.table("holidays").select("id").eq("date", date_str).execute()
        return len(res.data) > 0
    except:
        return False

def today_str():
    return datetime.now(KST).strftime("%Y-%m-%d")

def is_workday(dt):
    if dt.weekday() >= 6:
        return False
    return not is_holiday(dt.strftime("%Y-%m-%d"))

# ── DB 헬퍼 ───────────────────────────────────────────────
def get_members():
    res = supabase.table("members").select("*").eq("active", True).execute()
    return res.data or []

def auto_register(uid, name):
    """첫 보고 시 자동 등록"""
    try:
        res = supabase.table("members").select("id").eq("telegram_id", uid).execute()
        if not res.data:
            supabase.table("members").insert({
                "telegram_id": uid, "name": name, "active": True
            }).execute()
    except:
        pass

def get_reported_ids(date_str=None):
    ds = date_str or today_str()
    res = supabase.table("reports").select("telegram_id").eq("report_date", ds).execute()
    return {str(r["telegram_id"]) for r in (res.data or [])}

# ── 보고 양식 판단 ────────────────────────────────────────
def is_report_text(text: str) -> bool:
    """발굴 키워드가 있으면 보고 양식으로 판단"""
    return bool(re.search(r"발굴", text))

# ── 보고 파싱 ─────────────────────────────────────────────
def parse_report(text: str) -> dict:
    lines = text.splitlines()

    def extract(pattern):
        for line in lines:
            m = re.search(pattern, line, re.IGNORECASE)
            if m:
                return m
        return None

    def parse_item(pattern):
        m = extract(pattern)
        if not m:
            return 0, ""
        count = int(m.group(1)) if m.group(1).isdigit() else 0
        name = m.group(2).strip() if len(m.groups()) > 1 and m.group(2) else ""
        return count, name

    activity_m = extract(r"(?:전도활동|활동)[:\s]+(.+)")
    activity = activity_m.group(1).strip() if activity_m else "미기재"

    발굴건수, 발굴이름         = parse_item(r"발굴[인도]*[:\s]+(\d+)건?\s*[\(\（]?([^\)\）\n]*)[\)\）]?")
    찾기건수, 찾기이름         = parse_item(r"찾기[인도]*[:\s]+(\d+)건?\s*[\(\（]?([^\)\）\n]*)[\)\）]?")
    합자건수, 합자이름         = parse_item(r"합[자당][한자]?[:\s]+(\d+)건?\s*[\(\（]?([^\)\）\n]*)[\)\）]?")
    섭외인도건수, 섭외인도이름 = parse_item(r"섭외인도[:\s]+(\d+)건?\s*[\(\（]?([^\)\）\n]*)[\)\）]?")
    섭외교사건수, 섭외교사이름 = parse_item(r"섭외교사[:\s]+(\d+)건?\s*[\(\（]?([^\)\）\n]*)[\)\）]?")
    복음방인도건수, 복음방인도이름 = parse_item(r"복음방인도[:\s]+(\d+)건?\s*[\(\（]?([^\)\）\n]*)[\)\）]?")
    복음방교사건수, 복음방교사이름 = parse_item(r"복음방교사[:\s]+(\d+)건?\s*[\(\（]?([^\)\）\n]*)[\)\）]?")

    return dict(
        activity=activity,
        발굴건수=발굴건수, 발굴이름=발굴이름,
        찾기건수=찾기건수, 찾기이름=찾기이름,
        합자건수=합자건수, 합자이름=합자이름,
        섭외인도건수=섭외인도건수, 섭외인도이름=섭외인도이름,
        섭외교사건수=섭외교사건수, 섭외교사이름=섭외교사이름,
        복음방인도건수=복음방인도건수, 복음방인도이름=복음방인도이름,
        복음방교사건수=복음방교사건수, 복음방교사이름=복음방교사이름,
    )

# ── 보고 저장 ─────────────────────────────────────────────
def save_report(uid, name, parsed, raw_text):
    ds = today_str()
    time_str = datetime.now(KST).strftime("%H:%M")
    p = parsed
    supabase.table("reports").upsert({
        "telegram_id": uid, "name": name,
        "report_date": ds, "report_time": time_str,
        "activity": p["activity"],
        "발굴건수": p["발굴건수"], "발굴이름": p["발굴이름"],
        "찾기건수": p["찾기건수"], "찾기이름": p["찾기이름"],
        "합자건수": p["합자건수"], "합자이름": p["합자이름"],
        "섭외인도건수": p["섭외인도건수"], "섭외인도이름": p["섭외인도이름"],
        "섭외교사건수": p["섭외교사건수"], "섭외교사이름": p["섭외교사이름"],
        "복음방인도건수": p["복음방인도건수"], "복음방인도이름": p["복음방인도이름"],
        "복음방교사건수": p["복음방교사건수"], "복음방교사이름": p["복음방교사이름"],
        "raw_text": raw_text,
    }, on_conflict="telegram_id,report_date").execute()
    return ds, time_str

# ── 취합 메시지 ───────────────────────────────────────────
def build_summary(date_str=None):
    ds = date_str or today_str()
    res = supabase.table("reports").select("*").eq("report_date", ds).execute()
    rows = [r for r in (res.data or []) if r.get("telegram_id", 0) != 0]
    if not rows:
        return f"📋 {ds} 보고 없음"

    lines = [
        f"💙 <b>{ds} 특전대 일일 취합 결과</b> 💙\n",
        f"👥 보고 인원: {len(rows)}명\n",
        "─────────────────",
        f"📌 발굴인도: <b>{sum(r.get('발굴건수',0) for r in rows)}건</b>",
        f"📌 찾기인도: <b>{sum(r.get('찾기건수',0) for r in rows)}건</b>",
        f"📌 합자: <b>{sum(r.get('합자건수',0) for r in rows)}건</b>",
        f"📌 섭외인도: <b>{sum(r.get('섭외인도건수',0) for r in rows)}건</b>  |  "
        f"섭외교사: <b>{sum(r.get('섭외교사건수',0) for r in rows)}건</b>",
        f"📌 복음방인도: <b>{sum(r.get('복음방인도건수',0) for r in rows)}건</b>  |  "
        f"복음방교사: <b>{sum(r.get('복음방교사건수',0) for r in rows)}건</b>",
        "─────────────────\n",
        "👤 <b>개인별 보고</b>",
    ]
    for r in rows:
        lines.append(
            f"• {r['name']}  발굴{r.get('발굴건수',0)} / 찾기{r.get('찾기건수',0)} / "
            f"합자{r.get('합자건수',0)} / 섭외{r.get('섭외인도건수',0)} / "
            f"복음방{r.get('복음방인도건수',0)}"
        )

    members = get_members()
    reported = get_reported_ids(ds)
    unreported = [m["name"] for m in members if str(m["telegram_id"]) not in reported]
    if unreported:
        lines.append("\n⚠️ <b>미보고</b>: " + ", ".join(unreported))

    return "\n".join(lines)

# ── 그룹 전송 ─────────────────────────────────────────────
async def send_to_group(bot, text):
    chat_id = get_group_chat_id()
    if not chat_id:
        print("⚠️ group_chat_id 미설정")
        return
    topic_id = get_topic_id()
    kwargs = dict(chat_id=chat_id, text=text, parse_mode="HTML")
    if topic_id:
        kwargs["message_thread_id"] = topic_id
    await bot.send_message(**kwargs)

# ── 보고 처리 공통 ────────────────────────────────────────
async def process_report(message, is_edit: bool = False):
    now = datetime.now(KST)
    user = message.from_user
    uid = user.id
    name = (user.last_name or "") + (user.first_name or user.username or "이름없음")
    text = message.text or ""

    if not is_report_text(text):
        return

    # 마감 체크 (수정은 통과)
    if now.hour >= 21 and not is_edit:
        await message.reply_text(
            "⏰ <b>보고 마감(오후 9시)이 지났습니다.</b>\n내일 올려주세요.",
            parse_mode="HTML"
        )
        return

    # 자동 등록
    auto_register(uid, name)

    # 파싱 & 저장
    parsed = parse_report(text)
    ds, time_str = save_report(uid, name, parsed, text)
    p = parsed

    prefix = "✏️ <b>보고 수정 완료!</b>" if is_edit else "✅ <b>보고 완료!</b>"

    await message.reply_text(
        f"{prefix} ({name} / {time_str})\n\n"
        f"전도활동: {p['activity']}\n"
        f"├ 발굴인도: {p['발굴건수']}건 {p['발굴이름']}\n"
        f"├ 찾기인도: {p['찾기건수']}건 {p['찾기이름']}\n"
        f"├ 합자: {p['합자건수']}건 {p['합자이름']}\n"
        f"├ 섭외인도: {p['섭외인도건수']}건 {p['섭외인도이름']}\n"
        f"├ 섭외교사: {p['섭외교사건수']}건 {p['섭외교사이름']}\n"
        f"├ 복음방인도: {p['복음방인도건수']}건 {p['복음방인도이름']}\n"
        f"└ 복음방교사: {p['복음방교사건수']}건 {p['복음방교사이름']}",
        parse_mode="HTML"
    )

    if any([p['합자건수'], p['섭외인도건수'], p['섭외교사건수'],
            p['복음방인도건수'], p['복음방교사건수']]):
        await message.reply_text(
            "📸 합자 / 섭외 / 복음방 건이 보고되었습니다.\n"
            "‼️ <b>스텝업 촬영본을 함께 올려주세요!</b>",
            parse_mode="HTML"
        )

# ── 메시지 핸들러 ─────────────────────────────────────────
async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await process_report(update.message, is_edit=False)

async def handle_edited(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await process_report(update.edited_message, is_edit=True)

# ── /help ─────────────────────────────────────────────────
async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        if update.effective_chat.type in ("group", "supergroup"):
            await update.message.delete()
    except:
        pass
    await update.message.reply_text(
        "💙 <b>특전대 일일보고 사용법</b>\n\n"
        "명령어 없이 아래 양식대로 올리면 자동 저장됩니다!\n\n"
        "━━━━━━━━━━━━━━━━━\n"
        "<b>📋 보고 양식</b>\n"
        "━━━━━━━━━━━━━━━━━\n"
        "<code>전도활동: 강남역 노방전도\n"
        "발굴인도: 2건 (홍길동, 김철수)\n"
        "찾기인도: 0건\n"
        "합자: 0건\n"
        "섭외인도: 0건\n"
        "섭외교사: 0건\n"
        "복음방인도: 0건\n"
        "복음방교사: 0건</code>\n\n"
        "📌 보고 후 메시지 수정하면 자동 반영\n"
        "📌 여러 번 올리면 마지막 내용으로 저장\n"
        "📌 마감: 오후 9시",
        parse_mode="HTML"
    )

# ── /summary (관리자) ─────────────────────────────────────
async def cmd_summary(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_CHAT_ID:
        return
    try:
        if update.effective_chat.type in ("group", "supergroup"):
            await update.message.delete()
    except:
        pass
    await update.message.reply_text(build_summary(), parse_mode="HTML")

# ── /missing (관리자) ─────────────────────────────────────
async def cmd_unreported(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_CHAT_ID:
        return
    try:
        if update.effective_chat.type in ("group", "supergroup"):
            await update.message.delete()
    except:
        pass
    members = get_members()
    reported = get_reported_ids()
    unreported = [m["name"] for m in members if str(m["telegram_id"]) not in reported]
    msg = ("⚠️ <b>미보고 인원</b>\n\n" + "\n".join(f"• {n}" for n in unreported)
           if unreported else "✅ 모든 구성원 보고 완료!")
    await update.message.reply_text(msg, parse_mode="HTML")

# ── 독려 Job ──────────────────────────────────────────────
async def job_remind(ctx: ContextTypes.DEFAULT_TYPE):
    now = datetime.now(KST)
    if not is_workday(now):
        return
    members = get_members()
    reported = get_reported_ids()
    unreported = [m["name"] for m in members if str(m["telegram_id"]) not in reported]
    if not unreported:
        return
    h, m = now.hour, now.minute
    h12 = h - 12 if h > 12 else h
    label = f"오후 {h12}시" + (f" {m}분" if m else "")
    await send_to_group(
        ctx.bot,
        f"📢 <b>[{label} 보고 독려]</b>\n\n"
        f"미보고: ⚠️ {', '.join(unreported)}\n\n"
        f"오후 9시까지 보고 부탁드립니다! 💪\n"
        f"양식대로 올려주시면 자동 저장됩니다."
    )

# ── 마감 취합 ─────────────────────────────────────────────
async def job_final_summary(ctx: ContextTypes.DEFAULT_TYPE):
    now = datetime.now(KST)
    if not is_workday(now):
        return
    await send_to_group(
        ctx.bot,
        "⏰ <b>보고 마감!</b> 9시 이후 보고는 내일 올려주세요!\n\n"
        + build_summary()
    )

# ── Cloud Run 헬스체크 ────────────────────────────────────
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b"ok")
    def log_message(self, *a): pass

def run_health_server():
    HTTPServer(("0.0.0.0", int(os.environ.get("PORT", 8080))), HealthHandler).serve_forever()

# ── 메인 ─────────────────────────────────────────────────
def main():
    threading.Thread(target=run_health_server, daemon=True).start()
    print(f"🌐 헬스체크 서버 시작 (PORT={os.environ.get('PORT',8080)})")

    app = Application.builder().token(BOT_TOKEN).build()

    # 명령어
    app.add_handler(CommandHandler("start",   cmd_help))
    app.add_handler(CommandHandler("help",    cmd_help))
    app.add_handler(CommandHandler("summary", cmd_summary))
    app.add_handler(CommandHandler("missing", cmd_unreported))

    # 일반 메시지 자동 인식
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        handle_message
    ))

    # 수정된 메시지 자동 반영
    app.add_handler(MessageHandler(
        filters.UpdateType.EDITED_MESSAGE & filters.TEXT,
        handle_edited
    ))

    jq: JobQueue = app.job_queue
    for h in range(15, 19):
        jq.run_daily(job_remind, time=dtime(hour=h, minute=0, tzinfo=KST))
    for h, m in [(19,0),(19,30),(20,0),(20,30)]:
        jq.run_daily(job_remind, time=dtime(hour=h, minute=m, tzinfo=KST))
    jq.run_daily(job_final_summary, time=dtime(hour=21, minute=0, tzinfo=KST))

    print("🤖 봇 시작됨")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
