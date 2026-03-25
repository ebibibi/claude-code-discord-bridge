import { useEffect, useState, useCallback } from "react";
import type { TaskSummary, TaskDetail } from "./types";
import { fetchTasks, fetchTaskDetail } from "./api";
import { TaskCard } from "./components/TaskCard";
import { TaskExecutor } from "./components/TaskExecutor";
import "./App.css";

type View = { type: "list" } | { type: "task"; task: TaskDetail };

function App() {
  const [tasks, setTasks] = useState<TaskSummary[]>([]);
  const [view, setView] = useState<View>({ type: "list" });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    fetchTasks()
      .then(setTasks)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  const handleTaskClick = useCallback(async (taskId: string) => {
    try {
      const detail = await fetchTaskDetail(taskId);
      setView({ type: "task", task: detail });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, []);

  const handleBack = useCallback(() => {
    setView({ type: "list" });
  }, []);

  // 部署別にグループ化
  const tasksByDepartment = tasks.reduce<Record<string, TaskSummary[]>>(
    (acc, task) => {
      const dept = task.department || "その他";
      const existing = acc[dept] || [];
      return { ...acc, [dept]: [...existing, task] };
    },
    {}
  );

  return (
    <div className="app">
      <header className="app-header">
        <h1>JBS AI 業務支援ツール</h1>
      </header>

      <main className="app-main">
        {error && <div className="error-banner">{error}</div>}

        {view.type === "list" && (
          <>
            {loading ? (
              <p className="loading">タスクを読み込み中...</p>
            ) : tasks.length === 0 ? (
              <p className="empty">利用可能なタスクがありません</p>
            ) : (
              Object.entries(tasksByDepartment).map(([dept, deptTasks]) => (
                <section key={dept} className="department-section">
                  <h2 className="department-title">{dept}</h2>
                  <div className="task-grid">
                    {deptTasks.map((task) => (
                      <TaskCard
                        key={task.id}
                        task={task}
                        onClick={handleTaskClick}
                      />
                    ))}
                  </div>
                </section>
              ))
            )}
          </>
        )}

        {view.type === "task" && (
          <TaskExecutor task={view.task} onBack={handleBack} />
        )}
      </main>

      <footer className="app-footer">
        <p>JBS AI 業務支援ツール — Powered by Claude</p>
      </footer>
    </div>
  );
}

export default App;
