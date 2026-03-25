import type { TaskSummary } from "../types";

interface Props {
  task: TaskSummary;
  onClick: (taskId: string) => void;
}

export function TaskCard({ task, onClick }: Props) {
  return (
    <button className="task-card" onClick={() => onClick(task.id)}>
      <span className="task-icon">{task.icon}</span>
      <div className="task-info">
        <h3>{task.name}</h3>
        <p>{task.description}</p>
        <span className="task-version">v{task.version}</span>
      </div>
    </button>
  );
}
