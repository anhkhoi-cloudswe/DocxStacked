export type PlatformType = 'fuoverflow' | 'fuexam';

export interface Subject {
  id: number;
  code: string;
  name: string;
  forum_url: string;
  exam_count: number;
  last_synced_at?: string | null;
  node_id?: number | null;
  term_group?: string | null;
  platform?: PlatformType;
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
  question_count?: number | null;
  compiled?: boolean;
  has_file?: boolean;
  missing_file?: boolean;
  download_url?: string | null;
  compiled_at?: string | null;
  compiled_at_iso?: string | null;
  is_valid_exam?: boolean;
  warning?: string | null;
  sub_exam_count?: number | null;
  type_tags?: string[];
  platform?: PlatformType;
}

export interface SubjectExamTypesResponse {
  subject_code: string;
  platform: PlatformType;
  available_types: string[];
  has_fe: boolean;
  has_pe: boolean;
  counts: Record<string, number>;
}

export interface AuthStatus {
  logged_in: boolean;
  status_code?: 'logged_in' | 'not_logged_in' | 'profile_locked' | 'network_error';
  auth_source?: 'server' | 'extension';
  detail?: string;
  username?: string | null;
  expires_at?: string | null;
}

export interface FuexamAuthStatus {
  logged_in: boolean;
  status_code: 'logged_in' | 'expired' | 'not_logged_in' | 'logged_out';
  username?: string | null;
  detail?: string;
  auth_source?: 'headed_chromium' | 'extension' | null;
  extension_heartbeat_alive?: boolean;
  last_extension_heartbeat_age?: number | null;
}

export type FuexamLoginStatus =
  | 'idle'
  | 'starting'
  | 'waiting'
  | 'success'
  | 'failed'
  | 'timeout'
  | 'authenticated'
  | 'error'
  | 'cancelled';

export interface FuexamLoginSession {
  state: FuexamLoginStatus;
  stage?: string | null;
  run_id?: string | null;
  message: string;
  error?: string | null;
  started_at?: number | null;
  recent_logs?: string[];
}

export interface AnswerSourceSummary {
  image: number;
  comments: number;
  ai: number;
  total: number;
}

export interface LoginSession {
  state: 'idle' | 'opening' | 'waiting_for_user' | 'authenticated' | 'error' | 'cancelled';
  browser_used?: string | null;
  message?: string;
  error?: string | null;
  recent_logs?: string[];
  updated_at?: string | null;
}

export interface ExamResultItem {
  thread_id: number;
  exam_title: string;
  source_url?: string;
  filename?: string;
  status: 'completed' | 'completed_with_warnings' | 'failed';
  reason?: string;
  error_code?: string;
  fetch_failed_questions?: number[];
  questions_count?: number;
}

export interface JobFile {
  filename: string;
  path: string;
  exam_title: string;
  questions_count: number;
  size_bytes: number;
  cached?: boolean;
  cached_at?: string | null;
  platform?: string;
  status?: 'completed' | 'completed_with_warnings' | 'failed';
  confident_count?: number;
  weak_count?: number;
  conflict_count?: number;
  ai_count?: number;
  no_data_count?: number;
  image_count?: number;
  comment_count?: number;
  thread_id?: number;
  source_url?: string;
  source_breakdown?: Record<string, number>;
  review_needed_questions?: number[];
  image_warnings?: Record<string, string[]>;
  fetch_failed_questions?: number[];
}

export interface JobDetails {
  subject_code?: string;
  exam_type?: string;
  limit?: number;
  started_at?: string;
  completed_at?: string;
  files?: JobFile[];
  exam_results?: ExamResultItem[];
  failed_exams?: ExamResultItem[];
  crawl_metrics?: Record<string, any>;
  total_exams?: number;
  total_questions?: number;
  is_retryable?: boolean;
  error_code?: string;
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
  retry_attempt?: number;
  max_retries?: number;
  is_rate_limiting?: boolean;
  circuit_breaker?: boolean;
  wait_seconds?: number;
  files?: JobFile[];
  completed_file?: JobFile;
  exam_results?: ExamResultItem[];
  failed_exams?: ExamResultItem[];
  crawl_metrics?: Record<string, any>;
  is_retryable?: boolean;
  error_code?: string;
}

export interface AIProviderSetting {
  name: string;
  model: string;
  api_key_env: string;
  base_url?: string | null;
  enabled?: boolean;
  has_api_key?: boolean;
  masked_key?: string | null;
  status?: 'configured' | 'not_configured' | 'key_invalid';
  key_invalid?: boolean;
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
    multi_choice_format?: 'comma' | 'joined';
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
    fuexam_connect_timeout?: number;
    fuexam_read_timeout?: number;
    fuexam_max_retries?: number;
    fuexam_max_concurrency?: number;
    fuexam_min_delay_seconds?: number;
    fuexam_circuit_breaker_threshold?: number;
    fuexam_circuit_breaker_pause_seconds?: number;
  };
  storage?: {
    retention_days: number;
    auto_clean?: boolean;
  };
  extension?: {
    ingest_token?: string;
    extension_id?: string;
  };
}


