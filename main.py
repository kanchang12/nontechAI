from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import os, hashlib, secrets, json
from datetime import datetime
from supabase import create_client
from google import genai
from google.genai import types

# ── ENV ───────────────────────────────────────────────────────────────────────
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")
GEMINI_KEY   = os.getenv("GEMINI_KEY", "")
SECRET       = os.getenv("SECRET_KEY", "ceal-secret-2026")

sb     = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL and SUPABASE_KEY else None
gemini = genai.Client(api_key=GEMINI_KEY) if GEMINI_KEY else None

app = FastAPI(title="AI with AI — CEAL Platform")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# Serve frontend HTML from static/
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
def root():
    return FileResponse("static/platform.html")

# ── MODELS ────────────────────────────────────────────────────────────────────
class RegisterReq(BaseModel):
    name: str
    email: str
    tier: str  # foundation | professional | full

class LoginReq(BaseModel):
    email: str

class ProgressReq(BaseModel):
    module_id: int
    level_id: int
    ghost_caught: Optional[bool] = True
    score: Optional[int] = 0
    decisions: Optional[Dict[str, Any]] = {}

class AgentMsg(BaseModel):
    role: str
    content: str

class AgentReq(BaseModel):
    module_id: int
    level_id: int
    messages: List[AgentMsg]
    user_decisions: Optional[Dict[str, Any]] = {}
    ghost_missed: Optional[bool] = False

class EvalReq(BaseModel):
    module_id: int
    level_id: int
    level_type: str
    user_input: Dict[str, Any]
    ghost_missed: Optional[bool] = False

# ── AUTH ──────────────────────────────────────────────────────────────────────
def make_token(email: str) -> str:
    return hashlib.sha256(f"{email}{SECRET}{secrets.token_hex(8)}".encode()).hexdigest()[:48]

def get_user(x_token: str = Header(default=None)):
    if not sb:
        return {"id": "demo", "name": "Demo User", "email": "demo@aiwithai.online", "tier": "full"}
    if not x_token:
        raise HTTPException(401, "Token required")
    r = sb.table("users").select("*").eq("token", x_token).execute()
    if not r.data:
        raise HTTPException(401, "Invalid token")
    return r.data[0]

