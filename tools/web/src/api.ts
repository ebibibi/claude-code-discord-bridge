import type { TaskSummary, TaskDetail, ExecutionResult } from "./types";

const API_BASE = "/api";

export async function fetchTasks(): Promise<TaskSummary[]> {
  const res = await fetch(`${API_BASE}/tasks`);
  if (!res.ok) throw new Error(`Failed to fetch tasks: ${res.status}`);
  return res.json();
}

export async function fetchTaskDetail(taskId: string): Promise<TaskDetail> {
  const res = await fetch(`${API_BASE}/tasks/${taskId}`);
  if (!res.ok) throw new Error(`Task not found: ${taskId}`);
  return res.json();
}

export async function executeTask(
  taskId: string,
  file: File,
  fileFieldName: string
): Promise<ExecutionResult> {
  const formData = new FormData();
  formData.append(fileFieldName, file);

  const res = await fetch(`${API_BASE}/tasks/${taskId}/execute`, {
    method: "POST",
    body: formData,
  });

  const data = await res.json();
  if (!res.ok) throw new Error(data.error || `Execution failed: ${res.status}`);
  return data;
}

export async function recordEdits(
  executionId: string,
  edits: Array<{ field_name: string; original_value: string; edited_value: string }>
): Promise<void> {
  await fetch(`${API_BASE}/executions/${executionId}/edits`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ edits }),
  });
}
