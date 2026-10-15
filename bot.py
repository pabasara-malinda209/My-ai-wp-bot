import os, json, base64, logging, urllib.request
from openai import OpenAI
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

logging.basicConfig(level=logging.INFO)
TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
GH = os.environ.get("GITHUB_TOKEN", "")
client = OpenAI(api_key=os.environ["LLM_API_KEY"],
                base_url=os.environ.get("LLM_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/"))
MODELS = [os.environ.get("LLM_MODEL", "gemini-3.1-flash-lite"), "gemini-3-flash-preview", "gemini-flash-lite-latest"]
OWNER_FILE = "owner.txt"  # first user to /start becomes the only allowed user


def gh(path, method="GET", data=None):
    req = urllib.request.Request("https://api.github.com" + path, method=method,
        data=json.dumps(data).encode() if data else None,
        headers={"Authorization": "Bearer " + GH, "Accept": "application/vnd.github+json"})
    return json.load(urllib.request.urlopen(req, timeout=30))


def ask(messages):
    for m in MODELS:
        try:
            return client.chat.completions.create(model=m, messages=messages, timeout=40).choices[0].message.content
        except Exception as e:
            logging.warning("%s failed: %s", m, e)
    return None


def allowed(update):
    uid = str(update.effective_user.id)
    if os.environ.get("OWNER_ID"):
        return os.environ["OWNER_ID"].strip() == uid
    if not os.path.exists(OWNER_FILE):
        open(OWNER_FILE, "w").write(uid)
    return open(OWNER_FILE).read().strip() == uid


HELP = ("Commands:\n/repo owner/name - select repo\n/files [path] - list files\n"
        "/read path - show file\n/edit path instruction - AI edits file and commits it\n"
        "/new path instruction - AI creates new file\nOr just chat normally.")


async def start(u: Update, c: ContextTypes.DEFAULT_TYPE):
    if not allowed(u): return
    await u.message.reply_text("Hi! GitHub AI bot.\n" + HELP)


async def repo(u, c):
    if not allowed(u): return
    if not c.args: return await u.message.reply_text("Usage: /repo owner/name")
    c.user_data["repo"] = c.args[0]
    await u.message.reply_text("Repo set: " + c.args[0])


def need_repo(u, c):
    return c.user_data.get("repo")


async def files(u, c):
    if not allowed(u): return
    r = need_repo(u, c)
    if not r: return await u.message.reply_text("Set repo first: /repo owner/name")
    p = c.args[0] if c.args else ""
    try:
        items = gh(f"/repos/{r}/contents/{p}")
        await u.message.reply_text("\n".join(("📁 " if i["type"] == "dir" else "📄 ") + i["path"] for i in items) or "empty")
    except Exception as e:
        await u.message.reply_text("Error: %s" % e)


async def read(u, c):
    if not allowed(u): return
    r = need_repo(u, c)
    if not r or not c.args: return await u.message.reply_text("Usage: /repo first, then /read path")
    try:
        f = gh(f"/repos/{r}/contents/{c.args[0]}")
        await u.message.reply_text(base64.b64decode(f["content"]).decode()[:3900] or "(empty)")
    except Exception as e:
        await u.message.reply_text("Error: %s" % e)


async def edit(u, c, new=False):
    if not allowed(u): return
    r = need_repo(u, c)
    if not r or len(c.args) < 2:
        return await u.message.reply_text("Usage: /%s path instruction" % ("new" if new else "edit"))
    path, instr = c.args[0], " ".join(c.args[1:])
    await u.message.reply_text("Working...")
    try:
        sha, old = None, ""
        if not new:
            f = gh(f"/repos/{r}/contents/{path}")
            sha, old = f["sha"], base64.b64decode(f["content"]).decode()
        out = ask([{"role": "system", "content": "You edit files. Return ONLY the complete final file content, no explanations, no markdown fences."},
                   {"role": "user", "content": f"File: {path}\nCurrent content:\n{old}\n\nInstruction: {instr}"}])
        if not out: return await u.message.reply_text("AI is busy, try again.")
        if out.startswith("```"):
            out = out.split("\n", 1)[1].rsplit("```", 1)[0]
        body = {"message": f"AI edit: {instr[:60]}", "content": base64.b64encode(out.encode()).decode()}
        if sha: body["sha"] = sha
        res = gh(f"/repos/{r}/contents/{path}", "PUT", body)
        await u.message.reply_text("✅ Committed: " + res["commit"]["html_url"])
    except Exception as e:
        await u.message.reply_text("Error: %s" % e)


async def new(u, c): await edit(u, c, True)


async def chat(u, c):
    if not allowed(u): return
    h = c.user_data.setdefault("h", [])
    h.append({"role": "user", "content": u.message.text}); h[:] = h[-20:]
    a = ask([{"role": "system", "content": "You are a helpful assistant."}] + h)
    if not a:
        h.pop(); return await u.message.reply_text("AI is busy, try again.")
    h.append({"role": "assistant", "content": a})
    await u.message.reply_text(a)


app = ApplicationBuilder().token(TOKEN).build()
for n, f in [("start", start), ("help", start), ("repo", repo), ("files", files), ("read", read), ("edit", edit), ("new", new)]:
    app.add_handler(CommandHandler(n, f))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat))
app.run_polling()
