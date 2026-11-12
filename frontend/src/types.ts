export interface Subject {
  id: number;
  code: string;
  name: string;
  forum_url: string;
  exam_count: number;
  last_synced_at?: string | null;
}

export interface SubjectListResponse {
  items: Subject[];
  total: number;
  last_synced_at?: string | null;
}

export interface ExamItem {
  id: number;
  subject_id: number;
  title: string;
  url: string;
  exam_type: string;
  term?: string | null;
  post_date?: string | null;
  question_count: number;
}

export interface AuthStatus {
  logged_in: boolean;
  status_code?: 'logged_in' | 'not_logged_in' | 'profile_locked' | 'network_error';
  detail?: string;
  username?: string | null;
  expires_at?: string | null;
}

export interface LoginSession {
  state: 'idle' | 'opening' | 'waiting_for_user' | 'authenticated' | 'error' | 'cancelled';
  browser_used?: string | null;
  message?: string;
  error?: string | null;
  recent_logs?: string[];
  updated_at?: string | null;
}

export interface JobFile {
  filename: string;
  path: string;
  exam_title: string;
  questions_count: number;
  size_bytes: number;
  cached?: boolean;
  cached_at?: string | null;
}

export interface JobDetails {
  subject_code?: string;
  exam_type?: string;
  limit?: number;
  started_at?: string;
  completed_at?: string;
  files?: JobFile[];
  total_exams?: number;
  total_questions?: number;
}

export interface JobStatusResponse {
  job_id: string;
  subject_code: string;
  exam_type: string;
  exam_count: number;
  status: 'pending' | 'running' | 'completed' | 'failed';
  current_step?: string;
  progress_percentage: number;
  error_message?: string;
  result_file_path?: string;
  details?: JobDetails;
}

export interface SSEEvent {
  type: 'log' | 'progress' | 'completed' | 'error' | 'exam_completed';
  step?: string;
  message?: string;
  progress?: number;
  current_exam?: number;
  total_exams?: number;
  current_question?: number;
  total_questions?: number;
  files?: JobFile[];
  completed_file?: JobFile;
}

export interface AIProviderSetting {
  name: string;
  model: string;
  api_key_env: string;
  base_url?: string | null;
  enabled?: boolean;
  has_api_key?: boolean;
  status?: 'configured' | 'not_configured';
  key_source?: string | null;
  api_key?: string;
}

export interface AppSettings {
  export: {
    formats: string[];
    image_width_cm: number;
    image_zoom_percent?: number;
    highlight_low_confidence: boolean;
    answer_format: 'letter' | 'letter_keyword';
    merge: boolean;
    show_question_number?: boolean;
    show_separator_line?: boolean;
  };
  ai: {
    enabled: boolean;
    ensemble: boolean;
    max_ai_calls: number;
    backoff_seconds: number;
    max_retries: number;
    providers: AIProviderSetting[];
  };
  voting: {
    confident_min_ratio: number;
    confident_min_voters: number;
    multi_choice_threshold: number;
    vote_weight: string;
    ai_weight: number;
  };
  crawl: {
    delay_seconds: [number, number];
    concurrency: number;
    headless: boolean;
    max_retries: number;
    default_count: number;
  };
}


