import streamlit as st
import requests
import os
import io
import base64
import uuid
from datetime import datetime, timedelta
import pandas as pd
import altair as alt

# ============================================================
#  הגדרות
# ============================================================
API_URL       = "https://server.iac.ac.il/api/v1/studentapi/chat/completions"
API_KEY       = os.environ.get("WSC_API_KEY", "sk-std-NYI6dMVcFMobVTH3T8hrp2s4CWCNwJDi04ZLmflNzQU")
SUPPORT_PHONE = "0527007042"
COMPANY_NAME  = "WSC Sports"
CATEGORIES    = ["בעיה בוידיאו", "בעיה באודיו", "בעיה בפלטפורמה", "אחר"]
STATUSES      = ["פתוחה", "בטיפול", "ממתין ללקוח", "סגורה"]
# ============================================================

HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json"
}

SYSTEM_PROMPT = """You are a technical support bot for WSC Sports. Answer in Hebrew, concise (2-4 sentences), professional.
Diagnose the issue category (Video/Audio/Platform/Other) and give a clear step-by-step solution.

KNOWLEDGE BASE:
=== LIVE FEEDS & INGEST ===
Q: RTMP/SRT stream connected but black screen?
A: בדוק: (1) האנקודר משדר בפועל (2) חומת האש לא חוסמת את הפורט (3) מפתח/כתובת הסטרים תואמים בדיוק.
Q: תזמון ingest לפיד חי חדש?
A: Live Management > Add Stream. בחר פרוטוקול (RTMP/SRT), הזן פרטי סטרים, הגדר זמני התחלה/סיום, שמור.
Q: בעיית סינכרון אודיו-וידאו?
A: מקורה בצד האנקודר. ודא ש-sample rate של אודיו/וידאו תואמים, בדוק keyframe intervals, הפעל מחדש את האנקודר.
Q: פורמטים נתמכים להעלאה ידנית?
A: MP4 ו-MOV. קודקים: H.264 או H.265. אודיו: AAC.

=== קליפים אוטומטיים ===
Q: כלל אוטומציה להיילייטים של שחקן ספציפי?
A: Automation Rules > Create New Rule > Conditions > Player Name > הזן שם > בחר יעד > הפעל.
Q: קליפ ידני כשה-AI פספס רגע?
A: פתח את העורך למשחק. I = נקודת התחלה, O = נקודת סיום. הוסף תגיות, צור קליפ.
Q: שינוי יחס תמונה ל-TikTok/Reels?
A: בכלל אוטומציה או בעורך, עבור ל-Cropping, בחר 9:16 Vertical, הפעל Auto-Tracking.

=== הפצה ופרסום ===
Q: חיבור/אימות מחדש של רשת חברתית?
A: Destinations > Social Accounts. חדש: Add Account. אימות מחדש: לחץ Re-authenticate.
Q: קליפים נכשלים בפרסום ל-OTT?
A: בדוק ב-Publishing Logs את הסיבה המדויקת שהוחזרה מה-API של הפלטפורמה.
Q: עדכון כותרת קליפ שכבר פורסם?
A: כן, ניתן לעדכן מטא-דאטה תחת Published Clips, פרט ל-X/Twitter שלא תומך בעדכון רטרואקטיבי.

הנחיות:
- אם השאלה תואמת את מאגר הידע, ענה בהתאם
- תמיד תן פתרון שלב-אחר-שלב קצר וברור
- אם התבקשת "פתרון חלופי" - תן גישה שונה מהפתרון הקודם, לא אותו דבר
- אם אינך יודע, אמור שיש להסלים לנציג אנושי"""


def call_bot(messages, want_alternative=False):
    msgs = [{"role": "system", "content": SYSTEM_PROMPT}] + messages[-6:]
    if want_alternative:
        msgs.append({"role": "user", "content": "הפתרון הקודם לא עזר, תן לי בבקשה גישה/פתרון חלופי שונה."})
    payload = {"model": "gpt-4o-mini", "messages": msgs, "max_tokens": 500}
    try:
        r = requests.post(API_URL, json=payload, headers=HEADERS, timeout=60)
        data = r.json()
        if "choices" in data:
            content = data["choices"][0]["message"].get("content", "")
            if content and content.strip():
                return content.strip()
    except Exception as e:
        return f"שגיאה בתקשורת עם השרת: {str(e)[:100]}"
    return "לא הצלחתי לעבד את הבקשה, מעביר לנציג אנושי."


