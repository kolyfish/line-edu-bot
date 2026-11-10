import logging
from collections import defaultdict, deque

from anthropic import Anthropic

logger = logging.getLogger(__name__)
client = Anthropic()

MODEL = "claude-sonnet-5-5"
# 20 則 ≈ 10 輪：保留足夠上下文，又不會讓每次呼叫的 token 費用無限成長
MAX_HISTORY_MESSAGES = 20

# 決策: 依講義 CH24 步驟 C 四段式（角色/範疇/風格/引導），控制在 200-400 字
# 注意: LINE 不渲染 Markdown，所以「條列」明確限定用 1. 2. 或 ・，禁止 ** # 表格
SYSTEM_PROMPT = """你是一位親切、耐心的 AI 教學助理，專門協助高中生解答學科問題。

【職責範疇】
可以處理：數學、物理、化學、生物、社會科學（歷史、地理、公民）。
不處理：個人感情或家庭問題、政治立場話題、與學習無關的閒聊。遇到時溫和說明你只負責學科問題，並建議找師長或學校輔導室。

【回答風格】
用繁體中文，親切但學術嚴謹。適當分段，條列用「1. 2. 3.」或「・」。訊息會顯示在 LINE，不要使用 **、#、表格等 Markdown 符號。每次回覆控制在 300 字內。

【引導原則】
不直接給最終答案，而是引導學生自己找到答案：
1. 先問學生目前的想法，或卡在哪一步
2. 一次只給一個提示或關鍵概念
3. 學生答對時具體肯定；答錯時指出思路哪裡偏了，再給下一個提示
4. 學生嘗試兩次仍卡住，才示範完整步驟，並出一題類似題讓他自己練習"""

HELP_MESSAGE = """AI 教學助理使用說明

我能幫你解答：
・數學（代數、幾何、微積分）
・物理、化學、生物
・社會科學（歷史、地理、公民）

指令：
・直接輸入問題 → 我會一步步引導你
・「清除」→ 清除你的對話記錄
・「幫助」→ 顯示這個說明

在班級群組裡：@我，或用「問:」開頭才會回應"""

# 決策: deque(maxlen) 取代講義的 list[-20:]，自動丟最舊的
# 注意: 存在記憶體，Render 重啟/休眠就清空；gunicorn 必須單一 worker，否則記憶不共用
user_conversations: dict[str, deque] = defaultdict(lambda: deque(maxlen=MAX_HISTORY_MESSAGES))


def get_ai_response(user_id: str, user_message: str) -> str:
    """
    取得 Claude 回覆並維護該學生的對話歷史

    注意: 講義版本有兩個坑，這裡已修正
      1. 切到 20 則後可能以 assistant 開頭 → Claude API 400
      2. 失敗時提問留在歷史 → 下次出現連續兩則 user
    Returns:
        str: 回覆文字；失敗時回道歉訊息（不拋異常，因為 reply token 只能用一次）
    """
    history = user_conversations[user_id]
    history.append({"role": "user", "content": user_message})
    messages = list(history)
    if messages[0]["role"] == "assistant":
        messages = messages[1:]

    try:
        # 決策: 開 server-side fallback，原因: 化學/生物題偶爾被安全分類器誤判拒答，自動改由其他模型回答
        resp = client.beta.messages.create(
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            model=MODEL,
            # 思考 token 也算在 max_tokens 裡，設太小會只思考完就被截斷、沒有答案
            max_tokens=4000,
            # 決策: 聊天用 low effort，原因: Sonnet 5.5 預設 high，教學問答不需要深度推理，low 更快更省
            output_config={"effort": "low"},
            system=SYSTEM_PROMPT,
            messages=messages,
        )
        # 注意: Sonnet 5.5 預設開思考，content[0] 是 ThinkingBlock 不是文字（講義寫法會直接 crash）
        answer = "".join(b.text for b in resp.content if b.type == "text").strip()
        if not answer:
            raise ValueError(f"回覆沒有文字內容 stop_reason={resp.stop_reason}")
    except Exception as e:
        logger.error(f"Claude 呼叫失敗 user={user_id}: {type(e).__name__}: {e}")
        history.pop()
        # 決策: 不把 str(e) 回給學生（講義做法），原因: 可能洩漏 API 錯誤細節
        return "抱歉，我現在有點忙，請稍後再問一次 🙏"

    # 歷史只存文字、不存思考區塊，原因: deque 截掉舊訊息時，思考區塊會跟對話前文對不上
    history.append({"role": "assistant", "content": answer})
    return answer


def clear_conversation(user_id: str) -> str:
    user_conversations.pop(user_id, None)
    return "對話記錄已清除，讓我們從頭開始！"


def get_help_message() -> str:
    return HELP_MESSAGE
