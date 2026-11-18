const form = document.querySelector("#add-task");
const titleInput = document.querySelector("#task-title");
const addButton = document.querySelector("#add-button");
const taskList = document.querySelector("#tasks");
const taskApi = taskList.dataset.apiUrl;
const summary = document.querySelector("#summary");
const empty = document.querySelector("#empty");
const errorNotice = document.querySelector("#error");
const filters = document.querySelectorAll("[data-filter]");
const accountForm = document.querySelector("#account-form");
const accountError = document.querySelector("#account-error");

let tasks = [];
let filter = "all";
let ready = false;
let saving = false;

async function api(path, method = "GET", data) {
  const options = { method };
  if (data !== undefined) {
    options.headers = { "Content-Type": "application/json" };
    options.body = JSON.stringify(data);
  }
  const response = await fetch(path, options);
  if (response.status === 204) return;
  const result = await response.json().catch(() => null);
  if (!response.ok || result === null) {
    throw new Error(result?.error || "暂时无法连接服务，请稍后重试。");
  }
  return result;
}

function showError(message) {
  errorNotice.textContent = message;
  errorNotice.hidden = !message;
}

function render() {
  const completed = tasks.filter((task) => task.done).length;
  summary.textContent = `${tasks.length - completed} 项待完成 · ${completed} 项已完成`;
  for (const button of filters) {
    button.setAttribute("aria-pressed", String(button.dataset.filter === filter));
  }

  const visible = tasks.filter((task) => filter === "all" || task.done === (filter === "done"));
  taskList.replaceChildren(...visible.map(taskRow));
  taskList.hidden = visible.length === 0;
  empty.hidden = !taskList.hidden;
  const emptyText = { all: "清单还是空的，添加第一项任务吧。", open: "没有待完成的任务。", done: "还没有已完成的任务。" };
  empty.textContent = emptyText[filter];
}

function taskRow(task) {
  const row = document.createElement("li");
  row.className = "task";
  row.dataset.task = task.id;

  const label = document.createElement("label");
  const checkbox = document.createElement("input");
  checkbox.type = "checkbox";
  checkbox.checked = task.done;
  checkbox.disabled = saving;
  const title = document.createElement("span");
  title.textContent = task.title;
  label.append(checkbox, title);

  checkbox.addEventListener("change", async () => {
    const done = checkbox.checked;
    await save(async () => {
      await api(`${taskApi}/${task.id}`, "PATCH", { done });
      task.done = done;
    });
    const updated = taskList.querySelector(`[data-task="${task.id}"] input`);
    (updated || document.querySelector('[aria-pressed="true"]')).focus();
  });

  const remove = document.createElement("button");
  remove.className = "remove-task";
  remove.type = "button";
  remove.disabled = saving;
  remove.textContent = "删除";
  remove.setAttribute("aria-label", `删除任务：${task.title}`);
  remove.addEventListener("click", async () => {
    await save(async () => {
      await api(`${taskApi}/${task.id}`, "DELETE");
      tasks = tasks.filter((item) => item.id !== task.id);
    });
    const updated = taskList.querySelector(`[data-task="${task.id}"] button`);
    (updated || titleInput).focus();
  });

  row.append(label, remove);
  return row;
}

function setSaving(pending) {
  saving = pending;
  addButton.disabled = pending || !ready;
  for (const control of taskList.querySelectorAll("button, input")) control.disabled = pending;
  for (const button of accountForm?.querySelectorAll("button") ?? []) button.disabled = pending;
}

async function save(change) {
  setSaving(true);
  showError("");
  try {
    await change();
  } catch (error) {
    showError(error.message);
  } finally {
    setSaving(false);
    render();
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!ready || saving) return;
  const title = titleInput.value.trim();
  if (!title) {
    showError("请输入任务内容。");
    titleInput.focus();
    return;
  }
  await save(async () => {
    const task = await api(taskApi, "POST", { title });
    tasks.unshift(task);
    if (titleInput.value.trim() === title) titleInput.value = "";
    if (filter === "done") filter = "all";
  });
  titleInput.focus();
});

for (const button of filters) {
  button.addEventListener("click", () => {
    if (!ready || saving) return;
    filter = button.dataset.filter;
    render();
  });
}

accountForm?.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (saving) return;
  const path = event.submitter?.getAttribute("formaction") || accountForm.action;
  setSaving(true);
  accountError.hidden = true;
  try {
    await api(path, "POST", Object.fromEntries(new FormData(accountForm)));
    window.location.reload();
  } catch (error) {
    accountError.textContent = error.message;
    accountError.hidden = false;
    setSaving(false);
  }
});

async function load() {
  try {
    tasks = await api(taskApi);
    ready = true;
    titleInput.disabled = false;
    addButton.disabled = saving;
    render();
  } catch {
    summary.textContent = "暂时无法加载任务";
    showError("请刷新页面后重试。");
  }
}

load();