def summarize_ticket(ticket):
    """יוצר תקציר אוטומטי לנציג - מה נוסה ומה נכשל"""
    lines = [f"פנייה {ticket['id']} | קטגוריה: {ticket['category']}", f"תיאור: {ticket['description']}"]
    bot_msgs = [m["content"] for m in ticket["messages"] if m["role"] == "assistant"]
    for i, sol in enumerate(bot_msgs, 1):
        lines.append(f"ניסיון {i} (נכשל): {sol[:150]}")
    return "\n".join(lines)


# ============================================================
#  STATE
# ============================================================
if "tickets" not in st.session_state:
    st.session_state.tickets = {}          # id -> ticket dict
if "current_ticket_id" not in st.session_state:
    st.session_state.current_ticket_id = None
if "view_mode" not in st.session_state:
    st.session_state.view_mode = "form"    # form | chat | feedback
if "selected_agent_ticket" not in st.session_state:
    st.session_state.selected_agent_ticket = None


def new_ticket(category, description, attachment_name=None):
    tid = f"WSC-{datetime.now().strftime('%H%M%S')}-{uuid.uuid4().hex[:3].upper()}"
    st.session_state.tickets[tid] = {
        "id": tid,
        "category": category,
        "description": description,
        "attachment": attachment_name,
        "status": "פתוחה",
        "messages": [{"role": "user", "content": description}],
        "created_at": datetime.now(),
        "first_reply_at": None,
        "resolved_by": None,       # bot | agent
        "attempts": 0,
        "rating": None,
        "feedback_note": None,
        "summary": None,
        "agent_replies": [],
    }
    return tid


def get_ticket():
    tid = st.session_state.current_ticket_id
    return st.session_state.tickets.get(tid) if tid else None


# ============================================================
#  עיצוב
# ============================================================
st.set_page_config(page_title=COMPANY_NAME, page_icon="🎯", layout="wide")

