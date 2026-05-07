"""
💙 중진교역 특전대 일일보고 텔레그램 봇
- Supabase DB 연동
- 보고 접수 / 취합 / 독려 메시지
"""

import os
import re
import asyncio
from datetime import datetime, time, timedelta
import pytz
from telegram import Update, Bot
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes, JobQueue
)
from supabase import create_client, Client

# ── 환경변수 ──────────────────────────────────────────────
BOT_TOKEN      = os.environ["BOT_TOKEN"]
SUPABASE_URL   = os.environ["SUPABASE_URL"]
SUPABASE_KEY   = os.environ["SUPABASE_KEY"]
GROUP_CHAT_ID  = int(os.environ["GROUP_CHAT_ID"])   # 그룹 chat_id (음수)
ADMIN_CHAT_ID  = int(os.environ["ADMIN_CHAT_ID"])   # 관리자 chat_id

KST = pytz.timezone("Asia/Seoul")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ── 요일 체크 (월~토) ─────────────────────────────────────
def is_weekday(dt: datetime) -> bool:
    return dt.weekday() < 6  # 0=월 … 5=토

# ── 날짜 문자열 ───────────────────────────────────────────
def today_str() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d")

# ── 보고 파싱 ─────────────────────────────────────────────
def parse_report(text: str) -> dict | None:
    """
    /report 이후 텍스트를 파싱해 dict 반환.
    발굴인도 항목이 없으면 None 반환(유효하지 않은 보고).
    """
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

    activity_m = extract(r"(?:전도활동|1\.)[:\s]+(.+)")
    activity = activity_m.group(1).strip() if activity_m else "미기재"

    발굴건수, 발굴이름 = parse_item(r"발굴[인도]*[:\s]+(\d+)건?\s*[\(\（]?([^\)\）\n]*)[\)\）]?")
    찾기건수, 찾기이름 = parse_item(r"찾기[인도]*[:\s]+(\d+)건?\s*[\(\（]?([^\)\）\n]*)[\)\）]?")
    합자건수, 합자이름 = parse_item(r"합당[한자]*[:\s]+(\d+)건?\s*[\(\（]?([^\)\）\n]*)[\)\）]?")
    섭외인도건수, 섭외인도이름 = parse_item(r"섭외인도[:\s]+(\d+)건?\s*[\(\（]?([^\)\）\n]*)[\)\）]?")
    섭외교사건수, 섭외교사이름 = parse_item(r"섭외교사[:\s]+(\d+)건?\s*[\(\（]?([^\)\）\n]*)[\)\）]?")
    복음방인도건수, 복음방인도이름 = parse_item(r"복음방인도[:\s]+(\d+)건?\s*[\(\（]?([^\)\）\n]*)[\)\）]?")
    복음방교사건수, 복음방교사이름 = parse_item(r"복음방교사[:\s]+(\d+)건?\s*[\(\（]?([^\)\）\n]*)[\)\）]?")

    # 발굴인도 항목이 있어야 유효
    if extract(r"발굴") is None:
        return None

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

# ── 구성원 조회 ───────────────────────────────────────────
def get_members() -> list[dict]:
    res = supabase.table("members").select("*").eq("active", True).execute()
    return res.data or []

def is_member(user_id: int) -> bool:
    res = supabase.table("members").select("id").eq("telegram_id", user_id).eq("active", True).execute()
    return len(res.data) > 0

# ── 오늘 보고 조회 ────────────────────────────────────────
def get_today_reports() -> list[dict]:
    res = supabase.table("reports").select("*").eq("report_date", today_str()).execute()
    return res.data or []

def get_reported_ids() -> set[int]:
    return {r["telegram_id"] for r in get_today_reports()}

