const scenes = {
  sms: {
    meta: "案例一 · 待收窄结论 · 复用",
    slots: ["6687****", "202609", "人在黑龙江，称未出国；短信写国际漫游数据已达 15.30 澳门元"],
    remind: "15.30 只是 9 月 15 日的第一笔。同月 6 笔合计 22.50。不能拿短信金额结案，也不是用超。",
    sql: `-- 脱敏演示语句，不是生产 SQL
SELECT bill_month, card_no, event_name, visit_area, usage_mb, amount
  FROM demo_usage
 WHERE card_no = '6687****'
   AND bill_month = '202609'
   AND event_name LIKE '%漫游数据%';`,
    input: "【脱敏后的模拟录入】\n案例一。主号 6687****，账期 202609。\n客户人在黑龙江，称未出国。短信提示：国际漫游数据已达 15.30 澳门元。\n在用套餐含两地通。",
    thread: [
      ["user", "【模拟录入】案例一。主号 6687****。人在黑龙江，称未出国，短信却写国际漫游数据已达 15.30 澳门元。"],
      ["assistant", "先锁定主号和 202609。短信上的 15.30 不一定是整月合计。出漫游数据清单，按时间和拜访区看，不要直接写成用超。"],
      ["user", "【模拟贴回】\n日期 事件 拜访区 金额\n09-15 12:04 CtoG俄罗斯漫游数据 007 15.30\n其后 5 笔 同一事件 合计至 22.50\n同机最短 27 秒切到国内网号 460；09-14 起拜访区已是 0470"],
      ["assistant", "6 笔加起来 22.50。短信里的 15.30 是 9 月 15 日第一笔，后面还有 5 笔。拜访区 007 是俄罗斯方向。两地通不含俄罗斯。这是主卡切出去又切回来，不是用超了。"],
    ],
    nextTitle: "不能按短信上的 15.30 结案",
    nextDetail: "短信累计可以小于整月话单。结论停在：钱在主卡这 6 笔俄罗斯漫游数据上，第一笔是 15.30，合计 22.50。",
    nextClass: "stop",
    reviewClass: "needs_review",
    reviewStatus: "待收窄结论",
    reviewSummary: "短信金额和整月合计都在话单上。回复时把第一笔和后五笔分开说。",
    checks: [
      ["scope", "passed", "账期 202609、主号 6687**** 能在贴回里定位"],
      ["numbers", "passed", "15.30 对上第一笔；整月 6 笔合计 22.50"],
      ["coverage", "needs_review", "若只拿短信 15.30 结案，整月差额没有解释"],
      ["conclusion", "passed", "回复写的是切网，不是用超"],
    ],
    trail: [
      ["1", "done", "已贴回", "先看总账", "主号漫游清单", "贴回看到", "6 笔俄罗斯漫游数据合计 22.50；15.30 是第一笔"],
    ],
    compare: [
      ["未出国，不应有国际漫游", "已见到", "主卡有俄罗斯方向漫游数据，同机 27 秒切到国内网号"],
      ["短信已达 15.30", "只是第一笔", "整月合计 22.50，两地通不含该方向"],
    ],
  },
  pool: {
    meta: "案例二 · 核验通过，待人工确认 · 复用",
    slots: ["6663****", "202608", "主号未赴港；账单香港数据漫游 5.20；人多在新口岸"],
    remind: "主号整月只有澳门和内地，费用 0。5.20 在共享池副号 6887**** 的香港上网流量上。只查主号会错结。",
    sql: `-- 脱敏演示语句，不是生产 SQL
SELECT bill_month, card_no, card_role, event_name, usage_mb, amount
  FROM demo_usage
 WHERE pool_id = (SELECT pool_id FROM demo_pool WHERE card_no = '6663****')
   AND bill_month = '202608'
   AND amount > 0;`,
    input: "【脱敏后的模拟录入】\n案例二。主号 6663****，账期 202608。\n客户称主号未去香港，人多在新口岸。账单有香港数据漫游 5.20 澳门元。",
    thread: [
      ["user", "【模拟录入】案例二。主号 6663****。客户称没去香港，人多在新口岸，账单却有香港数据漫游 5.20。"],
      ["assistant", "工单上的号码不一定是出账的那张卡。先看主号这个月的清单。费用要是 0，先别回客户说没有这笔。"],
      ["user", "【模拟贴回 · 第一步】\n主号 6663****　澳门、内地　费用 0.00"],
      ["assistant", "主张 5.20 不在主号清单里。同一共享池还要看其他卡。只查主号算失败。"],
      ["user", "【模拟贴回 · 第二步】\n副号 6887****　香港上网　9 笔　410.75MB　5.20"],
      ["assistant", "5.20 在副号上，香港上网 9 笔，410.75MB。主号还是 0。草稿可以给人看，等同事点头再归档。"],
    ],
    nextTitle: "请确认：5.20 在副号上",
    nextDetail: "确认的是共享池副号这 9 笔，不是「主号没有去过香港所以账是错的」。",
    nextClass: "be_finish",
    reviewClass: "passed",
    reviewStatus: "待人工确认",
    reviewSummary: "主张金额已经落到副号行上。只查主号的那次贴回不能单独结案。",
    checks: [
      ["scope", "passed", "账期 202608；费用行上的号码是副号 6887****"],
      ["numbers", "passed", "主张 5.20 与副号 9 笔合计一致"],
      ["coverage", "passed", "香港数据漫游这笔有对应话单"],
      ["conclusion", "passed", "回复写的是副号上的 9 笔，不是主号没有这笔"],
    ],
    trail: [
      ["1", "done", "已贴回", "先看总账", "只查主号", "贴回看到", "6663**** 澳门和内地，费用 0"],
      ["2", "done", "已贴回", "再往下拆", "共享池", "贴回看到", "副号 6887**** 香港上网 9 笔 410.75MB = 5.20"],
    ],
    compare: [
      ["主号未赴港，人在新口岸", "已见到", "主号清单费用 0"],
      ["香港数据漫游 5.20", "金额对上", "副号 9 笔、410.75MB、5.20"],
    ],
  },
  voice: {
    meta: "案例三 · 核验通过，待人工确认 · 复用",
    slots: ["6630****", "202607、202608", "全澳通语音 58 元，称已取消数据；7 月另收 53.75，8 月另收 50.00"],
    remind: "没有副号。两个月的金额都能在澳门无线上网和少量国内卡流量上加平。语音套餐不含流量。减免是客情，不是错账。",
    sql: `-- 脱敏演示语句，不是生产 SQL
SELECT bill_month, card_no, event_name, usage_mb, amount
  FROM demo_usage
 WHERE card_no = '6630****'
   AND bill_month IN ('202607', '202608')
   AND amount > 0;`,
    input: "【脱敏后的模拟录入】\n案例三。号码 6630****。\n套餐是全澳通语音 58 元，客户称数据已取消。\n7 月另收数据 53.75，8 月另收 50.00，单位澳门元。",
    thread: [
      ["user", "【模拟录入】案例三。号码 6630****。全澳通语音 58 元，客户称已经取消数据，7 月仍收 53.75，8 月仍收 50.00。"],
      ["assistant", "先看有没有副号，再把两个月有钱的流量按科目加一下。"],
      ["user", "【模拟贴回】\n无副号\n202607 澳门无线上网 527.11MB 53.75\n202608 澳门无线上网 368.94MB 49.75\n202608 国内卡流量 1.58MB 0.25"],
      ["assistant", "7 月的 53.75 就是澳门无线上网这一条，527.11MB。8 月的 50 块是澳门流量 49.75，加上国内卡流量 0.25。客户办的是语音套餐，流量本来按量计。清单对得上。减不减免是另外的事。"],
    ],
    nextTitle: "请确认加总结果",
    nextDetail: "跟同事确认这两月的钱各自出在哪条话单上。减免另外处理。",
    nextClass: "be_finish",
    reviewClass: "passed",
    reviewStatus: "待人工确认",
    reviewSummary: "主张里的两笔金额都有科目对应。结论停在话单事实。",
    checks: [
      ["scope", "passed", "两个账期、号码 6630**** 能定位；没有另一张卡"],
      ["numbers", "passed", "53.75 对上 7 月；49.75+0.25 对上 8 月的 50.00"],
      ["coverage", "passed", "客户说的两笔额外数据费都有行"],
      ["conclusion", "passed", "回复写清了话单出处，减免另外处理"],
    ],
    trail: [
      ["1", "done", "已贴回", "先看总账", "有费科目", "贴回看到", "7 月澳门无线上网 53.75；8 月 49.75+0.25"],
    ],
    compare: [
      ["数据已经取消，不应再收费", "话单仍在", "两个月都有澳门无线上网按量费用"],
      ["7 月 53.75 / 8 月 50.00", "金额对上", "8 月是 49.75 的澳门流量加 0.25 的国内卡流量"],
    ],
  },
};

