"""Real agent: Hugging Face smolagents ToolCallingAgent. Not Grok. Not a fake loop."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from . import loop
from .managed import ChainBroken, be_home


def _load_env() -> None:
    roots = [
        Path(__file__).resolve().parents[2] / ".env",
        Path.cwd() / ".env",
        be_home() / ".env",
    ]
    for path in roots:
        if not path.is_file():
            continue
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))

INSTRUCTIONS = (
    "对用户只说中文，markdown。"
    "先判断这张单要核什么。话单金额或用量才点名已验证碎片出包；"
    "短信通知、延误、减免政策、不是话单行加总的问题，不要出流量普查。"
    "出包必须自己点名碎片，禁止套一份固定 SQL。禁止手写 Oracle。禁止写计费无误。贴回即权威。"
    "空了要自己判断原因，禁止套「本表未找到」当结案。"
    "be_finish 会自动做四项证据核验；核验通过后必须先让用户确认，只有用户明确确认后才调用 be_confirm，再调用 be_archive。"
)

DRILL_THINK = (
    "贴回已入库。根据这张单和贴回自己判断。"
    "有费为0、主张金额没对上，不要套别的工单口径、不要直接 finish。"
    "看用量、账期、办理/通知是不是这张表能回答的。要再查就点名不同碎片。"
    "禁止同一份 SQL。禁止写计费无误。"
)

_reasoning_turns: list[str] = []

_last_user = ""


def _json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


def _tools() -> list[Any]:
    from smolagents import tool

    @tool
    def be_start(
        ticket_id: str,
        acc_num: str,
        months: str,
        claim: str,
        ticket_text: str = "",
    ) -> str:
        """Lock ticket slots then return similar past cases.

        Args:
            ticket_id: Work order id, or empty string if unknown.
            acc_num: 8-digit MSISDN of the complained number.
            months: Bill months as 202609 or 202608,202609. 本月 and 回复期限 date win.
            claim: Customer claim in one or two sentences.
            ticket_text: Full CRM paste. Prefer the entire user message.
        """
        blob = (ticket_text or "").strip() or _last_user
        return _json(
            loop.start(
                ticket_id=ticket_id,
                acc_num=acc_num,
                months=months,
                claim=claim,
                ticket_text=blob,
            )
        )

    @tool
    def be_fragments(arguments: str = "") -> str:
        """List SQL fragment names, proven flag, and one-line notes. No SQL bodies.

        Args:
            arguments: Ignore. Some models send this by mistake.
        """
        from . import catalog

        return _json({"items": catalog.list_fragments(include_body=False)})

    @tool
    def be_fragment(name: str) -> str:
        """Fetch one SQL fragment body. This is the only allowed RAG payload.

        Args:
            name: Fragment name such as members or data_fee.
        """
        from . import catalog

        row = catalog.get_fragment(name)
        if not row:
            return _json({"error": f"no fragment {name}"})
        return _json(row)

    @tool
    def be_pack(parts: str = "", arguments: str = "") -> str:
        """Assemble named proven fragments for the open case. SQL appears on the right.

        Args:
            parts: Comma-separated fragment names, e.g. members,data_fee,data_charged.
            arguments: Ignore unless it is the parts list.
        """
        chosen = (parts or "").strip()
        if not chosen or chosen in {"{}", "null"}:
            chosen = (arguments or "").strip()
        out = loop.pack(parts=chosen)
        n = len(str(out.get("sql") or ""))
        out.pop("sql", None)
        out["sql_chars"] = n
        out["hint"] = "SQL 在右侧，请点「一键复制 SQL」。"
        return _json(out)

    @tool
    def be_ingest(text: str) -> str:
        """Store pasted SQL results from the human.

        Args:
            text: Raw query result pasted from the bastion SQL client.
        """
        return _json(loop.ingest(text))

    @tool
    def be_verify(arguments: str = "") -> str:
        """Check pack shape and whether bill amounts appear in ingest.

        Args:
            arguments: Ignore. Some models send this by mistake.
        """
        return _json(loop.verify())

    @tool
    def be_finish(arguments: str = "") -> str:
        """Write a three-sentence draft and run evidence review. Does not archive yet.

        核验通过后先把草稿和核验结果交给用户确认；用户没有明确确认时不要调用 be_confirm。

        Args:
            arguments: Ignore. Some models send this by mistake.
        """
        return _json(loop.finish())

    @tool
    def be_review(arguments: str = "") -> str:
        """Re-run evidence review for the current draft. Does not archive."""
        return _json(loop.review())

    @tool
    def be_confirm(arguments: str = "") -> str:
        """Record explicit human confirmation after a passing review."""
        return _json(loop.confirm())

    @tool
    def be_archive(finding: str = "", arguments: str = "") -> str:
        """Archive into SQLite history after review and explicit human confirmation.

        Args:
            finding: Final evidence sentence. Empty uses the draft.
            arguments: Ignore. Some models send this by mistake.
        """
        return _json(loop.archive(finding))

    @tool
    def be_abandon(reason: str = "") -> str:
        """Mark the open case abandoned.

        Args:
            reason: Why this ticket is abandoned.
        """
        return _json(loop.abandon(reason))

    @tool
    def be_history(query: str) -> str:
        """Search at most 3 similar closed tickets.

        Args:
            query: Keyword such as 副卡, 香港, or 53.75.
        """
        from . import catalog

        return _json({"items": catalog.search_history(query, 3)})

    return [
        be_start,
        be_fragments,
        be_fragment,
        be_pack,
        be_ingest,
        be_verify,
        be_finish,
        be_review,
        be_confirm,
        be_archive,
        be_abandon,
        be_history,
    ]


def _model() -> Any:
    from smolagents import OpenAIServerModel
    from smolagents.models import ChatMessage, TokenUsage

    _load_env()
    model_id = (
        os.environ.get("BE_MODEL")
        or "deepseek-v4-flash"
    )
    api_key = (
        os.environ.get("DEEPSEEK_API_KEY")
        or os.environ.get("BE_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
        or ""
    )
    api_base = os.environ.get("BE_API_BASE") or os.environ.get("OPENAI_BASE_URL") or ""
    if api_key.startswith("sk-") and "deepseek" in model_id.lower():
        api_base = api_base or "https://api.deepseek.com"
    if not api_base:
        api_base = "https://api.deepseek.com"
    if not api_key:
        raise ChainBroken("missing DEEPSEEK_API_KEY in be/.env")

    class DeepSeekModel(OpenAIServerModel):
        """Thinking + tools: tool_choice=auto, and pass reasoning_content back."""

        def generate(  # type: ignore[override]
            self,
            messages,
            stop_sequences=None,
            response_format=None,
            tools_to_call_from=None,
            **kwargs,
        ):
            if tools_to_call_from:
                kwargs["tool_choice"] = "auto"
            kwargs.pop("temperature", None)
            kwargs.pop("presence_penalty", None)
            kwargs.pop("frequency_penalty", None)
            completion_kwargs = self._prepare_completion_kwargs(
                messages=messages,
                stop_sequences=stop_sequences,
                response_format=response_format,
                tools_to_call_from=tools_to_call_from,
                model=self.model_id,
                custom_role_conversions=self.custom_role_conversions,
                convert_images_to_image_urls=True,
                **kwargs,
            )
            asst = 0
            for item in completion_kwargs.get("messages") or []:
                if item.get("role") != "assistant":
                    continue
                if asst < len(_reasoning_turns) and _reasoning_turns[asst]:
                    item["reasoning_content"] = _reasoning_turns[asst]
                asst += 1
            self._apply_rate_limit()
            try:
                response = self.retryer(self.client.chat.completions.create, **completion_kwargs)
            except Exception as exc:
                err = str(exc)
                if "tool_choice" in err or "thinking" in err.lower() or "400" in err:
                    completion_kwargs.pop("tool_choice", None)
                    extra = dict(completion_kwargs.get("extra_body") or {})
                    extra["thinking"] = {"type": "enabled"}
                    completion_kwargs["extra_body"] = extra
                    response = self.retryer(self.client.chat.completions.create, **completion_kwargs)
                else:
                    raise
            content = response.choices[0].message.content
            if stop_sequences is not None and not self.supports_stop_parameter:
                from smolagents.models import remove_content_after_stop_sequences

                content = remove_content_after_stop_sequences(content, stop_sequences)
            reasoning = getattr(response.choices[0].message, "reasoning_content", None) or ""
            _reasoning_turns.append(str(reasoning))
            usage = getattr(response, "usage", None)
            return ChatMessage(
                role=response.choices[0].message.role,
                content=content,
                tool_calls=response.choices[0].message.tool_calls,
                raw=response,
                token_usage=TokenUsage(
                    input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
                    output_tokens=getattr(usage, "completion_tokens", 0) or 0,
                )
                if usage
                else None,
            )

    return DeepSeekModel(
        model_id=model_id,
        api_base=api_base,
        api_key=api_key,
        extra_body={"thinking": {"type": "enabled"}},
        reasoning_effort="high",
        max_tokens=8192,
    )


_agent: Any = None


def reset_agent() -> None:
    global _agent
    _agent = None
    _reasoning_turns.clear()


def _reason_brief() -> str:
    raw = (_reasoning_turns[-1] if _reasoning_turns else "").strip()
    if not raw:
        return ""
    bits = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    text = " ".join(bits[-4:]) if bits else raw
    return text[:500]


_grid_re_cache: tuple[frozenset[str], re.Pattern[str]] | None = None


def _compile_grid_re() -> re.Pattern[str]:
    global _grid_re_cache
    from . import catalog

    names = frozenset(catalog.all_alias_names())
    if _grid_re_cache and _grid_re_cache[0] == names:
        return _grid_re_cache[1]
    if not names:
        pat = re.compile(r"(?!x)x")
    else:
        parts = sorted(names, key=len, reverse=True)
        pat = re.compile("|".join(re.escape(n) for n in parts), re.I)
    _grid_re_cache = (names, pat)
    return pat


class _GridRe:
    def search(self, text: str | None) -> re.Match[str] | None:
        return _compile_grid_re().search(text or "")


_GRID_RE = _GridRe()


def chat(message: str) -> str:
    global _agent, _last_user
    _last_user = message or ""
    loop.append_chat("user", message)
    is_grid = bool(_GRID_RE.search(message or ""))
    cur = loop.load_current()
    if (
        not is_grid
        and (not cur or not cur.get("acc_num"))
        and re.search(r"工单OID|工單OID|投訴具體|計費收費", message or "")
    ):
        try:
            loop.start(
                ticket_id="",
                acc_num="",
                months="",
                claim="",
                ticket_text=message or "",
            )
        except ChainBroken as exc:
            loop.append_chat("sys", str(exc)[:400])
    text = ""
    run_msg = message or ""
    cur = loop.load_current()
    if is_grid and cur and cur.get("sql"):
        try:
            loop.ingest(message or "")
            cur = loop.load_current()
        except ChainBroken as exc:
            loop.append_chat("sys", str(exc)[:400])
        act = ((cur or {}).get("action") or {}) if isinstance((cur or {}).get("action"), dict) else {}
        if str(act.get("code") or "") == "be_ingest":
            msg = "## " + str(act.get("title") or "还缺贴回") + "\n\n" + str(act.get("detail") or "")
            loop.append_chat("agent", msg)
            return msg
        if str(act.get("code") or "") == "stop":
            msg = "## " + str(act.get("title") or "停下") + "\n\n" + str(act.get("detail") or "")
            loop.append_chat("agent", msg)
            return msg
    if cur and cur.get("acc_num"):
        if is_grid:
            parts_now = list(cur.get("parts") or [])
            if (cur.get("action") or {}).get("code") == "be_ingest":
                title = str((cur.get("action") or {}).get("title") or "还缺贴回")
                detail = str((cur.get("action") or {}).get("detail") or "")
                msg = f"## {title}\n\n{detail}"
                loop.append_chat("agent", msg)
                return msg
            elif "data_survey" in parts_now or "data_by_day" in parts_now:
                run_msg = DRILL_THINK
            else:
                run_msg = (
                    "结果表已入库。取证只问：主张金额能不能从这些行加总找到。"
                    "加总得上就是证据已找到，不是未覆盖，不要提扣减行。"
                    "口述错就写哪一句不成立。中文短答。"
                )
        elif loop.is_ora_00942(message or ""):
            run_msg = (
                "已 ingest。表不存在，等真实表名。不要换表、不要再出同一份 SQL。"
            )
        elif loop.is_empty_ingest(message or ""):
            parts = ",".join(str(x) for x in (cur.get("parts") or []))
            months = ",".join(str(m) for m in (cur.get("months") or []))
            last = (list(cur.get("parts") or []) or [""])[-1]
            run_msg = (
                "用户确认查询无行。请 ingest「空」。贴回即权威，不要再要格子。"
                f"本包 {parts or '—'}，账期 {months or '—'}，最后一段 {last or '—'}。"
                "空不等于没用过、不等于主张不成立。禁止套「本表未找到」三句话，禁止用空来 be_finish。"
                "你自己判断为什么空：有费行在套餐内会空、当月月表可能未出账、办理/通知不在话单表。"
                "要再查就点名不同碎片或月份。禁止同一份 SQL。对用户把判断说清楚。"
            )
        elif cur.get("sql") and not str(cur.get("ingest") or "").strip():
            run_msg = (
                "SQL 已在右侧。用中文请用户点「一键复制 SQL」整份执行，把结果贴回。"
                "在人贴回之前不要核对、不要结案、不要当空表、不要再出包。"
            )
        else:
            run_msg = (
                f"工单已锁 {cur.get('ticket_id')} 号码 {cur.get('acc_num')} "
                f"月 {','.join(cur.get('months') or [])}。"
                f"主张：{str(cur.get('claim') or '')[:800]}。"
                "先根据这段主张判断要核什么。话单金额或用量才 be_fragments 后点名碎片 be_pack；"
                "短信通知、延误、减免政策不要出流量普查。禁止手写 Oracle。禁止套默认包。"
                "对用户中文说明判断。人未贴回前不要核对、不要结案。"
            )
    try:
        from smolagents import ToolCallingAgent
        from smolagents.monitoring import AgentLogger, LogLevel
        from rich.console import Console

        if _agent is None:
            quiet = Console(file=open(be_home() / "agent.log", "a", encoding="utf-8"))
            logger = AgentLogger(level=LogLevel.ERROR, console=quiet)

            def _on_step(memory_step, agent=None) -> None:
                bits: list[str] = []
                calls = getattr(memory_step, "tool_calls", None) or []
                names = []
                for tc in calls:
                    names.append(getattr(tc, "name", None) or str(getattr(tc, "id", "") or tc))
                if names:
                    bits.append("调用：" + ", ".join(names))
                brief = _reason_brief()
                if brief:
                    bits.append("思考：" + brief)
                err = getattr(memory_step, "error", None)
                if err:
                    bits.append("错误：" + str(err)[:400])
                if bits:
                    loop.append_chat("sys", "\n".join(bits))

            try:
                _agent = ToolCallingAgent(
                    tools=_tools(),
                    model=_model(),
                    instructions=INSTRUCTIONS,
                    max_steps=10,
                    verbosity_level=LogLevel.OFF,
                    logger=logger,
                    step_callbacks=[_on_step],
                )
            except TypeError:
                _agent = ToolCallingAgent(
                    tools=_tools(),
                    model=_model(),
                    max_steps=10,
                    verbosity_level=LogLevel.OFF,
                    logger=logger,
                    step_callbacks=[_on_step],
                )
        result = _agent.run(run_msg, reset=False)
        text = str(result) if result is not None else ""
    except Exception as exc:
        loop.append_chat("sys", "agent error: " + str(exc)[:400])
    cur = loop.load_current()
    if cur and cur.get("sql") and str(cur.get("process") or "") in {"packed", "active"}:
        if loop.is_empty_ingest(message or ""):
            try:
                loop.ingest(message or "空")
            except ChainBroken as exc:
                loop.append_chat("sys", str(exc)[:400])
        elif loop.is_ora_00942(message or ""):
            try:
                loop.ingest(message or "")
            except ChainBroken as exc:
                loop.append_chat("sys", str(exc)[:400])
    cur = loop.load_current()
    if not text:
        if cur and str(cur.get("sql") or "").strip():
            text = "已处理。请看右侧 SQL。"
        else:
            text = "已处理。"
    loop.append_chat("agent", text)
    case = loop.load_current()
    if case is not None:
        loop.save_current(case)
    return text