# ── 취합 메시지 생성 ──────────────────────────────────────
def build_summary(date_str: str | None = None) -> str:
    ds = date_str or today_str()
    res = supabase.table("reports").select("*").eq("report_date", ds).execute()
    rows = res.data or []

    if not rows:
        return f"📋 {ds} 보고 없음"

    총발굴 = sum(r.get("발굴건수", 0) for r in rows)
    총찾기 = sum(r.get("찾기건수", 0) for r in rows)
    총합자 = sum(r.get("합자건수", 0) for r in rows)
    총섭외인도 = sum(r.get("섭외인도건수", 0) for r in rows)
    총섭외교사 = sum(r.get("섭외교사건수", 0) for r in rows)
    총복음방인도 = sum(r.get("복음방인도건수", 0) for r in rows)
    총복음방교사 = sum(r.get("복음방교사건수", 0) for r in rows)

    lines = [f"💙 <b>{ds} 특전대 일일 취합 결과</b> 💙\n"]
    lines.append(f"👥 보고 인원: {len(rows)}명\n")
    lines.append("─────────────────")
    lines.append(f"📌 발굴인도: <b>{총발굴}건</b>")
    lines.append(f"📌 찾기인도: <b>{총찾기}건</b>")
    lines.append(f"📌 합자: <b>{총합자}건</b>")
    lines.append(f"📌 섭외인도: <b>{총섭외인도}건</b>  |  섭외교사: <b>{총섭외교사}건</b>")
    lines.append(f"📌 복음방인도: <b>{총복음방인도}건</b>  |  복음방교사: <b>{총복음방교사}건</b>")
    lines.append("─────────────────")

    # 개인별 한 줄 요약
    lines.append("\n👤 <b>개인별 보고</b>")
    for r in rows:
        lines.append(
            f"• {r['name']}  발굴{r.get('발굴건수',0)} / 찾기{r.get('찾기건수',0)} / "
            f"합자{r.get('합자건수',0)} / 섭외{r.get('섭외인도건수',0)} / "
            f"복음방{r.get('복음방인도건수',0)}"
        )

    # 미보고자
    members = get_members()
    reported_ids = {r["telegram_id"] for r in rows}
    unreported = [m["name"] for m in members if m["telegram_id"] not in reported_ids]
    if unreported:
        lines.append("\n⚠️ <b>미보고</b>: " + ", ".join(unreported))

    return "\n".join(lines)

