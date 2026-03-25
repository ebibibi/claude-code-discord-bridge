import { useState, useCallback } from "react";
import type { FieldResult } from "../types";

interface Props {
  fields: FieldResult[];
  editable: boolean;
  onFieldEdit: (index: number, newValue: string) => void;
}

export function ResultPreview({ fields, editable, onFieldEdit }: Props) {
  const [editingIndex, setEditingIndex] = useState<number | null>(null);

  const getConfidenceClass = (confidence: string) => {
    if (confidence === "high") return "confidence-high";
    if (confidence === "medium") return "confidence-medium";
    return "confidence-low";
  };

  const handleDoubleClick = useCallback(
    (index: number) => {
      if (editable) setEditingIndex(index);
    },
    [editable]
  );

  return (
    <div className="result-preview">
      <table>
        <thead>
          <tr>
            <th>#</th>
            <th>項目</th>
            <th>転記元の値</th>
            <th>出力値</th>
            <th>状態</th>
          </tr>
        </thead>
        <tbody>
          {fields.map((field, i) => (
            <tr key={field.name} className={field.warning ? "has-warning" : ""}>
              <td>{i + 1}</td>
              <td>{field.name}</td>
              <td className="source-value">{field.source_value}</td>
              <td
                className="output-value"
                onDoubleClick={() => handleDoubleClick(i)}
              >
                {editingIndex === i ? (
                  <input
                    type="text"
                    defaultValue={field.output_value}
                    autoFocus
                    onBlur={(e) => {
                      onFieldEdit(i, e.target.value);
                      setEditingIndex(null);
                    }}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") {
                        onFieldEdit(i, (e.target as HTMLInputElement).value);
                        setEditingIndex(null);
                      }
                    }}
                  />
                ) : (
                  field.output_value
                )}
              </td>
              <td>
                <span className={getConfidenceClass(field.confidence)}>
                  {field.warning ? `⚠️ ${field.warning}` : "✅"}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {editable && (
        <p className="edit-hint">値をダブルクリックして修正できます</p>
      )}
    </div>
  );
}
