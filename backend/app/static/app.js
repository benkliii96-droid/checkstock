const state = {
  stock: null,
  products: [],
  warehouses: [],
  fbsOrders: [],
  operations: [],
};

function newKey(prefix) {
  return `${prefix}-${crypto.randomUUID()}`;
}

function $(sel) {
  return document.querySelector(sel);
}

function showToast(message, kind = "ok") {
  const el = $("#toast");
  el.textContent = message;
  el.className = `toast ${kind}`;
  clearTimeout(showToast._t);
  showToast._t = setTimeout(() => el.classList.add("hidden"), 5000);
}

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const err = new Error(data.message || data.detail?.message || res.statusText);
    err.payload = data.detail && typeof data.detail === "object" ? data.detail : data;
    throw err;
  }
  return data;
}

function formatShortage(payload) {
  let msg = payload.message || "Недостаточно на выбранном ФФ";
  if (payload.alternatives?.length) {
    const alt = payload.alternatives
      .map((a) => `${a.warehouse_name}: ${a.available}`)
      .join(", ");
    msg += ` Альтернативы: ${alt}.`;
  } else if (typeof payload.total_available === "number") {
    msg += ` Общий доступный остаток: ${payload.total_available}.`;
  }
  return msg;
}

async function withFeedback(fn) {
  try {
    const result = await fn();
    if (result?.replayed) {
      showToast(result.detail || "Повтор: операция уже была учтена", "warn");
    } else if (result?.detail) {
      showToast(result.detail, "ok");
    } else {
      showToast("Готово", "ok");
    }
    await refreshAll();
    return result;
  } catch (e) {
    const payload = e.payload || {};
    if (payload.code === "insufficient_on_selected_warehouse") {
      showToast(formatShortage(payload), "warn");
    } else {
      showToast(payload.message || e.message, "err");
    }
    throw e;
  }
}

function fillSelect(select, items, { valueKey = "id", labelFn, includeDeleted = false } = {}) {
  const current = select.value;
  select.innerHTML = "";
  items
    .filter((i) => includeDeleted || !i.is_deleted)
    .forEach((item) => {
      const opt = document.createElement("option");
      opt.value = item[valueKey];
      opt.textContent = labelFn ? labelFn(item) : item.name;
      select.appendChild(opt);
    });
  if ([...select.options].some((o) => o.value === current)) {
    select.value = current;
  }
}

function fillProductSelects() {
  document.querySelectorAll('select[name="product_id"]').forEach((sel) => {
    fillSelect(sel, state.products, {
      labelFn: (p) => `${p.sku} — ${p.name}`,
    });
  });
}

function fillWarehouseSelects() {
  document.querySelectorAll('select[name="warehouse_id"], select[name="from_warehouse_id"], select[name="to_warehouse_id"]').forEach((sel) => {
    fillSelect(sel, state.warehouses, {
      labelFn: (w) => (w.is_deleted ? `${w.name} (удалён)` : w.name),
    });
  });
}