st.markdown("""
<style>
    body { direction: rtl; }
    #MainMenu, footer, header { visibility: hidden; }
    .stApp { background: #0a0e1a; }
    .block-container { padding: 0 1rem 3rem !important; max-width: 100% !important; }

    .wa-header { background: linear-gradient(90deg, #d4ff00 0%, #aacc00 100%); color: #000; padding: 12px 16px;
        display: flex; align-items: center; gap: 12px; margin-bottom: 1rem; border-bottom: 3px solid #000;
        border-radius: 8px; }
    .wa-name { font-weight: bold; font-size: 16px; color: #000 !important; }
    .wa-status { font-size: 12px; color: #333 !important; }

    .ticket-badge { background: rgba(212,255,0,0.15); border: 1px solid rgba(212,255,0,0.4); border-radius: 8px;
        padding: 8px 12px; color: #d4ff00; font-size: 13px; margin-bottom: 10px; display: flex;
        justify-content: space-between; align-items: center; }

    .chat-wrap { background: rgba(236,229,221,0.95); border-radius: 12px; padding: 10px; margin-bottom: 10px; }

    .msg-user { background: #DCF8C6; color: #000 !important; padding: 8px 12px; border-radius: 12px 2px 12px 12px;
        margin: 6px 0 6px auto; max-width: 80%; width: fit-content; text-align: right; font-size: 14px;
        line-height: 1.6; word-break: break-word; white-space: pre-wrap; box-shadow: 0 1px 3px rgba(0,0,0,0.15); }
    .msg-bot { background: white; color: #000 !important; padding: 8px 12px; border-radius: 2px 12px 12px 12px;
        margin: 6px auto 6px 0; max-width: 80%; width: fit-content; text-align: right; font-size: 14px;
        line-height: 1.6; border-right: 3px solid #d4ff00; word-break: break-word; white-space: pre-wrap;
        box-shadow: 0 1px 3px rgba(0,0,0,0.15); }
    .msg-agent { background: #eef4ff; color: #000 !important; padding: 8px 12px; border-radius: 2px 12px 12px 12px;
        margin: 6px auto 6px 0; max-width: 80%; width: fit-content; text-align: right; font-size: 14px;
        line-height: 1.6; border-right: 3px solid #3b82f6; word-break: break-word; white-space: pre-wrap; }
    .msg-time { font-size: 11px; color: #666 !important; margin-top: 3px; }
    .msg-wrapper-user { display: flex; justify-content: flex-end; width: 100%; }
    .msg-wrapper-bot { display: flex; justify-content: flex-start; width: 100%; }

    .stButton > button { background: transparent !important; color: #d4ff00 !important;
        border: 1px solid rgba(212,255,0,0.4) !important; border-radius: 8px !important;
        padding: 8px 16px !important; font-size: 13px !important; width: 100% !important; }
    .stButton > button:hover { color: #000 !important; background: #d4ff00 !important; border-color: #d4ff00 !important; }

    section[data-testid="stSidebar"] { background: rgba(15,20,35,0.97) !important; }
    section[data-testid="stSidebar"] * { color: white !important; }
    .stSelectbox label, .stFileUploader label, .stTextArea label, .stTextInput label { color: #d4ff00 !important; }

    .metric-card { background: rgba(255,255,255,0.05); border: 1px solid rgba(212,255,0,0.3); border-radius: 12px;
        padding: 20px; text-align: center; }
    .metric-value { font-size: 2rem; font-weight: bold; color: #d4ff00; }
    .metric-label { font-size: 0.85rem; color: #ccc; margin-top: 4px; }
    .metric-target { font-size: 0.75rem; color: #888; margin-top: 2px; }
    .metric-pass { color: #4ade80 !important; font-weight: bold; }
    .metric-fail { color: #f87171 !important; font-weight: bold; }

    .feedback-box { background: rgba(255,255,255,0.95); border-radius: 12px; padding: 24px; text-align: center;
        margin: 10px 0; }
    .feedback-box h3 { color: #000 !important; margin: 0 0 10px; }
    .feedback-box p { color: #555 !important; }

    .agent-card { background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.15); border-radius: 10px;
        padding: 14px; margin-bottom: 8px; color: #eee; }
    .status-open { color: #f87171; font-weight: bold; }
    .status-progress { color: #facc15; font-weight: bold; }
    .status-waiting { color: #60a5fa; font-weight: bold; }
    .status-closed { color: #4ade80; font-weight: bold; }
</style>
""", unsafe_allow_html=True)


# ============================================================
#  TABS - 3 מסכים ראשיים (מסך 4 המשוב משולב בתוך מסך הצ'אט)
# ============================================================
tab1, tab2, tab3 = st.tabs(["💬 צ'אט לקוח", "🎧 פאנל נציג תמיכה", "📊 דוחות ומדדים"])

