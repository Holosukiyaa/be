export const PROCESS = {
  idle: "空闲",
  active: "已开单",
  packed: "待跑 SQL",
  ingested: "已贴回",
  verified: "已核对",
  drafted: "草稿待结档",
  review_pending: "待补证或收窄结论",
  reviewed: "核验通过，待人工确认",
  confirmed: "已确认，待归档",
  archived: "已结档",
  abandoned: "已废弃",
};

export function emptyState() {
  return {
    process: "idle",
    ticket_id: "",
    acc_num: "",
    months: [],
    claim: "",
    mode: "",
    explore_n: 0,
    reminder: "",
    uncovered: [],
    slots: { acc_num: "", months: [], claim: "" },
    sql: "",
    sql_round: 0,
    sql_copied: false,
    sql_copied_n: 0,
    ingest: "",
    action: {},
    review: {},
    confirmed: false,
    charts: {},
    trail: [],
    map_md: "",
    thread: [],
  };
}

function sameThread(a, b) {
  if (a === b) return true;
  if (!Array.isArray(a) || !Array.isArray(b) || a.length !== b.length) return false;
  for (let i = 0; i < a.length; i += 1) {
    if ((a[i].role || "") !== (b[i].role || "") || (a[i].text || "") !== (b[i].text || "")) {
      return false;
    }
  }
  return true;
}

export function applyState(state, s) {
  if (!s) return;
  const nextThread = Array.isArray(s.thread) ? s.thread : [];
  const keepThread = sameThread(state.thread, nextThread);
  state.process = s.process || "idle";
  state.ticket_id = s.ticket_id || "";
  state.acc_num = s.acc_num || "";
  state.months = s.months || [];
  state.claim = s.claim || "";
  state.mode = s.mode || "";
  state.explore_n = Number(s.explore_n) || 0;
  state.reminder = s.reminder || "";
  state.uncovered = s.uncovered || [];
  state.slots = s.slots || {
    acc_num: s.acc_num || "",
    months: s.months || [],
    claim: s.claim || "",
  };
  state.sql = s.sql || "";
  state.sql_round = Number(s.sql_round) || 0;
  state.sql_copied = Boolean(s.sql_copied);
  state.sql_copied_n = Number(s.sql_copied_n) || 0;
  state.ingest = s.ingest || "";
  state.action = s.action || {};
  state.review = s.review || {};
  state.confirmed = Boolean(s.confirmed);
  state.charts = s.charts || {};
  state.trail = Array.isArray(s.trail) ? s.trail : [];
  state.map_md = s.map_md || "";
  if (!keepThread) state.thread = nextThread;
}

const LAYER_NAME = {
  普查: "先看总账",
  下探: "再往下拆",
  通话取证: "查通话话单",
  锁定: "写下结论",
  取证: "取证",
};

export const TrailMap = {
  props: ["trail"],
  computed: {
    steps() {
      const list = Array.isArray(this.trail) ? this.trail : [];
      const last = list.length - 1;
      return list.map((step, i) => {
        const st = String(step.status || "");
        let kind = "wait";
        let status = "待跑";
        if (st === "locked") {
          kind = "lock";
          status = "已锁定";
        } else if (st === "ingested") {
          kind = "done";
          status = "已贴回";
        } else if (i === last) {
          kind = "on";
          status = "等你跑 SQL";
        }
        const next = list[i + 1];
        return {
          n: step.n || i + 1,
          kind,
          status,
          name: LAYER_NAME[step.name] || step.name || "取证",
          chips: step.labels || step.parts || [],
          why: step.why || "",
          seen: step.seen || "",
          bridge: next ? next.why || "继续往下查" : "",
        };
      });
    },
  },
  template: `
    <section v-if="steps.length" class="path">
      <header class="board-head">
        <h3>这一路查了什么</h3>
        <p class="board-sub">从上往下看。每一步：先跑 SQL，把结果贴回来，再决定要不要再查一层。</p>
      </header>
      <ol class="path-list">
        <li v-for="(step, i) in steps" :key="step.n">
          <article class="path-card" :class="step.kind">
            <div class="path-mark">
              <span class="path-n">{{ step.n }}</span>
              <span class="path-st">{{ step.status }}</span>
            </div>
            <div class="path-body">
              <div class="path-name">{{ step.name }}</div>
              <div v-if="step.chips.length" class="path-chips">
                <span v-for="(c, j) in step.chips" :key="j" class="chip">{{ c }}</span>
              </div>
              <p v-if="i === 0 && step.why" class="path-why">{{ step.why }}</p>
              <p v-if="step.seen" class="path-seen"><span>贴回看到</span>{{ step.seen }}</p>
              <p v-else-if="step.kind === 'on' || step.kind === 'wait'" class="path-seen is-empty"><span>贴回看到</span>还没有这一步的结果</p>
            </div>
          </article>
          <div v-if="step.bridge" class="path-bridge">
            <span class="path-arrow" aria-hidden="true"></span>
            <p class="path-reason">{{ step.bridge }}</p>
          </div>
        </li>
      </ol>
    </section>
  `,
};

