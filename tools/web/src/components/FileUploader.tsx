import { useCallback, useState } from "react";
import type { InputFileSpec } from "../types";

interface Props {
  fileSpec: InputFileSpec;
  onFileSelected: (file: File) => void;
}

export function FileUploader({ fileSpec, onFileSelected }: Props) {
  const [dragOver, setDragOver] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);

  const handleFile = useCallback(
    (file: File) => {
      const maxBytes = fileSpec.max_size_mb * 1024 * 1024;
      if (file.size > maxBytes) {
        alert(`ファイルサイズが上限（${fileSpec.max_size_mb}MB）を超えています`);
        return;
      }
      setSelectedFile(file);
      onFileSelected(file);
    },
    [fileSpec.max_size_mb, onFileSelected]
  );

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragOver(false);
      const file = e.dataTransfer.files[0];
      if (file) handleFile(file);
    },
    [handleFile]
  );

  const handleChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (file) handleFile(file);
    },
    [handleFile]
  );

  return (
    <div
      className={`file-uploader ${dragOver ? "drag-over" : ""}`}
      onDragOver={(e) => {
        e.preventDefault();
        setDragOver(true);
      }}
      onDragLeave={() => setDragOver(false)}
      onDrop={handleDrop}
    >
      {selectedFile ? (
        <div className="file-selected">
          <span>✅ {selectedFile.name}</span>
          <span className="file-size">
            ({(selectedFile.size / 1024).toFixed(0)}KB)
          </span>
        </div>
      ) : (
        <label className="file-label">
          <span>📎 {fileSpec.label}（{fileSpec.accept}）をドラッグ＆ドロップ</span>
          <span>または クリックして選択</span>
          <input
            type="file"
            accept={fileSpec.accept}
            onChange={handleChange}
            hidden
          />
        </label>
      )}
    </div>
  );
}
