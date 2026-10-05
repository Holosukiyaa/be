import { createApp, onMounted, ref } from "/vendor/vue.esm-browser.prod.js";
import { NavBar, api } from "/common.js";

createApp({
  components: { NavBar },
  setup() {
    const rows = ref([]);
    onMounted(async () => {
      const data = await api("/api/archive");
      rows.value = data.strategies || [];
    });
    return { rows };
  },
}).mount("#app");