export const EvidenceCharts = {
  props: ["charts"],
  computed: {
    hasCharts() {
      const c = this.charts || {};
      return (c.ok && c.ok.length) || (c.bad && c.bad.length) || (c.rows && c.rows.length);
    },
    pairs() {
      const c = this.charts || {};
      const out = [];
      for (const x of c.ok || []) {
        const money = String(x.label || "").includes("主张");
        out.push({
          say: x.label || "",
          bill: x.fact || "",
          mark: x.ok === false ? "没对上" : money ? "金额对上" : "已见到",
          ok: x.ok !== false,
        });
      }
      for (const x of c.bad || []) {
        out.push({
          say: x.label || "",
          bill: x.fact || "",
          mark: "对照",
          ok: false,
        });
      }
      return out;
    },
    rows() {
      return (this.charts && this.charts.rows) || [];
    },
  },
  template: `
    <section v-if="hasCharts" class="compare">
      <header class="board-head">
        <h3>客户说的 vs 话单里的</h3>
        <p class="board-sub">左边是投诉原话，右边是贴回格子加总出来的。对上了只说明钱在这些行里，不说明计费无误。</p>
      </header>
      <table class="compare-table">
        <thead>
          <tr>
            <th>客户说</th>
            <th></th>
            <th>话单里</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(row, i) in pairs" :key="i">
            <td>{{ row.say }}</td>
            <td class="compare-mark" :class="row.ok ? 'yes' : 'no'">{{ row.mark }}</td>
            <td>{{ row.bill }}</td>
          </tr>
        </tbody>
      </table>
      <div v-if="rows.length" class="time-block">
        <h4>有费行时间</h4>
        <ol class="time-rail">
          <li v-for="(r, i) in rows" :key="i">
            <div class="time-when">{{ r.tm || '—' }}</div>
            <div class="time-what">{{ r.event || '有费' }} · {{ r.sec || 0 }}秒 · {{ r.mop }}元</div>
          </li>
        </ol>
      </div>
    </section>
  `,
};

export async function paintMermaid(root) {
  const nodes = (root || document).querySelectorAll("pre.mermaid");
  if (!nodes.length) return;
  try {
    const mod = await import("https://cdn.jsdelivr.net/npm/mermaid@11.4.1/dist/mermaid.esm.min.mjs");
    const mermaid = mod.default;
    mermaid.initialize({ startOnLoad: false, theme: "neutral", securityLevel: "loose" });
    await mermaid.run({ nodes });
  } catch {
    /* 对照图 CSS 仍在 */
  }
}

export async function api(url, opts) {
  const r = await fetch(url, opts);
  let data = {};
  try {
    data = await r.json();
  } catch {
    data = { error: r.statusText };
  }
  if (!r.ok) {
    const err = new Error(data.error || r.statusText);
    err.state = data.state;
    throw err;
  }
  return data;
}

export function hay(row, keys) {
  return keys.map((k) => String(row[k] || "")).join(" ").toLowerCase();
}

export const NavBar = {
  props: ["page"],
  template: `
    <nav class="topnav">
      <a href="/" class="brand">计费取证</a>
      <a href="/" :class="{ on: page === 'work' }">工作台</a>
      <a href="/history" :class="{ on: page === 'history' }">工单</a>
      <a href="/cards" :class="{ on: page === 'cards' }">卡片</a>
      <a href="/gates" :class="{ on: page === 'gates' }">闸门</a>
    </nav>
  `,
};