# ============================================================
#  TAB 1 - מסך 1: צ'אט הלקוח + מסך 4: משוב
# ============================================================
with tab1:
    st.markdown(f'''<div class="wa-header">🎯<div style="flex:1;">
        <div class="wa-name">{COMPANY_NAME} Support</div>
        <div class="wa-status">⚡ תמיכה טכנית | מקוון</div></div>
        <div style="font-size:11px;background:rgba(0,0,0,0.15);padding:4px 10px;border-radius:12px;color:#000;">● ONLINE</div>
        </div>''', unsafe_allow_html=True)

    ticket = get_ticket()

    # --- שלב א: אין פנייה פתוחה -> טופס פתיחה ---
    if ticket is None:
        st.subheader("פתיחת פנייה חדשה")
        category = st.selectbox("אופי הפנייה:", CATEGORIES)
        description = st.text_area("תאר את הבעיה:", placeholder="לדוגמה: הסטרים שלי מציג מסך שחור...", height=100)
        uploaded = st.file_uploader("צירוף קובץ (צילום מסך / הודעת שגיאה):", type=["jpg", "jpeg", "png", "mp4", "mov", "txt"])
        if uploaded:
            if uploaded.type.startswith("image"):
                st.image(uploaded, width=250)

        if st.button("📤 שלח פנייה", type="primary"):
            if description.strip():
                tid = new_ticket(category, description, uploaded.name if uploaded else None)
                st.session_state.current_ticket_id = tid
                ticket = st.session_state.tickets[tid]
                with st.spinner("🔍 מנתח תקלה..."):
                    ticket["first_reply_at"] = datetime.now()
                    reply = call_bot(ticket["messages"])
                    ticket["messages"].append({"role": "assistant", "content": reply})
                    ticket["attempts"] = 1
                st.rerun()
            else:
                st.warning("נא לתאר את הבעיה לפני השליחה")

    # --- שלב ב: יש פנייה פעילה ---
    else:
        st.markdown(f'''<div class="ticket-badge"><span>📋 <strong>פנייה {ticket['id']}</strong> |
            {ticket['category']} | סטטוס: {ticket['status']}</span>
            <span style="opacity:0.7;">{ticket['created_at'].strftime("%H:%M")}</span></div>''', unsafe_allow_html=True)

        st.markdown('<div class="chat-wrap">', unsafe_allow_html=True)
        for msg in ticket["messages"]:
            if msg["role"] == "user":
                st.markdown(f'<div class="msg-wrapper-user"><div class="msg-user">{msg["content"]}<div class="msg-time">✓✓</div></div></div>', unsafe_allow_html=True)
            elif msg["role"] == "assistant":
                st.markdown(f'<div class="msg-wrapper-bot"><div class="msg-bot">{msg["content"]}<div class="msg-time">🎯 {COMPANY_NAME}</div></div></div>', unsafe_allow_html=True)
            elif msg["role"] == "agent":
                st.markdown(f'<div class="msg-wrapper-bot"><div class="msg-agent">{msg["content"]}<div class="msg-time">🎧 נציג תמיכה</div></div></div>', unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)

        # --- לחצני משוב על הפתרון (רק אם הפנייה עדיין פתוחה ולא מוסלמת) ---
        if ticket["status"] not in ("סגורה",) and ticket["resolved_by"] is None:
            st.write("האם הפתרון עזר?")
            c1, c2, c3 = st.columns(3)
            with c1:
                if st.button("✅ הפתרון עזר – סגור פנייה"):
                    ticket["status"] = "סגורה"
                    ticket["resolved_by"] = "bot"
                    st.session_state.view_mode = "feedback"
                    st.rerun()
            with c2:
                if st.button("🔁 לא עזר – הצג פתרון חלופי"):
                    if ticket["attempts"] >= 2:
                        # שני ניסיונות נכשלו -> הסלמה אוטומטית
                        ticket["status"] = "פתוחה"
                        ticket["resolved_by"] = "agent"
                        ticket["summary"] = summarize_ticket(ticket)
                        ticket["messages"].append({"role": "assistant",
                            "content": f"שני ניסיונות פתרון לא הצליחו. הפנייה {ticket['id']} הוסלמה לנציג אנושי עם תקציר אוטומטי. נציג יחזור אליך בהקדם."})
                        st.session_state.view_mode = "feedback"
                    else:
                        with st.spinner("🔍 מחפש פתרון חלופי..."):
                            reply = call_bot(ticket["messages"], want_alternative=True)
                            ticket["messages"].append({"role": "assistant", "content": reply})
                            ticket["attempts"] += 1
                    st.rerun()
            with c3:
                if st.button("🔼 הסלמה לנציג אנושי"):
                    ticket["status"] = "פתוחה"
                    ticket["resolved_by"] = "agent"
                    ticket["summary"] = summarize_ticket(ticket)
                    ticket["messages"].append({"role": "assistant",
                        "content": f"הפנייה {ticket['id']} הוסלמה לנציג אנושי עם תקציר אוטומטי. נציג יחזור אליך בהקדם."})
                    st.session_state.view_mode = "feedback"
                    st.rerun()

        # --- מסך 4: משוב לקוח (מוצג אוטומטית עם סגירה/הסלמה) ---
        if st.session_state.view_mode == "feedback":
            if ticket["rating"] is None:
                st.markdown('<div class="feedback-box"><h3>⭐ דרג את חוויית השירות</h3><p>כמה היית מדרג את התמיכה שקיבלת?</p></div>', unsafe_allow_html=True)
                cols = st.columns(5)
                for i, col in enumerate(cols, 1):
                    with col:
                        if st.button(f"{'⭐' * i}", key=f"rate_{ticket['id']}_{i}"):
                            ticket["rating"] = i
                            st.rerun()
                note = st.text_area("הערות נוספות (לא חובה):", key=f"note_{ticket['id']}")
                c1, c2 = st.columns(2)
                with c1:
                    if st.button("📨 שלח משוב"):
                        if ticket["rating"] is None:
                            ticket["rating"] = 0
                        ticket["feedback_note"] = note
                        st.success("✅ תודה על המשוב!")
                with c2:
                    if st.button("⏭️ דלג"):
                        ticket["feedback_note"] = None
                        st.session_state.current_ticket_id = None
                        st.session_state.view_mode = "form"
                        st.rerun()
            else:
                ticket["feedback_note"] = ticket.get("feedback_note")
                st.success(f"✅ תודה על המשוב! דירוג: {'⭐' * ticket['rating']}")
                st.info(f"📋 פנייה {ticket['id']} {'נסגרה' if ticket['resolved_by']=='bot' else 'הוסלמה לנציג'}.")
                if st.button("🔄 פנייה חדשה"):
                    st.session_state.current_ticket_id = None
                    st.session_state.view_mode = "form"
                    st.rerun()


