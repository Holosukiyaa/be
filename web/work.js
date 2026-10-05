import { createApp, reactive, computed, onMounted, nextTick, ref } from "/vendor/vue.esm-browser.prod.js";
import { PROCESS, NavBar, EvidenceCharts, TrailMap, api, applyState, emptyState, paintMermaid } from "/common.js";
import { looksLikeMarkdown, renderMarkdown } from "/md.js";

createApp({
  components: { NavBar, EvidenceCharts, TrailMap },
  setup() {
    const state = reactive(emptyState());
    const draft = ref("");
    const busy = ref(false);
    const threadEl = ref(null);
    const statusLine = ref("");
    let firstPull = true;

    function nearBottom() {
      const el = threadEl.value;
      if (!el) return true;
      return el.scrollHeight - el.scrollTop - el.clientHeight < 80;
    }

    function scrollBottom() {
      const el = threadEl.value;
      if (el) el.scrollTop = el.scrollHeight;
    }

    async function pull() {
      const stick = firstPull || nearBottom();
      const y = threadEl.value ? threadEl.value.scrollTop : 0;
      try {
        applyState(state, await api("/api/state"));
        await nextTick();
        paintMermaid(document);
        if (!threadEl.value) return;
        if (stick) scrollBottom();
        else threadEl.value.scrollTop = y;
        firstPull = false;
      } catch (e) {
        statusLine.value = String(e.message || e);
      }
    }

    async function send(preset) {
      const text = (typeof preset === "string" ? preset : draft.value).trim();
      if (!text || busy.value) return;
      draft.value = "";
      busy.value = true;
      statusLine.value = "思考中…";
      try {
        const data = await api("/api/chat", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ message: text }),
        });
        if (data.error) statusLine.value = data.error;
        else statusLine.value = "";
        applyState(state, data.state);
        await nextTick();
        paintMermaid(document);
        scrollBottom();
      } catch (e) {
        if (e.state) applyState(state, e.state);
        statusLine.value = String(e.message || e);
      } finally {
        busy.value = false;
      }
    }

    async function newChat() {
      if (!confirm("清空当前对话并开始新单？未结档的工单不会写入历史。")) return;
      const data = await api("/api/new", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      });
      applyState(state, data.state);
      statusLine.value = "";
    }

    function submitEmpty() {
      return send("结果是空的");
    }

    async function copySql() {
      const text = state.sql || "";
      if (!text) return;
      try {
        await navigator.clipboard.writeText(text);
      } catch {
        const ta = document.createElement("textarea");
        ta.value = text;
        document.body.appendChild(ta);
        ta.select();
        document.execCommand("copy");
        ta.remove();
      }
      try {
        const data = await api("/api/copied", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: "{}",
        });
        if (data.state) applyState(state, data.state);
        else {
          state.sql_copied = true;
          state.sql_copied_n = (Number(state.sql_copied_n) || 0) + 1;
        }
      } catch {
        state.sql_copied = true;
        state.sql_copied_n = (Number(state.sql_copied_n) || 0) + 1;
      }
    }

    async function confirmDraft() {
      if (busy.value) return;
      busy.value = true;
      statusLine.value = "正在记录人工确认…";
      try {
        const data = await api("/api/confirm", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: "{}",
        });
        if (data.state) applyState(state, data.state);
        statusLine.value = data.error || "";
      } catch (e) {
        if (e.state) applyState(state, e.state);
        statusLine.value = String(e.message || e);
      } finally {
        busy.value = false;
      }
    }

    async function archiveDraft() {
      if (busy.value) return;
      busy.value = true;
      statusLine.value = "正在归档当前工单…";
      try {
        const data = await api("/api/archive-current", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: "{}",
        });
        if (data.state) applyState(state, data.state);
        statusLine.value = data.error || "当前工单已归档";
      } catch (e) {
        if (e.state) applyState(state, e.state);
        statusLine.value = String(e.message || e);
      } finally {
        busy.value = false;
      }
    }

    function who(role) {
      return { user: "你", agent: "取证", sys: "系统" }[role] || role;
    }

    function isMd(item) {
      return item && item.role !== "user" && looksLikeMarkdown(item.text);
    }

    function renderMd(text) {
      return renderMarkdown(text);
    }

    function reviewName(name) {
      return {
        scope: "对象和账期",
        numbers: "数字和 SQL",
        coverage: "诉求覆盖",
        conclusion: "结论边界",
        charge: "收费金额",
        notice: "提醒证据",
        usage: "用量证据",
      }[name] || name;
    }

    onMounted(() => {
      pull();
      setInterval(pull, 2000);
    });

    return {
      state,
      draft,
      busy,
      copyPending: computed(() => Boolean(state.sql) && !state.sql_copied),
      copyDone: computed(() => Boolean(state.sql) && Boolean(state.sql_copied)),
      copyLabel: computed(() => {
        if (!state.sql) return "一键复制 SQL";
        const round = Number(state.sql_round) || 1;
        if (!state.sql_copied) return "第" + round + "轮 · 未复制";
        const n = Number(state.sql_copied_n) || 1;
        if (n <= 1) return "第" + round + "轮 · 已复制";
        return "第" + round + "轮 · 已复制 " + n + " 次";
      }),
      copyHint: computed(() => {
        if (!state.sql) return "";
        if (!state.sql_copied) return "这轮 SQL 还没复制过。换包会变成新一轮。";
        return "这轮已经复制过。SQL 没换轮次就不会变。";
      }),
      threadEl,
      statusLine,
      processLabel: computed(() => PROCESS[state.process] || state.process || "空闲"),
      modeLabel: computed(() => {
        if (state.mode === "explore") {
          const n = Number(state.explore_n) || 1;
          return "探索 第" + n + "次";
        }
        if (state.mode === "reuse") return "复用已验证碎片";
        return "—";
      }),
      slotAcc: computed(() => state.slots.acc_num || state.acc_num || "—"),
      slotMonths: computed(() => (state.slots.months || state.months || []).join(",") || "—"),
      slotClaim: computed(() => state.slots.claim || state.claim || "—"),
      action: computed(() => state.action || {}),
      review: computed(() => state.review || {}),
      reviewPassed: computed(() => state.review && state.review.status === "passed"),
      reviewStatusLabel: computed(() => state.review && state.review.status === "passed" ? "通过" : "需要补证"),
      reviewName,
      who,
      isMd,
      renderMd,
      send,
      newChat,
      submitEmpty,
      copySql,
      confirmDraft,
      archiveDraft,
    };
  },
}).mount("#app");