function renderStock() {
  const data = state.stock;
  if (!data) return;

  const thead = $("#stockTable thead");
  const tbody = $("#stockTable tbody");
  thead.innerHTML = "";
  tbody.innerHTML = "";

  const head = document.createElement("tr");
  head.innerHTML = `<th>Артикул</th><th>Товар</th>`;
  data.warehouses.forEach((w) => {
    const th = document.createElement("th");
    th.innerHTML = `${w.name}${w.is_deleted ? '<span class="badge">удалён</span>' : ""}<br><small>физ / дост / резерв</small>`;
    head.appendChild(th);
  });
  head.innerHTML += `<th>Итого<br><small>физ / дост / резерв</small></th>`;
  thead.appendChild(head);

  data.products.forEach((row) => {
    const tr = document.createElement("tr");
    let html = `<td><strong>${row.sku}</strong></td><td>${row.name}</td>`;
    row.cells.forEach((c) => {
      html += `<td class="num ${c.warehouse_deleted ? "deleted-col" : ""}">
        <div class="cell-stack">
          <span>${c.on_hand} / ${c.available} / ${c.reserved_fbs}</span>
        </div>
      </td>`;
    });
    html += `<td class="num"><strong>${row.total_on_hand} / ${row.total_available} / ${row.total_reserved_fbs}</strong></td>`;
    tr.innerHTML = html;
    tbody.appendChild(tr);
  });

  renderTransit("#transitTransfers", data.in_transit_transfers, (item) => {
    return {
      title: `${item.sku} · ${item.quantity} шт.`,
      meta: `${item.from_warehouse} → ${item.to_label}`,
      actions: [
        {
          label: "Принять",
          primary: true,
          onClick: () =>
            withFeedback(() =>
              api("/api/movements/transfer/receive", {
                method: "POST",
                body: JSON.stringify({
                  idempotency_key: newKey("transfer-receive"),
                  shipment_id: item.id,
                }),
              })
            ),
        },
      ],
    };
  });

  renderTransit("#transitFbo", data.in_transit_fbo, (item) => ({
    title: `${item.sku} · ${item.quantity} шт.`,
    meta: `${item.from_warehouse} → ${item.to_label}`,
    actions: [
      {
        label: "Принять на МП",
        primary: true,
        onClick: () =>
          withFeedback(() =>
            api("/api/fbo/receive", {
              method: "POST",
              body: JSON.stringify({
                idempotency_key: newKey("fbo-receive"),
                shipment_id: item.id,
              }),
            })
          ),
      },
    ],
  }));

  renderTransit("#transitFbs", data.in_transit_fbs, (item) => ({
    title: `${item.sku} · ${item.quantity} шт.`,
    meta: `${item.from_warehouse} → ${item.to_label}`,
    actions: [],
  }));

  renderTransit("#openTransfers", data.in_transit_transfers, (item) => ({
    title: `${item.sku} · ${item.quantity} шт.`,
    meta: `${item.from_warehouse} → ${item.to_label}`,
    actions: [
      {
        label: "Принять",
        primary: true,
        onClick: () =>
          withFeedback(() =>
            api("/api/movements/transfer/receive", {
              method: "POST",
              body: JSON.stringify({
                idempotency_key: newKey("transfer-receive"),
                shipment_id: item.id,
              }),
            })
          ),
      },
      {
        label: "Повторить приёмку",
        onClick: () =>
          withFeedback(async () => {
            const key = `replay-transfer-receive-${item.id}`;
            await api("/api/movements/transfer/receive", {
              method: "POST",
              body: JSON.stringify({ idempotency_key: key, shipment_id: item.id }),
            });
            return api("/api/movements/transfer/receive", {
              method: "POST",
              body: JSON.stringify({ idempotency_key: key, shipment_id: item.id }),
            });
          }),
      },
    ],
  }));
}

function renderTransit(selector, items, mapFn) {
  const root = $(selector);
  root.innerHTML = "";
  if (!items.length) {
    root.innerHTML = `<div class="empty">Пусто</div>`;
    return;
  }
  items.forEach((item) => {
    const view = mapFn(item);
    const el = document.createElement("div");
    el.className = "list-item";
    el.innerHTML = `
      <div>
        <div>${view.title}</div>
        <div class="meta">${view.meta}</div>
      </div>
      <div class="actions"></div>
    `;
    const actions = el.querySelector(".actions");
    view.actions.forEach((a) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.textContent = a.label;
      if (a.primary) btn.classList.add("primary");
      if (a.danger) btn.classList.add("danger");
      btn.addEventListener("click", a.onClick);
      actions.appendChild(btn);
    });
    root.appendChild(el);
  });
}