function esc(text) {
  return String(text)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function render(name) {
  const scene = scenes[name];
  document.getElementById("meta").textContent = scene.meta;
  const slots = document.querySelectorAll(".slots .slot-short span:last-child, .slots .slot-claim span:last-child");
  slots[0].textContent = scene.slots[0];
  slots[1].textContent = scene.slots[1];
  slots[2].textContent = scene.slots[2];
  document.getElementById("remind").textContent = scene.remind;
  document.getElementById("sql").textContent = scene.sql;
  document.getElementById("sim-input").value = scene.input;
  document.getElementById("thread").innerHTML = scene.thread.map(([role, text]) => {
    const who = role === "user" ? "运维" : "取证助手";
    return `<div class="msg ${role}"><div class="who">${who}</div><div class="bubble">${esc(text).replaceAll("\n", "<br>")}</div></div>`;
  }).join("");
  const next = document.getElementById("next");
  next.className = `next-box ${scene.nextClass}`;
  next.innerHTML = `<h2>现在做什么</h2><p class="next-title">${esc(scene.nextTitle)}</p><p class="next-detail">${esc(scene.nextDetail)}</p>`;
  const review = document.getElementById("review");
  review.className = `review-box ${scene.reviewClass}`;
  const names = { scope: "对象和账期", numbers: "金额", coverage: "主张覆盖", conclusion: "结论边界" };
  review.innerHTML = `
    <div class="review-head"><h2>交付核验</h2><span class="review-status">${esc(scene.reviewStatus)}</span></div>
    <div class="review-checks">
      ${scene.checks.map(([key, status, detail]) => `
        <div class="review-check ${status}">
          <span class="review-mark">${status === "passed" ? "✓" : "!"}</span>
          <div><strong>${names[key]}</strong><p>${esc(detail)}</p></div>
        </div>`).join("")}
    </div>
    <p class="review-summary">${esc(scene.reviewSummary)}</p>`;
  const bridge = scene.trail.length > 1 ? "主号清单对不上主张，改查共享池" : "";
  document.getElementById("path").innerHTML = `
    <header class="board-head"><h3>这一路查了什么</h3><p class="board-sub">脱敏回放。业务结构来自真实投诉，号码已打码。</p></header>
    <ol class="path-list">
      ${scene.trail.map(([n, kind, status, title, chip, seenLab, seen], i) => `
        <li>
          <article class="path-card ${kind}">
            <div class="path-mark"><span class="path-n">${n}</span><span class="path-st">${status}</span></div>
            <div class="path-body">
              <div class="path-name">${title}</div>
              <div class="path-chips"><span class="chip">${esc(chip)}</span></div>
              <p class="path-seen"><span>${seenLab}</span>${esc(seen)}</p>
            </div>
          </article>
          ${bridge && i < scene.trail.length - 1 ? `<div class="path-bridge"><span class="path-arrow"></span><p class="path-reason">${esc(bridge)}</p></div>` : ""}
        </li>`).join("")}
    </ol>`;
  document.getElementById("compare").innerHTML = `
    <header class="board-head"><h3>客户说的 vs 话单里的</h3><p class="board-sub">对上了，就是钱在这几条话单上。</p></header>
    <table class="compare-table">
      <thead><tr><th>客户说</th><th></th><th>话单里</th></tr></thead>
      <tbody>
        ${scene.compare.map(([say, mark, bill]) => `
          <tr>
            <td>${esc(say)}</td>
            <td class="compare-mark ${mark === "没对上" || mark === "只是第一笔" ? "no" : "yes"}">${esc(mark)}</td>
            <td>${esc(bill)}</td>
          </tr>`).join("")}
      </tbody>
    </table>`;
  for (const id of ["sms", "pool", "voice"]) {
    document.getElementById("btn-" + id).classList.toggle("on", id === name);
  }
}

document.getElementById("btn-sms").addEventListener("click", () => render("sms"));
document.getElementById("btn-pool").addEventListener("click", () => render("pool"));
document.getElementById("btn-voice").addEventListener("click", () => render("voice"));
render("sms");