# ── AGENT SYSTEM PROMPTS ──────────────────────────────────────────────────────
def build_system_prompt(module_id: int, level_id: int, user_name: str,
                        user_decisions: Dict, ghost_missed: bool) -> str:
    decision_ctx = ""
    if user_decisions:
        decision_ctx = "\n\nUSER PREVIOUS DECISIONS:\n" + "\n".join(f"- {k}: {v}" for k, v in user_decisions.items())
        decision_ctx += "\nReference these. Challenge contradictions directly."

    ghost_ctx = ""
    if ghost_missed and module_id >= 5:
        ghost_ctx = "\n\nCRITICAL: This user did NOT quarantine employee performance data in Module 3 RAG audit. This is a live GDPR Article 9 violation. Confront them about this immediately."

    level_tasks = {
        (1,1): "Module 1 — AI Readiness Audit. Ask sharp questions about team structure and approval bottlenecks. After 4-5 exchanges: Readiness Score 0-100, Top 3 blockers, Immediate next action. START: Ask team size and where approval layers slow development.",
        (1,2): "Module 1 — Org redesign review. Challenge each categorisation: why human oversight, which AI specifically. Score their logic.",
        (1,3): "Module 1 — Policy compliance review. Probe how they'd evidence each item in a real audit. Score their readiness.",
        (1,4): "Module 1 — Play a challenging board member. Reject claims without evidence. Score their defence.",
        (1,5): "Module 1 — Review their 12-month roadmap. Challenge every phase: what if Month 3 fails? Score strategic thinking.",
        (2,1): "Module 2 — Guide them to write a Spec Kit: Goal, Constraints, Metrics, Agent Steps. Flag every ambiguity with risk %. Score the spec quality.",
        (2,2): "Module 2 — Review SDLC flow placement. Challenge wrong placements. Score SDLC understanding.",
        (2,3): "Module 2 — Audit spec security decisions. Ask how each would be tested. Score security thinking.",
        (2,4): "Module 2 — Play a sceptical CTO. Challenge speed vs tech debt claims. Score their defence.",
        (2,5): "Module 2 — Review AI-native workflow plan. Challenge tool choices and lock-in risks. Score strategic depth.",
        (3,1): "Module 3 — Help identify real data moat. Probe every source: could Google buy this in 18 months? Score moat strength 0-100.",
        (3,2): "Module 3 — Review RAG pipeline design. Challenge every placement. Score architecture understanding.",
        (3,3): "Module 3 — GHOST DATA LEVEL. Specifically ask about employee performance data in their RAG. If not identified as sensitive, explicitly fail them. Score data governance.",
        (3,4): "Module 3 — Play risk committee. Challenge cost vs security trade-offs. Score risk reasoning.",
        (3,5): "Module 3 — Review growth plan. At 10x data volume, what breaks first? Score scalability thinking.",
        (4,1): "Module 4 — Teach Planner Agent decomposition. Guide them on a real task. Critique every step missing acceptance criteria. Score decomposition quality.",
        (4,2): "Module 4 — Review multi-agent pipeline. Challenge assignments. Score agent architecture.",
        (4,3): "Module 4 — Review human-in-the-loop design. What specific trigger fires each checkpoint? Score governance design.",
        (4,4): "Module 4 — Play risk committee on agent autonomy. Reference EU AI Act liability. Score defence.",
        (4,5): "Module 4 — Review centaur team roadmap. How do you measure when an agent earns more autonomy? Score maturity.",
        (5,1): "Module 5 — EU AI Act regulator. Challenge every risk tier. Most people underestimate. Score compliance awareness.",
        (5,2): "Module 5 — Review AIMS conformity file. Challenge wrong categorisations. Score ISO 42001 understanding.",
        (5,3): "Module 5 — Mock regulator audit. " + ("Flag GDPR Article 9 violation from Module 3 immediately. Score as non-compliant until acknowledged." if ghost_missed else "Run a thorough audit. Score overall compliance."),
        (5,4): "Module 5 — Live data breach crisis. Push on every decision. Score incident response quality.",
        (5,5): "Module 5 — Review governance roadmap. EU AI Act will update in 2027. How does AIMS adapt? Score future-proofing.",
        (6,1): "Module 6 — Build hard-dollar ROI case. Play CFO. Reject every vague claim. Convert to rupees. Score financial reasoning.",
        (6,2): "Module 6 — Review DX Core 4 dashboard. Challenge every wrong metric assignment. Score understanding.",
        (6,3): "Module 6 — Audit ROI claims for auditability. How would you evidence each to an auditor? Score audit readiness.",
        (6,4): "Module 6 — Play sceptical CFO. Challenge every number. Accept nothing without calculation. Score financial defence.",
        (6,5): "Module 6 — Review 3-year ROI model. Challenge every compounding assumption. Score strategic financial thinking.",
    }

    task = level_tasks.get((module_id, level_id), f"Module {module_id}, Level {level_id} — Audit and score every answer. Challenge every claim.")

    return f"""You are the CEAL AI Consultant inside the AI with AI enterprise certification platform.
You are working with {user_name}.

YOUR RULES:
1. Never accept vague answers. Demand specifics with numbers.
2. Score every significant answer: "Score: X/100 — reason."
3. Reference user's previous decisions — call out contradictions.
4. Quantitative diagnostics: "3 ambiguities → ~15% hallucination risk."
5. After 4+ exchanges provide MODULE SCORE with breakdown.
6. Be direct. Never encourage without evidence.
{decision_ctx}
{ghost_ctx}

TASK: {task}"""

# ── ROUTES ────────────────────────────────────────────────────────────────────
@app.post("/api/register")
def register(req: RegisterReq):
    if not sb:
        return {"token": "demo-token", "user": {"id":"demo","name":req.name,"email":req.email,"tier":req.tier}}
    existing = sb.table("users").select("*").eq("email", req.email).execute()
    if existing.data:
        return {"token": existing.data[0]["token"], "user": existing.data[0]}
    token = make_token(req.email)
    user = sb.table("users").insert({
        "name":req.name,"email":req.email,"tier":req.tier,
        "token":token,"created_at":datetime.utcnow().isoformat()
    }).execute().data[0]
    sb.table("progress").insert({"user_id":user["id"],"data":{},"scores":{},"decisions":{},"ghost_missed":False}).execute()
    return {"token": token, "user": user}

@app.post("/api/login")
def login(req: LoginReq):
    if not sb:
        return {"token":"demo-token","user":{"id":"demo","name":"Demo","email":req.email,"tier":"full"}}
    r = sb.table("users").select("*").eq("email", req.email).execute()
    if not r.data:
        raise HTTPException(404, "Account not found. Please register.")
    return {"token": r.data[0]["token"], "user": r.data[0]}

