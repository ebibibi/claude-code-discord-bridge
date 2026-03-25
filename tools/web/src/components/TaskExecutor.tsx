import { useState, useCallback } from "react";
import type { TaskDetail, ExecutionResult, FieldResult } from "../types";
import { executeTask, recordEdits } from "../api";
import { FileUploader } from "./FileUploader";
import { ResultPreview } from "./ResultPreview";

interface Props {
  task: TaskDetail;
  onBack: () => void;
}

type Phase = "upload" | "processing" | "result" | "error";

export function TaskExecutor({ task, onBack }: Props) {
  const [phase, setPhase] = useState<Phase>("upload");
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [result, setResult] = useState<ExecutionResult | null>(null);
  const [fields, setFields] = useState<FieldResult[]>([]);
  const [errorMessage, setErrorMessage] = useState("");
  const [edits, setEdits] = useState<
    Array<{ field_name: string; original_value: string; edited_value: string }>
  >([]);

  const handleExecute = useCallback(async () => {
    if (!selectedFile) return;
    setPhase("processing");
    setErrorMessage("");

    try {
      const fileFieldName = task.input_files[0]?.name || "file";
      const res = await executeTask(task.id, selectedFile, fileFieldName);
      setResult(res);
      setFields(res.preview?.fields || []);
      setPhase("result");
    } catch (err) {
      setErrorMessage(err instanceof Error ? err.message : String(err));
      setPhase("error");
    }
  }, [selectedFile, task]);

  const handleFieldEdit = useCallback(
    (index: number, newValue: string) => {
      const field = fields[index];
      if (field.output_value === newValue) return;

      const updatedFields = fields.map((f, i) =>
        i === index ? { ...f, output_value: newValue } : f
      );
      setFields(updatedFields);
      setEdits((prev) => [
        ...prev,
        {
          field_name: field.name,
          original_value: field.output_value,
          edited_value: newValue,
        },
      ]);
    },
    [fields]
  );

  const handleDownload = useCallback(async () => {
    if (!result) return;

    // 修正があれば記録
    if (edits.length > 0) {
      await recordEdits(result.execution_id, edits);
    }

    // CSVとしてダウンロード（将来的にはExcelテンプレート埋め込み）
    const csvRows = [
      ["項目", "値"].join(","),
      ...fields.map((f) => [f.name, `"${f.output_value}"`].join(",")),
    ];
    const blob = new Blob(["\uFEFF" + csvRows.join("\n")], {
      type: "text/csv;charset=utf-8",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `就業条件明示書_${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }, [result, fields, edits]);

  const warningCount = fields.filter((f) => f.warning).length;

  return (
    <div className="task-executor">
      <button className="back-button" onClick={onBack}>
        ← 戻る
      </button>
      <div className="task-header">
        <span className="task-icon-large">{task.icon}</span>
        <div>
          <h2>{task.name}</h2>
          <span className="task-meta">
            {task.department} / {task.category} / v{task.version}
          </span>
        </div>
      </div>
      <p className="task-description">{task.description}</p>

      {/* ステップ1: ファイルアップロード */}
      {(phase === "upload" || phase === "error") && (
        <section>
          <h3>ステップ 1: ファイルをアップロード</h3>
          {task.input_files.map((spec) => (
            <FileUploader
              key={spec.name}
              fileSpec={spec}
              onFileSelected={setSelectedFile}
            />
          ))}
          {selectedFile && (
            <button className="execute-button" onClick={handleExecute}>
              処理開始
            </button>
          )}
          {phase === "error" && (
            <div className="error-message">❌ {errorMessage}</div>
          )}
        </section>
      )}

      {/* 処理中 */}
      {phase === "processing" && (
        <section className="processing">
          <div className="spinner" />
          <p>処理中です。しばらくお待ちください...</p>
        </section>
      )}

      {/* ステップ2: 結果プレビュー */}
      {phase === "result" && result && (
        <section>
          <h3>ステップ 2: 結果を確認</h3>
          {warningCount > 0 && (
            <div className="warning-banner">
              ⚠️ {warningCount}件の要確認項目があります
            </div>
          )}
          <ResultPreview
            fields={fields}
            editable={task.preview.editable}
            onFieldEdit={handleFieldEdit}
          />
          <div className="result-actions">
            <button className="download-button" onClick={handleDownload}>
              ダウンロード
            </button>
            <span className="processing-time">
              処理時間: {(result.processing_time_ms / 1000).toFixed(1)}秒
            </span>
          </div>
        </section>
      )}
    </div>
  );
}