function renderWarehouses() {
  const root = $("#warehouseList");
  root.innerHTML = "";
  state.warehouses.forEach((w) => {
    const el = document.createElement("div");
    el.className = "list-item";
    el.innerHTML = `
      <div>
        <div><strong>${w.name}</strong>${w.is_deleted ? ' <span class="badge">удалён</span>' : ""}</div>
        <div class="meta">${w.is_deleted ? "Остатки сохранены, операции запрещены" : "Активный ФФ"}</div>
      </div>
      <div class="actions"></div>
    `;
    const actions = el.querySelector(".actions");
    if (!w.is_deleted) {
      const renameBtn = document.createElement("button");
      renameBtn.type = "button";
      renameBtn.textContent = "Переименовать";
      renameBtn.addEventListener("click", async () => {
        const name = prompt("Новое имя склада", w.name);
        if (!name) return;
        await withFeedback(() =>
          api(`/api/warehouses/${w.id}`, {
            method: "PATCH",
            body: JSON.stringify({ name }),
          })
        );
      });

      const delBtn = document.createElement("button");
      delBtn.type = "button";
      delBtn.className = "danger";
      delBtn.textContent = "Удалить";
      delBtn.addEventListener("click", async () => {
        if (!confirm(`Удалить склад «${w.name}»? Остатки и история сохранятся.`)) return;
        const key = newKey(`wh-del-${w.id}`);
        await withFeedback(() =>
          api(`/api/warehouses/${w.id}?idempotency_key=${encodeURIComponent(key)}`, {
            method: "DELETE",
          })
        );
      });

      actions.appendChild(renameBtn);
      actions.appendChild(delBtn);
    }
    root.appendChild(el);
  });
}

function renderFbs() {
  const root = $("#fbsOrders");
  root.innerHTML = "";
  if (!state.fbsOrders.length) {
    root.innerHTML = `<div class="empty">Нет заказов FBS</div>`;
    return;
  }
  state.fbsOrders.forEach((o) => {
    const el = document.createElement("div");
    el.className = "list-item";
    el.innerHTML = `
      <div>
        <div><strong>${o.sku}</strong> · ${o.quantity} шт. · ${o.status}</div>
        <div class="meta">${o.warehouse_name} → клиент</div>
      </div>
      <div class="actions"></div>
    `;
    const actions = el.querySelector(".actions");
    if (o.status === "reserved") {
      const shipBtn = document.createElement("button");
      shipBtn.type = "button";
      shipBtn.className = "primary";
      shipBtn.textContent = "Отправить";
      shipBtn.addEventListener("click", () =>
        withFeedback(() =>
          api("/api/fbs/ship", {
            method: "POST",
            body: JSON.stringify({ idempotency_key: newKey("fbs-ship"), order_id: o.id }),
          })
        )
      );

      const cancelBtn = document.createElement("button");
      cancelBtn.type = "button";
      cancelBtn.className = "danger";
      cancelBtn.textContent = "Отменить";
      cancelBtn.addEventListener("click", () =>
        withFeedback(() =>
          api("/api/fbs/cancel", {
            method: "POST",
            body: JSON.stringify({ idempotency_key: newKey("fbs-cancel"), order_id: o.id }),
          })
        )
      );

      const replayBtn = document.createElement("button");
      replayBtn.type = "button";
      replayBtn.textContent = "Повторить отправку";
      replayBtn.title = "Дважды с одним ключом идемпотентности";
      replayBtn.addEventListener("click", () =>
        withFeedback(async () => {
          const key = `replay-fbs-ship-${o.id}`;
          await api("/api/fbs/ship", {
            method: "POST",
            body: JSON.stringify({ idempotency_key: key, order_id: o.id }),
          });
          return api("/api/fbs/ship", {
            method: "POST",
            body: JSON.stringify({ idempotency_key: key, order_id: o.id }),
          });
        })
      );

      actions.append(shipBtn, cancelBtn, replayBtn);
    }
    root.appendChild(el);
  });
}

function renderFbo() {
  const root = $("#fboShipments");
  const items = state.stock?.in_transit_fbo || [];
  renderTransit("#fboShipments", items, (item) => ({
    title: `${item.sku} · ${item.quantity} шт.`,
    meta: `${item.from_warehouse} → ${item.to_label}`,
    actions: [
      {
        label: "Принять",
        primary: true,
        onClick: () =>
          withFeedback(() =>
            api("/api/fbo/receive", {
              method: "POST",
              body: JSON.stringify({
                idempotency_key: newKey("fbo-receive"),
                shipment_id: item.id,
              }),
            })
          ),
      },
      {
        label: "Повторить приёмку",
        onClick: () =>
          withFeedback(async () => {
            const key = `replay-fbo-receive-${item.id}`;
            await api("/api/fbo/receive", {
              method: "POST",
              body: JSON.stringify({ idempotency_key: key, shipment_id: item.id }),
            });
            return api("/api/fbo/receive", {
              method: "POST",
              body: JSON.stringify({ idempotency_key: key, shipment_id: item.id }),
            });
          }),
      },
    ],
  }));
}

