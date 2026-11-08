import logging
import os

from dotenv import load_dotenv

# 必須在 import ai_teacher 前載入，原因: ai_teacher 一 import 就建立 Anthropic client 讀 API key
load_dotenv()

from flask import Flask, abort, request  # noqa: E402
from linebot.v3 import WebhookHandler  # noqa: E402
from linebot.v3.exceptions import InvalidSignatureError  # noqa: E402
from linebot.v3.messaging import (  # noqa: E402
    ApiClient,
    Configuration,
    MessagingApi,
    ReplyMessageRequest,
    TextMessage,
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent  # noqa: E402

from ai_teacher import clear_conversation, get_ai_response, get_help_message  # noqa: E402

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
configuration = Configuration(access_token=os.environ["LINE_CHANNEL_ACCESS_TOKEN"])
handler = WebhookHandler(os.environ["LINE_CHANNEL_SECRET"])

CLEAR_COMMANDS = {"清除", "clear", "重置"}
HELP_COMMANDS = {"幫助", "help", "?", "？"}
# 全形冒號也收，原因: 手機中文輸入法打出來幾乎都是「：」
ASK_PREFIXES = ("問:", "問：")
# LINE 單則上限 5000 字、一次 reply 最多 5 則；留緩衝切 4000
CHUNK_SIZE = 4000
MAX_REPLY_MESSAGES = 5


def extract_group_question(message: TextMessageContent) -> str | None:
    """
    群組模式：只有 @Bot 或「問:」開頭才回應，並去掉觸發前綴

    決策: 用 mention.is_self 判斷，不比對 "@AI教學助理" 字串
    原因: 講義寫法沒空格，但 Bot 顯示名稱是「AI 教學助理」（有空格），字串比對永遠不會中；
          改名後也不用改程式
    Returns:
        str | None: 去掉前綴後的問題；None 表示這則不是對 Bot 說的
    """
    text = message.text
    mentionees = message.mention.mentionees if message.mention else []
    self_mention = next((m for m in mentionees if getattr(m, "is_self", False)), None)

    if self_mention:
        text = text[: self_mention.index] + text[self_mention.index + self_mention.length :]
    elif text.strip().startswith(ASK_PREFIXES):
        text = text.strip()[2:]
    else:
        return None
    return text.strip()


def split_reply(text: str) -> list[TextMessage]:
    chunks = [text[i : i + CHUNK_SIZE] for i in range(0, len(text), CHUNK_SIZE)] or [""]
    return [TextMessage(text=c) for c in chunks[:MAX_REPLY_MESSAGES]]


@app.get("/")
def health():
    # Render 免費層休眠後，先開首頁喚醒再按 LINE Verify，否則會逾時
    return "ok"


@app.post("/callback")
def callback():
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        logger.warning("簽章驗證失敗：Channel secret 不對，或請求不是 LINE 發的")
        abort(400)
    return "OK"


@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event: MessageEvent):
    source = event.source
    # 群組裡極少數情況拿不到 user_id（成員未同意條款），退回用群組 id 當記憶 key
    user_id = source.user_id or getattr(source, "group_id", None) or getattr(source, "room_id", "")

    if source.type in ("group", "room"):
        user_message = extract_group_question(event.message)
        if user_message is None:
            return
    else:
        user_message = event.message.text.strip()

    if user_message in CLEAR_COMMANDS:
        reply_text = clear_conversation(user_id)
    elif user_message in HELP_COMMANDS or not user_message:
        reply_text = get_help_message()
    else:
        reply_text = get_ai_response(user_id, user_message)

    with ApiClient(configuration) as api_client:
        MessagingApi(api_client).reply_message(
            ReplyMessageRequest(reply_token=event.reply_token, messages=split_reply(reply_text))
        )


if __name__ == "__main__":
    # 本地預設 5001，原因: macOS 的 AirPlay 接收器佔用 5000，ngrok http 5000 會打到 AirPlay 回 403
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5001)))
