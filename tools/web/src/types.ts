export interface InputFileSpec {
  name: string;
  label: string;
  accept: string;
  required: boolean;
  max_size_mb: number;
}

export interface OutputFileSpec {
  name: string;
  label: string;
  format: string;
}

export interface TaskSummary {
  id: string;
  name: string;
  description: string;
  department: string;
  category: string;
  icon: string;
  version: string;
  input_files: InputFileSpec[];
}

export interface TaskDetail extends TaskSummary {
  output_files: OutputFileSpec[];
  preview: { type: string; editable: boolean };
}

export interface FieldResult {
  name: string;
  source_value: string;
  output_value: string;
  confidence: string;
  warning: string;
}

export interface ExecutionResult {
  execution_id: string;
  task_id: string;
  status: "success" | "error";
  preview: {
    type: string;
    editable: boolean;
    fields: FieldResult[];
  };
  processing_time_ms: number;
  token_usage: { input_tokens: number; output_tokens: number };
  error?: string;
}