function renderHistory() {
  const tbody = $("#historyTable tbody");
  tbody.innerHTML = "";
  state.operations.forEach((op) => {
    const tr = document.createElement("tr");
    const when = new Date(op.created_at).toLocaleString("ru-RU");
    tr.innerHTML = `
      <td>${when}</td>
      <td>${op.type}</td>
      <td>${op.product_sku ? `${op.product_sku} ${op.product_name}` : "—"}</td>
      <td class="num">${op.quantity}</td>
      <td>${op.from_warehouse || "—"}</td>
      <td>${op.to_warehouse || "—"}</td>
      <td>${op.note || ""}</td>
    `;
    tbody.appendChild(tr);
  });
}

async function refreshAll() {
  const [stock, products, warehousesList, fbsOrders, operations] = await Promise.all([
    api("/api/stock"),
    api("/api/products"),
    api("/api/warehouses?include_deleted=true"),
    api("/api/fbs/orders"),
    api("/api/operations?limit=100"),
  ]);
  state.stock = stock;
  state.products = products;
  state.warehouses = warehousesList;
  state.fbsOrders = fbsOrders;
  state.operations = operations;
  fillProductSelects();
  fillWarehouseSelects();
  renderStock();
  renderWarehouses();
  renderFbs();
  renderFbo();
  renderHistory();
}

function bindTabs() {
  document.querySelectorAll(".tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
      document.querySelectorAll(".panel").forEach((p) => p.classList.remove("active"));
      tab.classList.add("active");
      $(`#tab-${tab.dataset.tab}`).classList.add("active");
    });
  });
}

function bindForms() {
  $("#whCreateForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    await withFeedback(() =>
      api("/api/warehouses", {
        method: "POST",
        body: JSON.stringify({ name: fd.get("name") }),
      })
    );
    e.target.reset();
  });

  $("#receiptForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    await withFeedback(() =>
      api("/api/movements/receipt", {
        method: "POST",
        body: JSON.stringify({
          idempotency_key: newKey("receipt"),
          product_id: fd.get("product_id"),
          warehouse_id: fd.get("warehouse_id"),
          quantity: Number(fd.get("quantity")),
        }),
      })
    );
  });

  $("#transferShipForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    await withFeedback(() =>
      api("/api/movements/transfer/ship", {
        method: "POST",
        body: JSON.stringify({
          idempotency_key: newKey("transfer-ship"),
          product_id: fd.get("product_id"),
          from_warehouse_id: fd.get("from_warehouse_id"),
          to_warehouse_id: fd.get("to_warehouse_id"),
          quantity: Number(fd.get("quantity")),
        }),
      })
    );
  });

  $("#fbsReserveForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    await withFeedback(() =>
      api("/api/fbs/reserve", {
        method: "POST",
        body: JSON.stringify({
          idempotency_key: newKey("fbs-reserve"),
          product_id: fd.get("product_id"),
          warehouse_id: fd.get("warehouse_id"),
          quantity: Number(fd.get("quantity")),
        }),
      })
    );
  });

  $("#fboShipForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    await withFeedback(() =>
      api("/api/fbo/ship", {
        method: "POST",
        body: JSON.stringify({
          idempotency_key: newKey("fbo-ship"),
          product_id: fd.get("product_id"),
          warehouse_id: fd.get("warehouse_id"),
          quantity: Number(fd.get("quantity")),
        }),
      })
    );
  });

  $("#refreshBtn").addEventListener("click", () =>
    refreshAll().then(() => showToast("Данные обновлены", "ok"))
  );
}

bindTabs();
bindForms();
refreshAll().catch((e) => showToast(e.message, "err"));
