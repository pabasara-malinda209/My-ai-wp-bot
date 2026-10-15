import os
import logging
from openai import OpenAI
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

logging.basicConfig(level=logging.INFO)

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
client = OpenAI(
    api_key=os.environ["LLM_API_KEY"],
    base_url=os.environ.get("LLM_BASE_URL", "https://integrations.emergentagent.com/llm"),
)
MODEL = os.environ.get("LLM_MODEL", "gpt-4o-mini")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Hi! I'm your AI bot. Send me a message.")


async def chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    history = context.user_data.setdefault("history", [])
    history.append({"role": "user", "content": update.message.text})
    history[:] = history[-20:]
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "system", "content": "You are a helpful assistant."}] + history,
    )
    answer = resp.choices[0].message.content
    history.append({"role": "assistant", "content": answer})
    await update.message.reply_text(answer)


def main():
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat))
    app.run_polling()


if __name__ == "__main__":
    main()
