import { createApp, computed, onMounted, ref, nextTick } from "/vendor/vue.esm-browser.prod.js";
import { NavBar, api, hay, paintMermaid } from "/common.js";
import { looksLikeMarkdown, renderMarkdown } from "/md.js";

createApp({
  components: { NavBar },
  setup() {
    const rows = ref([]);
    const q = ref("");
    const filtered = computed(() => {
      const n = q.value.trim().toLowerCase();
      return rows.value.filter(
        (row) =>
          !n ||
          hay(row, ["ticket_id", "acc_num", "claim", "finding", "amounts", "note"]).includes(n)
      );
    });
    onMounted(async () => {
      const data = await api("/api/archive");
      rows.value = data.cases || [];
      await nextTick();
      paintMermaid(document);
    });
    return {
      rows,
      q,
      filtered,
      isMd: (text) => looksLikeMarkdown(text || ""),
      renderMd: (text) => renderMarkdown(text || ""),
    };
  },
}).mount("#app");