# ── /register ─────────────────────────────────────────────────
async def cmd_register(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != GROUP_CHAT_ID:
        await update.message.reply_text("⚠️ 특전대 그룹 채팅방에서 등록해주세요.")
        return

    user = update.effective_user
    uid = user.id
    name = (user.last_name or "") + (user.first_name or user.username or "이름없음")

    if is_member(uid):
        await update.message.reply_text(f"✅ <b>{name}</b>님은 이미 등록되어 있습니다.", parse_mode="HTML")
        return

    supabase.table("members").insert({"telegram_id": uid, "name": name, "active": True}).execute()
    await update.message.reply_text(
        f"🎉 <b>{name}</b>님 등록 완료!\n\n"
        "보고는 아래 양식으로 보내주세요:\n\n"
        "<code>/report\n"
        "전도활동: (내용)\n"
        "발굴인도: 0건 (이름)\n"
        "찾기인도: 0건 (이름)\n"
        "합자: 0건 (이름)\n"
        "섭외인도: 0건 (이름)\n"
        "섭외교사: 0건 (이름)\n"
        "복음방인도: 0건 (이름)\n"
        "복음방교사: 0건 (이름)</code>",
        parse_mode="HTML"
    )

# ── /report ─────────────────────────────────────────────────
async def cmd_report(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != GROUP_CHAT_ID:
        await update.message.reply_text("⚠️ 특전대 그룹 채팅방에서 보고해주세요.")
        return

    now = datetime.now(KST)
    user = update.effective_user
    uid = user.id
    name = (user.last_name or "") + (user.first_name or user.username or "이름없음")

    # 마감 체크
    if now.hour >= 21:
        await update.message.reply_text(
            "⏰ <b>보고 마감(오후 9시)이 지났습니다.</b>\n내일 보고란에 올려주세요.",
            parse_mode="HTML"
        )
        return

    # 구성원 체크
    if not is_member(uid):
        await update.message.reply_text("⚠️ 먼저 <code>/register</code> 명령어로 등록해주세요.", parse_mode="HTML")
        return

    # 파싱
    text = update.message.text or ""
    parsed = parse_report(text)
    if parsed is None:
        await update.message.reply_text(
            "❌ 보고 양식이 올바르지 않습니다.\n\n"
            "<code>/report\n"
            "전도활동: (내용)\n"
            "발굴인도: 0건 (이름)\n"
            "찾기인도: 0건 (이름)\n"
            "합자: 0건 (이름)\n"
            "섭외인도: 0건 (이름)\n"
            "섭외교사: 0건 (이름)\n"
            "복음방인도: 0건 (이름)\n"
            "복음방교사: 0건 (이름)</code>",
            parse_mode="HTML"
        )
        return

    ds = today_str()
    time_str = now.strftime("%H:%M")

    # upsert (같은 날 같은 사람은 덮어쓰기)
    supabase.table("reports").upsert({
        "telegram_id": uid,
        "name": name,
        "report_date": ds,
        "report_time": time_str,
        "activity": parsed["activity"],
        "발굴건수": parsed["발굴건수"],
        "발굴이름": parsed["발굴이름"],
        "찾기건수": parsed["찾기건수"],
        "찾기이름": parsed["찾기이름"],
        "합자건수": parsed["합자건수"],
        "합자이름": parsed["합자이름"],
        "섭외인도건수": parsed["섭외인도건수"],
        "섭외인도이름": parsed["섭외인도이름"],
        "섭외교사건수": parsed["섭외교사건수"],
        "섭외교사이름": parsed["섭외교사이름"],
        "복음방인도건수": parsed["복음방인도건수"],
        "복음방인도이름": parsed["복음방인도이름"],
        "복음방교사건수": parsed["복음방교사건수"],
        "복음방교사이름": parsed["복음방교사이름"],
        "raw_text": text,
    }, on_conflict="telegram_id,report_date").execute()

    # 확인 메시지
    p = parsed
    msg = (
        f"✅ <b>{name}</b>님 보고 완료! ({time_str})\n\n"
        f"전도활동: {p['activity']}\n"
        f"├ 발굴인도: {p['발굴건수']}건 {p['발굴이름']}\n"
        f"├ 찾기인도: {p['찾기건수']}건 {p['찾기이름']}\n"
        f"├ 합자: {p['합자건수']}건 {p['합자이름']}\n"
        f"├ 섭외인도: {p['섭외인도건수']}건 {p['섭외인도이름']}\n"
        f"├ 섭외교사: {p['섭외교사건수']}건 {p['섭외교사이름']}\n"
        f"├ 복음방인도: {p['복음방인도건수']}건 {p['복음방인도이름']}\n"
        f"└ 복음방교사: {p['복음방교사건수']}건 {p['복음방교사이름']}"
    )
    await update.message.reply_text(msg, parse_mode="HTML")

    # 스텝업 안내
    if any([p['합자건수'], p['섭외인도건수'], p['섭외교사건수'], p['복음방인도건수'], p['복음방교사건수']]):
        await update.message.reply_text(
            "📸 <b>스텝업 촬영 안내</b>\n\n"
            "합자 / 섭외인도 / 섭외교사 / 복음방인도 / 복음방교사 건이 보고되었습니다.\n\n"
            "‼️ <b>스텝업 촬영본을 함께 올려주세요!</b>",
            parse_mode="HTML"
        )

# ── /summary (관리자) ────────────────────────────────────────
async def cmd_summary(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_CHAT_ID:
        return
    await update.message.reply_text(build_summary(), parse_mode="HTML")

# ── /missing (관리자) ──────────────────────────────────────
async def cmd_unreported(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_CHAT_ID:
        return
    members = get_members()
    reported = get_reported_ids()
    unreported = [m["name"] for m in members if m["telegram_id"] not in reported]
    if unreported:
        msg = "⚠️ <b>미보고 인원</b>\n\n" + "\n".join(f"• {n}" for n in unreported)
    else:
        msg = "✅ 모든 구성원이 보고 완료했습니다!"
    await update.message.reply_text(msg, parse_mode="HTML")

# ── /help ───────────────────────────────────────────────
async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "💙 <b>특전대 일일보고 봇 명령어</b>\n\n"
        "/register — 구성원 등록 (최초 1회)\n"
        "/report — 일일보고 제출\n"
        "/help — 이 메시지\n\n"
        "<b>관리자 전용</b>\n"
        "/summary — 오늘 보고 전체 취합\n"
        "/missing — 미보고 인원 확인",
        parse_mode="HTML"
    )

# ── 예약 메시지 Jobs ──────────────────────────────────────
async def job_remind(ctx: ContextTypes.DEFAULT_TYPE):
    now = datetime.now(KST)
    if not is_weekday(now):
        return

    reported = get_reported_ids()
    members = get_members()
    unreported = [m["name"] for m in members if m["telegram_id"] not in reported]

    if not unreported:
        return

    hour = now.hour
    if 15 <= hour < 19:
        label = f"오후 {hour}시"
    elif hour == 19:
        label = "오후 7시"
    else:
        label = now.strftime("%H:%M")

    names_str = ", ".join(unreported)
    await ctx.bot.send_message(
        chat_id=GROUP_CHAT_ID,
        text=(
            f"📢 <b>[{label} 보고 독려]</b>\n\n"
            f"아직 보고 미완료 인원입니다:\n"
            f"⚠️ {names_str}\n\n"
            f"오후 9시까지 보고 부탁드립니다! 💪\n"
            f"(<code>/report</code> 명령어 사용)"
        ),
        parse_mode="HTML"
    )

async def job_final_summary(ctx: ContextTypes.DEFAULT_TYPE):
    """오후 9시 - 최종 취합"""
    now = datetime.now(KST)
    if not is_weekday(now):
        return
    await ctx.bot.send_message(
        chat_id=GROUP_CHAT_ID,
        text="⏰ <b>보고 마감되었습니다.</b>\n9시 이후 보고는 내일 올려주세요!\n\n" + build_summary(),
        parse_mode="HTML"
    )

# ── Cloud Run 헬스체크용 HTTP 서버 ───────────────────────
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")
    def log_message(self, *args):
        pass  # 로그 출력 억제

def run_health_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    server.serve_forever()

# ── 메인 ─────────────────────────────────────────────────
def main():
    # Cloud Run 헬스체크 서버를 백그라운드 스레드로 실행
    t = threading.Thread(target=run_health_server, daemon=True)
    t.start()
    print(f"🌐 헬스체크 서버 시작됨 (PORT={os.environ.get('PORT', 8080)})")

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("register", cmd_register))
    app.add_handler(CommandHandler("report", cmd_report))
    app.add_handler(CommandHandler("summary", cmd_summary))
    app.add_handler(CommandHandler("missing", cmd_unreported))
    app.add_handler(CommandHandler("help", cmd_help))

    jq: JobQueue = app.job_queue

    # 오후 3~6시 매 정시 독려 (1시간 단위)
    for h in range(15, 19):
        jq.run_daily(job_remind, time=time(hour=h, minute=0, tzinfo=KST))

    # 오후 7시~8시 30분 단위 독려
    for h, m in [(19, 0), (19, 30), (20, 0), (20, 30)]:
        jq.run_daily(job_remind, time=time(hour=h, minute=m, tzinfo=KST))

    # 오후 9시 최종 취합
    jq.run_daily(job_final_summary, time=time(hour=21, minute=0, tzinfo=KST))

    print("🤖 봇 시작됨")
    app.run_polling()

if __name__ == "__main__":
    main()
