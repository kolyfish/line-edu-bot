"""
Webhook 端到端測試：用真實 HMAC 簽章模擬 LINE 送訊息，mock 掉 Claude 與 LINE 回覆 API

注意: Claude mock 必須照真實回傳形狀（思考區塊 + 文字區塊）。
      曾經 mock 只回文字區塊 → 測試全綠，上線後 Sonnet 5.5 回 ThinkingBlock 直接崩潰。
"""
import base64
import hashlib
import hmac
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

SECRET = "testsecret"
# 假值，只為了讓 app 能 import；gitleaks:allow 標記避免 pre-commit 誤判
os.environ.update(LINE_CHANNEL_ACCESS_TOKEN="x", LINE_CHANNEL_SECRET=SECRET, ANTHROPIC_API_KEY="x")  # gitleaks:allow
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import ai_teacher  # noqa: E402
import app as appmod  # noqa: E402

USER_A = {"type": "user", "userId": "UA"}
USER_B = {"type": "user", "userId": "UB"}


def group(user_id: str) -> dict:
    return {"type": "group", "groupId": "G1", "userId": user_id}


def self_mention(length: int) -> dict:
    return {"mentionees": [{"type": "user", "index": 0, "length": length, "userId": "U0", "isSelf": True}]}


@pytest.fixture
def bot(monkeypatch):
    """回傳 post(source, text, mention) → (status, 回覆文字列表)，並記錄 Claude 呼叫參數與載入動畫"""
    ai_teacher.user_conversations.clear()
    claude_calls, replies, typing = [], [], []

    def fake_create(**kw):
        claude_calls.append(kw)
        question = kw["messages"][-1]["content"]
        text = "A" * 4500 if "長" in question else f"回覆:{question}"
        return SimpleNamespace(
            stop_reason="end_turn",
            content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=text)],
        )

    monkeypatch.setattr(ai_teacher.client.beta.messages, "create", fake_create)
    monkeypatch.setattr("linebot.v3.messaging.MessagingApi.reply_message",
                        lambda self, req: replies.append([m.text for m in req.messages]))
    monkeypatch.setattr("linebot.v3.messaging.MessagingApi.show_loading_animation",
                        lambda self, req: typing.append(req.chat_id))

    def post(source: dict, text: str, mention: dict | None = None):
        message = {"type": "text", "id": "1", "quoteToken": "q", "text": text}
        if mention:
            message["mention"] = mention
        body = json.dumps({"destination": "U0", "events": [{
            "type": "message", "mode": "active", "timestamp": 0, "webhookEventId": "w",
            "deliveryContext": {"isRedelivery": False}, "replyToken": "r", "source": source, "message": message,
        }]})
        sig = base64.b64encode(hmac.new(SECRET.encode(), body.encode(), hashlib.sha256).digest()).decode()
        replies.clear()
        r = appmod.app.test_client().post(
            "/callback", data=body, headers={"X-Line-Signature": sig, "Content-Type": "application/json"}
        )
        return r.status_code, list(replies)

    post.claude_calls, post.typing = claude_calls, typing
    return post


def test_個人提問會回覆並顯示載入動畫(bot):
    assert bot(USER_A, "什麼是三角函數") == (200, [["回覆:什麼是三角函數"]])
    assert bot.typing == ["UA"]


def test_不同學生的對話記憶互相隔離(bot):
    bot(USER_A, "第一題")
    bot(USER_B, "我問過什麼")
    assert len(bot.claude_calls[-1]["messages"]) == 1
    bot(USER_A, "第二題")
    assert len(bot.claude_calls[-1]["messages"]) == 3


@pytest.mark.parametrize("cmd", ["幫助", "help", "?", "？"])
def test_幫助指令不呼叫Claude(bot, cmd):
    status, replies = bot(USER_A, cmd)
    assert replies[0][0].startswith("AI 教學助理使用說明")
    assert bot.claude_calls == [] and bot.typing == []


def test_清除指令只清自己的記憶(bot):
    bot(USER_A, "q")
    bot(USER_B, "q")
    bot(USER_A, "清除")
    assert "UA" not in ai_teacher.user_conversations
    assert len(ai_teacher.user_conversations["UB"]) == 2


@pytest.mark.parametrize("text, mention, expected", [
    ("今天午餐吃什麼", None, []),
    ("問：牛頓第二定律", None, [["回覆:牛頓第二定律"]]),
    ("問:牛頓第二定律", None, [["回覆:牛頓第二定律"]]),
    ("@AI 教學助理 光合作用是什麼", self_mention(8), [["回覆:光合作用是什麼"]]),
    ("@小明 交作業了嗎", {"mentionees": [{"type": "user", "index": 0, "length": 3, "userId": "UX", "isSelf": False}]}, []),
])
def test_群組只回應at_Bot或問開頭(bot, text, mention, expected):
    assert bot(group("UC"), text, mention) == (200, expected)
    assert bot.typing == []  # LINE 群組不支援載入動畫


def test_長回覆切成4000字分段(bot):
    _, replies = bot(USER_A, "給我長答案")
    assert [len(t) for t in replies[0]] == [4000, 500]


def test_錯誤簽章回400():
    r = appmod.app.test_client().post("/callback", data="{}", headers={"X-Line-Signature": "bad"})
    assert r.status_code == 400


def test_歷史滿20則後第一則仍是user(bot):
    for _ in range(13):
        bot(USER_A, "q")
    msgs = bot.claude_calls[-1]["messages"]
    assert msgs[0]["role"] == "user" and len(msgs) <= ai_teacher.MAX_HISTORY_MESSAGES


def test_Claude失敗時回道歉且不留下孤兒提問(bot, monkeypatch):
    def boom(**kw):
        raise RuntimeError("API down")
    monkeypatch.setattr(ai_teacher.client.beta.messages, "create", boom)
    _, replies = bot(USER_A, "q")
    assert "抱歉" in replies[0][0] and "API down" not in replies[0][0]
    assert len(ai_teacher.user_conversations["UA"]) == 0


def test_只有思考區塊沒有文字時視為失敗(bot, monkeypatch):
    monkeypatch.setattr(ai_teacher.client.beta.messages, "create",
                        lambda **kw: SimpleNamespace(stop_reason="max_tokens",
                                                     content=[SimpleNamespace(type="thinking", thinking="")]))
    _, replies = bot(USER_A, "q")
    assert "抱歉" in replies[0][0]


def test_Claude呼叫參數(bot):
    bot(USER_A, "q")
    kw = bot.claude_calls[-1]
    assert kw["output_config"] == {"effort": "low"} and kw["fallbacks"] == "default"
