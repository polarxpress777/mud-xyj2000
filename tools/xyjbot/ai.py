"""AI-assisted bot creation.

Turns a plain-Chinese description ("行功完毕就继续打坐") into Trigger /
TimerBot objects, so a player who can't write regexes can still build one.

Optional: needs the `anthropic` package and an API key. The rest of
xyjbot works without either — botui catches the ImportError and shows the
message to the user.
"""
from __future__ import annotations

import json
import os

from triggers import Trigger, TimerBot

MODEL = "claude-opus-5"

SYSTEM = """\
你是一个中文 MUD（《西游记》，FluffOS/LPC）机器人设定助手。玩家会用中文
描述他们想要的自动化行为，你要把它转成设定资料。

两种自动化：
- trigger（触发）：游戏输出某行文字时，自动送出指令。绝大多数需求属于这类。
- timer（循环）：每隔固定秒数送出指令，用于练功、打坐之类的循环。

重要规则：
- pattern 要用游戏真正会输出的中文原文（例如「你行功完毕，吸一口气，缓缓
  站了起来。」）。若玩家给的是大概意思，取其中最可能原样出现的一小段，
  不要自己发明整句。
- 宁可用较短的片段当 pattern，也不要用可能对不上的长句。
- is_regex 预设 false（纯文字比对）。只有确实需要抓数字之类时才用 true，
  这时可在 actions 里用 $1 代入第一个括号捕获的内容。
- actions 是要送进游戏的指令，通常是英文指令（dazuo、exercise、fight、
  quit、hp、look 等）。
- cooldown 用来避免同一行文字瞬间触发很多次；不确定就填 0。
- 只有玩家明确说「每隔几秒」「一直重复」之类时才产生 timer。
- name 用简短中文。
"""

SCHEMA = {
    "type": "object",
    "properties": {
        "triggers": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "pattern": {"type": "string"},
                    "is_regex": {"type": "boolean"},
                    "actions": {"type": "array", "items": {"type": "string"}},
                    "cooldown": {"type": "number"},
                    "once": {"type": "boolean"},
                },
                "required": ["name", "pattern", "is_regex", "actions",
                             "cooldown", "once"],
                "additionalProperties": False,
            },
        },
        "timers": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "interval": {"type": "number"},
                    "actions": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["name", "interval", "actions"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["triggers", "timers"],
    "additionalProperties": False,
}


def generate_bot(description: str) -> list:
    """Return a list of Trigger / TimerBot built from a Chinese description.

    Raises RuntimeError with a user-facing Chinese message on any problem,
    since botui surfaces the text directly in the status bar.
    """
    try:
        import anthropic
    except ImportError:
        raise RuntimeError(
            "需要 anthropic 套件：pip3 install anthropic") from None

    if not (os.environ.get("ANTHROPIC_API_KEY")
            or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        # An `ant auth login` profile also works, so don't hard-fail here --
        # let the client try and report its own error if there's nothing.
        pass

    client = anthropic.Anthropic()
    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=16000,
            system=SYSTEM,
            output_config={"format": {"type": "json_schema",
                                      "schema": SCHEMA}},
            messages=[{"role": "user", "content": description}],
        )
    except anthropic.AuthenticationError:
        raise RuntimeError("API 金钥无效或未设定 ANTHROPIC_API_KEY") from None
    except anthropic.RateLimitError:
        raise RuntimeError("被限流了，请稍后再试") from None
    except anthropic.APIConnectionError:
        raise RuntimeError("无法连线到 Anthropic API") from None
    except anthropic.APIStatusError as e:
        raise RuntimeError(f"API 错误 {e.status_code}") from None

    if response.stop_reason == "refusal":
        raise RuntimeError("这个要求被拒绝了，请换个说法")

    text = next((b.text for b in response.content if b.type == "text"), "")
    if not text:
        raise RuntimeError("AI 没有回传内容")

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        raise RuntimeError("AI 回传的内容无法解析") from None

    made: list = []
    for d in data.get("triggers", []):
        made.append(Trigger(
            name=d.get("name", "AI 触发"),
            pattern=d.get("pattern", ""),
            actions=list(d.get("actions", [])),
            is_regex=bool(d.get("is_regex", False)),
            cooldown=float(d.get("cooldown", 0.0)),
            once=bool(d.get("once", False)),
            # Off by default: the player should read what the AI wrote
            # before it starts firing commands into a live character.
            enabled=False,
        ))
    for d in data.get("timers", []):
        made.append(TimerBot(
            name=d.get("name", "AI 循环"),
            interval=float(d.get("interval", 10.0)),
            actions=list(d.get("actions", [])),
            enabled=False,
        ))
    return made
