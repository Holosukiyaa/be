import { createApp, computed, onMounted, ref } from "/vendor/vue.esm-browser.prod.js";
import { NavBar, api, hay } from "/common.js";

createApp({
  components: { NavBar },
  setup() {
    const rows = ref([]);
    const q = ref("");
    const filtered = computed(() => {
      const n = q.value.trim().toLowerCase();
      return rows.value.filter((row) => !n || hay(row, ["kind", "name", "body"]).includes(n));
    });
    onMounted(async () => {
      const data = await api("/api/archive");
      rows.value = data.cards || [];
    });
    return { rows, q, filtered };
  },
}).mount("#app");