@app.get("/api/progress")
def get_progress(user=Depends(get_user)):
    if not sb or user.get("id") == "demo":
        return {"progress":{},"scores":{},"decisions":{},"ghost_missed":False}
    r = sb.table("progress").select("*").eq("user_id", user["id"]).execute()
    if not r.data:
        return {"progress":{},"scores":{},"decisions":{},"ghost_missed":False}
    d = r.data[0]
    return {"progress":d.get("data",{}),"scores":d.get("scores",{}),"decisions":d.get("decisions",{}),"ghost_missed":d.get("ghost_missed",False)}

@app.post("/api/progress")
def save_progress(req: ProgressReq, user=Depends(get_user)):
    if not sb or user.get("id") == "demo":
        return {"ok": True}
    existing = sb.table("progress").select("*").eq("user_id", user["id"]).execute()
    if existing.data:
        d = existing.data[0]
        prog, scores, decisions, ghost_missed = d.get("data",{}), d.get("scores",{}), d.get("decisions",{}), d.get("ghost_missed",False)
    else:
        prog, scores, decisions, ghost_missed = {}, {}, {}, False
    mk, lk = str(req.module_id), str(req.level_id)
    if mk not in prog: prog[mk] = {}
    prog[mk][lk] = "completed"
    if mk not in scores: scores[mk] = {}
    scores[mk][lk] = req.score
    if req.decisions:
        decisions[f"M{req.module_id}L{req.level_id}"] = req.decisions
    if req.module_id == 3 and req.level_id == 3:
        ghost_missed = not req.ghost_caught
    if existing.data:
        sb.table("progress").update({"data":prog,"scores":scores,"decisions":decisions,"ghost_missed":ghost_missed}).eq("user_id",user["id"]).execute()
    else:
        sb.table("progress").insert({"user_id":user["id"],"data":prog,"scores":scores,"decisions":decisions,"ghost_missed":ghost_missed}).execute()
    return {"ok": True}

@app.post("/api/agent")
async def agent(req: AgentReq, user=Depends(get_user)):
    """Agentic AI — stateful, scores answers, tracks decisions across modules"""
    if not gemini:
        return {"reply": "GEMINI_KEY not configured.", "score": None, "flags": []}

    user_decisions = req.user_decisions or {}
    ghost_missed = req.ghost_missed

    if sb and user.get("id") != "demo":
        r = sb.table("progress").select("decisions,scores,ghost_missed").eq("user_id", user["id"]).execute()
        if r.data:
            user_decisions = r.data[0].get("decisions", {})
            ghost_missed = r.data[0].get("ghost_missed", False)

    system_prompt = build_system_prompt(
        req.module_id, req.level_id,
        user.get("name", "User"), user_decisions, ghost_missed
    )

    # Build Gemini contents
    contents = []
    for m in req.messages:
        role = "user" if m.role == "user" else "model"
        contents.append(types.Content(role=role, parts=[types.Part(text=m.content)]))

    response = gemini.models.generate_content(
        model="gemini-2.0-flash",
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            max_output_tokens=1200,
            temperature=0.8,
        ),
        contents=contents,
    )

    reply = response.text or "Continue."

    # Extract score if agent gave one
    import re
    score = None
    m = re.search(r'[Ss]core:\s*(\d+)', reply)
    if m:
        score = int(m.group(1))

    flags = ["ghost_data_violation"] if ghost_missed and req.module_id >= 5 else []
    return {"reply": reply, "score": score, "flags": flags}

@app.post("/api/evaluate")
async def evaluate(req: EvalReq, user=Depends(get_user)):
    """AI evaluation of design/comply/defend/future levels — returns score + feedback"""
    if not gemini:
        return {"score": 75, "feedback": "Demo mode.", "passed": True}

    ghost_missed = req.ghost_missed
    if sb and user.get("id") != "demo":
        r = sb.table("progress").select("ghost_missed").eq("user_id", user["id"]).execute()
        if r.data:
            ghost_missed = r.data[0].get("ghost_missed", False)

    eval_prompts = {
        "design": f"You are a CEAL evaluator. Module {req.module_id} drag-and-drop design exercise.\nUser placements: {json.dumps(req.user_input)}\nScore 0-100. Be specific on wrong placements.\nFormat exactly:\nSCORE: X/100\nFEEDBACK: 2-3 sentences.",
        "comply": f"You are a CEAL evaluator. Module {req.module_id} compliance checklist.\nUser input: {json.dumps(req.user_input)}\n{'CRITICAL: Ghost data (employee PII) was NOT caught in Module 3. Penalise heavily.' if ghost_missed and req.module_id==5 else ''}\nScore 0-100.\nFormat exactly:\nSCORE: X/100\nFEEDBACK: 2-3 sentences.",
        "defend": f"You are a CEAL evaluator. Module {req.module_id} defence simulation.\nUser answers: {json.dumps(req.user_input)}\nScore defence quality 0-100.\nFormat exactly:\nSCORE: X/100\nFEEDBACK: 2-3 sentences.",
        "future": f"You are a CEAL evaluator. Module {req.module_id} roadmap.\nUser phases: {json.dumps(req.user_input)}\nScore strategic thinking and specificity 0-100.\nFormat exactly:\nSCORE: X/100\nFEEDBACK: 2-3 sentences.",
    }

    prompt = eval_prompts.get(req.level_type, eval_prompts["defend"])

    response = gemini.models.generate_content(
        model="gemini-2.0-flash",
        config=types.GenerateContentConfig(max_output_tokens=400, temperature=0.4),
        contents=prompt,
    )
    text = response.text or ""

    import re
    score_m = re.search(r'SCORE:\s*(\d+)', text)
    score = int(score_m.group(1)) if score_m else 70
    feed_m = re.search(r'FEEDBACK:\s*(.+)', text, re.DOTALL)
    feedback = feed_m.group(1).strip()[:300] if feed_m else text[:300]

    return {"score": score, "feedback": feedback, "passed": score >= 50}