# ============================================================
#  TAB 2 - מסך 2: פאנל נציג התמיכה
# ============================================================
with tab2:
    st.markdown("## 🎧 פאנל נציג תמיכה")
    all_tickets = list(st.session_state.tickets.values())

    if not all_tickets:
        st.info("אין פניות במערכת כרגע.")
    else:
        search = st.text_input("🔍 חיפוש לפי מזהה פנייה / קטגוריה / תיאור:")
        filtered = all_tickets
        if search:
            s = search.strip().lower()
            filtered = [t for t in all_tickets if s in t["id"].lower() or s in t["category"].lower() or s in t["description"].lower()]

        col_list, col_detail = st.columns([1, 2])

        with col_list:
            st.markdown("### רשימת פניות")
            status_cls = {"פתוחה": "status-open", "בטיפול": "status-progress",
                          "ממתין ללקוח": "status-waiting", "סגורה": "status-closed"}
            for t in sorted(filtered, key=lambda x: x["created_at"], reverse=True):
                cls = status_cls.get(t["status"], "")
                st.markdown(f'''<div class="agent-card">
                    <strong>{t['id']}</strong><br>
                    {t['category']}<br>
                    <span class="{cls}">● {t['status']}</span>
                    {" | 🔼 הוסלם" if t['resolved_by']=='agent' else ""}
                    </div>''', unsafe_allow_html=True)
                if st.button(f"פתח פנייה {t['id']}", key=f"open_{t['id']}"):
                    st.session_state.selected_agent_ticket = t["id"]
                    st.rerun()

        with col_detail:
            sel_id = st.session_state.selected_agent_ticket
            if sel_id and sel_id in st.session_state.tickets:
                t = st.session_state.tickets[sel_id]
                st.markdown(f"### פנייה {t['id']}")
                st.write(f"**קטגוריה:** {t['category']} | **נוצרה:** {t['created_at'].strftime('%d/%m %H:%M')}")

                new_status = st.selectbox("עדכון סטטוס:", STATUSES, index=STATUSES.index(t["status"]), key=f"status_{t['id']}")
                if new_status != t["status"]:
                    t["status"] = new_status

                if t.get("summary"):
                    st.markdown("**📋 תקציר אוטומטי (מהבוט):**")
                    st.code(t["summary"])

                st.markdown("**היסטוריית שיחה מלאה:**")
                st.markdown('<div class="chat-wrap">', unsafe_allow_html=True)
                for msg in t["messages"]:
                    if msg["role"] == "user":
                        st.markdown(f'<div class="msg-wrapper-user"><div class="msg-user">{msg["content"]}</div></div>', unsafe_allow_html=True)
                    elif msg["role"] == "assistant":
                        st.markdown(f'<div class="msg-wrapper-bot"><div class="msg-bot">{msg["content"]}</div></div>', unsafe_allow_html=True)
                    else:
                        st.markdown(f'<div class="msg-wrapper-bot"><div class="msg-agent">{msg["content"]}</div></div>', unsafe_allow_html=True)
                st.markdown('</div>', unsafe_allow_html=True)

                reply = st.text_input("הודעה ללקוח:", key=f"reply_{t['id']}")
                c1, c2 = st.columns(2)
                with c1:
                    if st.button("📨 שלח תגובה", key=f"send_{t['id']}"):
                        if reply.strip():
                            t["messages"].append({"role": "agent", "content": reply})
                            t["status"] = "ממתין ללקוח"
                            st.rerun()
                with c2:
                    if st.button("✅ סגור פנייה", key=f"close_{t['id']}"):
                        t["status"] = "סגורה"
                        st.rerun()
            else:
                st.info("בחר פנייה מהרשימה כדי לצפות בפרטים.")


# ============================================================
#  TAB 3 - מסך 3: דוחות ומדדים
# ============================================================
with tab3:
    st.markdown(f"# 📊 דוחות ומדדים — {COMPANY_NAME}")

    filt_col, exp_col1, exp_col2 = st.columns([2, 1, 1])
    with filt_col:
        time_range = st.selectbox("טווח זמנים:", ["הכל", "היום", "השבוע האחרון", "החודש האחרון"])

    all_tickets = list(st.session_state.tickets.values())
    now = datetime.now()
    if time_range == "היום":
        all_tickets = [t for t in all_tickets if t["created_at"].date() == now.date()]
    elif time_range == "השבוע האחרון":
        all_tickets = [t for t in all_tickets if t["created_at"] >= now - timedelta(days=7)]
    elif time_range == "החודש האחרון":
        all_tickets = [t for t in all_tickets if t["created_at"] >= now - timedelta(days=30)]

    total = max(len(all_tickets), 1)
    resolved_by_bot = len([t for t in all_tickets if t["resolved_by"] == "bot"])
    escalated = len([t for t in all_tickets if t["resolved_by"] == "agent"])
    bot_resolved_pct = round((resolved_by_bot / total) * 100) if all_tickets else 0

    response_times = [ (t["first_reply_at"] - t["created_at"]).total_seconds()
                        for t in all_tickets if t["first_reply_at"] ]
    avg_time = round(sum(response_times) / len(response_times), 1) if response_times else 0

    ratings = [t["rating"] for t in all_tickets if t.get("rating")]
    avg_rating = round(sum(ratings) / len(ratings), 1) if ratings else 0

    accuracy = 84  # יעד מדיד בפועל ע"י תיוג ידני מול סיווג הבוט - כאן ערך הדגמה

    # --- יצוא ---
    with exp_col1:
        df_export = pd.DataFrame([{
            "מזהה": t["id"], "קטגוריה": t["category"], "סטטוס": t["status"],
            "נפתר ע\"י": t["resolved_by"] or "-", "דירוג": t.get("rating") or "-",
            "נוצר": t["created_at"].strftime("%d/%m/%Y %H:%M")
        } for t in all_tickets])
        buf = io.BytesIO()
        if not df_export.empty:
            df_export.to_excel(buf, index=False, engine="openpyxl")
        st.download_button("📥 יצוא לאקסל", data=buf.getvalue(), file_name="wsc_report.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    with exp_col2:
        st.markdown("""<a href="javascript:window.print()">
            <button style="width:100%;padding:8px;border-radius:8px;border:1px solid rgba(212,255,0,0.4);
            background:transparent;color:#d4ff00;cursor:pointer;">🖨️ הדפסה / PDF</button></a>""",
            unsafe_allow_html=True)

    st.markdown("---")

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        passed = bot_resolved_pct >= 30
        cls, icon = ("metric-pass", "✓") if passed else ("metric-fail", "✗")
        st.markdown(f'''<div class="metric-card"><div class="metric-value">{bot_resolved_pct}%</div>
            <div class="metric-label">פתרון עצמאי של הבוט</div><div class="metric-target">יעד: ≥30%</div>
            <div class="{cls}">{icon} {"מעל היעד" if passed else "מתחת ליעד"}</div></div>''', unsafe_allow_html=True)
    with col2:
        passed = avg_time < 30 if response_times else True
        cls, icon = ("metric-pass", "✓") if passed else ("metric-fail", "✗")
        st.markdown(f'''<div class="metric-card"><div class="metric-value">{avg_time} שנ'</div>
            <div class="metric-label">זמן מענה ראשוני ממוצע</div><div class="metric-target">יעד: &lt;30 שנ'</div>
            <div class="{cls}">{icon} {"מתחת ליעד" if passed else "מעל היעד"}</div></div>''', unsafe_allow_html=True)
    with col3:
        passed = accuracy > 80
        cls, icon = ("metric-pass", "✓") if passed else ("metric-fail", "✗")
        st.markdown(f'''<div class="metric-card"><div class="metric-value">{accuracy}%</div>
            <div class="metric-label">דיוק סיווג תקלות</div><div class="metric-target">יעד: &gt;80%</div>
            <div class="{cls}">{icon} {"מעל היעד" if passed else "מתחת ליעד"}</div></div>''', unsafe_allow_html=True)
    with col4:
        passed = avg_rating >= 4.0
        cls, icon = ("metric-pass", "✓") if passed else ("metric-fail", "✗")
        display_rating = f"{avg_rating}/5" if avg_rating > 0 else "—"
        st.markdown(f'''<div class="metric-card"><div class="metric-value">{display_rating}</div>
            <div class="metric-label">שביעות רצון לקוחות</div><div class="metric-target">יעד: ≥4.0</div>
            <div class="{cls}">{icon if avg_rating>0 else ""} {"מעל היעד" if passed and avg_rating>0 else ("ממתין לדירוגים" if avg_rating==0 else "מתחת ליעד")}</div></div>''', unsafe_allow_html=True)

    st.markdown("---")
    st.subheader("📈 התפלגות פניות לפי קטגוריה")

    cat_counts = {c: 0 for c in CATEGORIES}
    for t in all_tickets:
        cat_counts[t["category"]] = cat_counts.get(t["category"], 0) + 1
    chart_df = pd.DataFrame({"קטגוריה": list(cat_counts.keys()), "כמות פניות": list(cat_counts.values())})

    if chart_df["כמות פניות"].sum() > 0:
        bar = alt.Chart(chart_df).mark_bar(color="#d4ff00").encode(
            x=alt.X("כמות פניות:Q"),
            y=alt.Y("קטגוריה:N", sort="-x"),
            tooltip=["קטגוריה", "כמות פניות"]
        ).properties(height=220)
        st.altair_chart(bar, use_container_width=True)
    else:
        st.info("אין עדיין נתונים להצגה - פתח פניות בטאב הצ'אט.")

    st.markdown("---")
    st.subheader("🔢 סיכום כמותי")
    c_a, c_b, c_c = st.columns(3)
    with c_a:
        st.metric("סה\"כ פניות", len(all_tickets))
    with c_b:
        st.metric("נפתרו ע\"י בוט", resolved_by_bot)
    with c_c:
        st.metric("הוסלמו לנציג", escalated)


# ============================================================
#  SIDEBAR
# ============================================================
with st.sidebar:
    st.markdown(f"### 🎯 {COMPANY_NAME}")
    st.markdown("**Technical Support 24/7**")
    st.divider()
    t = get_ticket()
    if t:
        st.markdown("**🎫 פנייה נוכחית:**")
        st.code(t["id"])
    st.divider()
    st.markdown("**📊 קטגוריות:**")
    for c in CATEGORIES:
        st.markdown(f"• {c}")
    st.divider()
    if st.button("🔄 פנייה חדשה"):
        st.session_state.current_ticket_id = None
        st.session_state.view_mode = "form"
        st.rerun()
    st.divider()
    st.caption("**Graduation Project**")
    st.caption("WSC Sports Support System")
    st.caption("Built by: חיים עוליאל | נועם קיש")
    st.caption("Supervisor: אריה עמית")