@app.get("/api/certificate")
def certificate(user=Depends(get_user)):
    scores = {}
    if sb and user.get("id") != "demo":
        r = sb.table("progress").select("scores,data").eq("user_id", user["id"]).execute()
        if r.data:
            scores = r.data[0].get("scores", {})
            prog   = r.data[0].get("data", {})
    else:
        prog = {}
    all_scores = [s for ms in scores.values() for s in ms.values() if s]
    avg = round(sum(all_scores)/len(all_scores)) if all_scores else 0
    levels_done = sum(len(v) for v in prog.values())
    labels = {"foundation":"CEAL Foundation","professional":"CEAL Professional","full":"Certified Enterprise AI Lead (CEAL)"}
    return {
        "name": user["name"], "email": user["email"], "tier": user["tier"],
        "title": labels.get(user["tier"],"CEAL"), "average_score": avg,
        "levels_done": levels_done,
        "issued_by": "LOVEUAD LTD", "company_no": "16838046",
        "issued_on": datetime.utcnow().strftime("%d %B %Y"),
    }

@app.get("/api/certificate/pdf")
def certificate_pdf(user=Depends(get_user)):
    """Generate and return a PDF certificate"""
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas
    from reportlab.lib.styles import getSampleStyleSheet
    import io

    scores, prog = {}, {}
    if sb and user.get("id") != "demo":
        r = sb.table("progress").select("scores,data").eq("user_id", user["id"]).execute()
        if r.data:
            scores = r.data[0].get("scores", {})
            prog   = r.data[0].get("data", {})

    all_scores = [s for ms in scores.values() for s in ms.values() if s]
    avg = round(sum(all_scores)/len(all_scores)) if all_scores else 0
    levels_done = sum(len(v) for v in prog.values())

    labels = {
        "foundation": "CEAL Foundation",
        "professional": "CEAL Professional",
        "full": "Certified Enterprise AI Lead (CEAL)"
    }
    cert_title = labels.get(user["tier"], "CEAL")
    issued_on  = datetime.utcnow().strftime("%d %B %Y")

    # ── Build PDF ──────────────────────────────────────────────────────────────
    buf = io.BytesIO()
    W, H = landscape(A4)
    c = canvas.Canvas(buf, pagesize=landscape(A4))

    NAVY   = colors.HexColor("#1B3068")
    AMBER  = colors.HexColor("#B87200")
    GOLD   = colors.HexColor("#D4A017")
    LTGREY = colors.HexColor("#F5F4EF")
    WHITE  = colors.white
    DARK   = colors.HexColor("#1C1830")
    SUBGREY= colors.HexColor("#4A4862")

    # Background
    c.setFillColor(LTGREY)
    c.rect(0, 0, W, H, fill=1, stroke=0)

    # Navy border frame
    c.setStrokeColor(NAVY)
    c.setLineWidth(3)
    c.rect(12*mm, 12*mm, W-24*mm, H-24*mm, fill=0, stroke=1)

    # Amber inner border line
    c.setStrokeColor(AMBER)
    c.setLineWidth(1)
    c.rect(15*mm, 15*mm, W-30*mm, H-30*mm, fill=0, stroke=1)

    # Navy header band
    c.setFillColor(NAVY)
    c.rect(12*mm, H-42*mm, W-24*mm, 28*mm, fill=1, stroke=0)

    # Logo text in header
    c.setFillColor(WHITE)
    c.setFont("Helvetica-Bold", 20)
    c.drawString(22*mm, H-26*mm, "AI")
    c.setFillColor(AMBER)
    c.drawString(37*mm, H-26*mm, "with")
    c.setFillColor(WHITE)
    c.drawString(58*mm, H-26*mm, "AI")

    # Header subtitle
    c.setFont("Helvetica", 10)
    c.setFillColor(colors.HexColor("#CCCCDD"))
    c.drawString(22*mm, H-35*mm, "Enterprise AI Certification Platform  ·  aiwithai.online")

    # Issued by — right of header
    c.setFont("Helvetica-Bold", 9)
    c.setFillColor(WHITE)
    c.drawRightString(W-22*mm, H-26*mm, "LOVEUAD LTD")
    c.setFont("Helvetica", 8)
    c.setFillColor(colors.HexColor("#CCCCDD"))
    c.drawRightString(W-22*mm, H-33*mm, f"Company No. 16838046  ·  Issued {issued_on}")

    # Main body — "This certifies that"
    c.setFont("Helvetica", 13)
    c.setFillColor(SUBGREY)
    c.drawCentredString(W/2, H-58*mm, "This certifies that")

    # Name
    c.setFont("Helvetica-Bold", 32)
    c.setFillColor(NAVY)
    c.drawCentredString(W/2, H-75*mm, user["name"])

    # Gold line under name
    c.setStrokeColor(GOLD)
    c.setLineWidth(1.5)
    name_w = min(len(user["name"]) * 17, 220*mm)
    c.line(W/2 - name_w/2, H-79*mm, W/2 + name_w/2, H-79*mm)

    # "has successfully completed"
    c.setFont("Helvetica", 13)
    c.setFillColor(SUBGREY)
    c.drawCentredString(W/2, H-88*mm, "has successfully completed")

    # Certificate title
    c.setFont("Helvetica-Bold", 20)
    c.setFillColor(NAVY)
    c.drawCentredString(W/2, H-101*mm, cert_title)

    # Score box
    score_x = W/2 - 40*mm
    score_y = H - 122*mm
    c.setFillColor(NAVY)
    c.roundRect(score_x, score_y, 80*mm, 16*mm, 3*mm, fill=1, stroke=0)
    c.setFont("Helvetica-Bold", 13)
    c.setFillColor(WHITE)
    c.drawCentredString(W/2, score_y + 5*mm, f"Average Score: {avg}/100  ·  {levels_done} Levels Completed")

    # Tier badge
    tier_colors = {"foundation":"#1B3068","professional":"#0D6B4A","full":"#5B2D8E"}
    tc = colors.HexColor(tier_colors.get(user["tier"],"#1B3068"))
    c.setFillColor(tc)
    badge_w = 55*mm
    c.roundRect(W/2 - badge_w/2, H-140*mm, badge_w, 9*mm, 2*mm, fill=1, stroke=0)
    c.setFont("Helvetica-Bold", 9)
    c.setFillColor(WHITE)
    tier_label = labels.get(user["tier"], "CEAL")
    c.drawCentredString(W/2, H-135*mm, tier_label.upper())

    # Footer — signature area
    sig_y = 22*mm
    # Left: director signature line
    c.setStrokeColor(NAVY)
    c.setLineWidth(0.75)
    c.line(22*mm, sig_y+10*mm, 80*mm, sig_y+10*mm)
    c.setFont("Helvetica-Bold", 9)
    c.setFillColor(DARK)
    c.drawString(22*mm, sig_y+5*mm, "Director, LOVEUAD LTD")
    c.setFont("Helvetica", 8)
    c.setFillColor(SUBGREY)
    c.drawString(22*mm, sig_y+1*mm, "Company No. 16838046")

    # Right: verify URL
    c.setFont("Helvetica", 8)
    c.setFillColor(SUBGREY)
    c.drawRightString(W-22*mm, sig_y+5*mm, f"Verify: aiwithai.online/verify/{user.get('id','')}")
    c.drawRightString(W-22*mm, sig_y+1*mm, f"Email: {user['email']}")

    # Centre: date
    c.setFont("Helvetica", 9)
    c.setFillColor(SUBGREY)
    c.drawCentredString(W/2, sig_y+5*mm, f"Issued on {issued_on}")

    c.save()
    buf.seek(0)

    from fastapi.responses import StreamingResponse
    filename = f"CEAL_Certificate_{user['name'].replace(' ','_')}.pdf"
    return StreamingResponse(
        buf,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )
