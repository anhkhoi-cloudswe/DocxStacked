import React, { useState, useEffect, useCallback } from 'react';
import { Header } from './components/Header';
import { ScreenProgress } from './components/ScreenProgress';
import { ScreenResult } from './components/ScreenResult';
import { ScreenSelectSubject } from './components/ScreenSelectSubject';
import { ScreenSettings } from './components/ScreenSettings';
import { ScreenUserDocuments } from './components/ScreenUserDocuments';
import { ScreenSelectPlatform } from './components/ScreenSelectPlatform';
import { FuexamLoginModal } from './components/FuexamLoginModal';
import { FuoverflowLoginModal } from './components/FuoverflowLoginModal';
import { GlobalModalHost, alertModal, confirmModal } from './components/ModalDialog';
import type { JobDetails, JobFile, JobStatusResponse, PlatformType } from './types';

const DEFAULT_PINNED_EXTENSION_ID = 'kicplcdfmbcfjildbbimpfiljlmfokea';

interface EnqueueResult {
  success: boolean;
  ack?: boolean;
  queuedCount?: number;
  message?: string;
  error?: string;
  isBusy?: boolean;
  currentExamTitle?: string;
  runId?: string;
}

async function tryEnqueueViaExtension(
  subjectCode: string,
  examType: string,
  examIds?: number[],
  forceReplace: boolean = false,
  targetExtensionId?: string
): Promise<EnqueueResult> {
  const activeExtId = targetExtensionId || DEFAULT_PINNED_EXTENSION_ID;
  if (typeof window !== 'undefined' && (window as any).chrome?.runtime?.sendMessage) {
    try {
      let examsToEnqueue: any[] = [];
      if (examIds && examIds.length > 0) {
        const resp = await fetch(`/api/subjects/${subjectCode}/exams?type=${examType}`);
        if (resp.ok) {
          const allExams = await resp.json();
          examsToEnqueue = allExams.filter((e: any) => examIds.includes(e.id));
        }
      }

      const payloadExams =
        examsToEnqueue.length > 0
          ? examsToEnqueue.map((e: any) => ({
              title: e.title,
              url: e.url,
              exam_type: e.exam_type || examType,
              subject_code: subjectCode,
              question_count: e.question_count || undefined,
              term: e.term || '',
            }))
          : [
              {
                title: `${subjectCode} - Tự động`,
                url: `https://fuoverflow.com/threads/${subjectCode.toLowerCase()}/`,
                exam_type: examType,
                subject_code: subjectCode,
              },
            ];

      // Unique runId for this batch command
      const runId = 'run_' + Date.now().toString(36) + '_' + Math.random().toString(36).slice(2, 7);

      // Register run with backend for end-to-end verification
      try {
        await fetch('/api/ingest/register-run', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            runId,
            subjectCode,
            examUrls: payloadExams.map((e: any) => e.url),
          }),
        });
      } catch (e) {
        // Ignore backend offline if using extension independently
      }

      return new Promise<EnqueueResult>((resolve) => {
        let timedOut = false;
        const timer = setTimeout(() => {
          timedOut = true;
          resolve({
            success: false,
            error: 'Extension không phản hồi sau 5 giây.',
          });
        }, 5000);

        try {
          (window as any).chrome.runtime.sendMessage(
            activeExtId,
            {
              type: 'ENQUEUE_EXAMS',
              payload: {
                runId,
                subjectCode,
                exams: payloadExams,
                force: forceReplace,
              },
            },
            (res: any) => {
              if (timedOut) return;
              clearTimeout(timer);
              if ((window as any).chrome.runtime.lastError || !res) {
                const errMsg =
                  (window as any).chrome.runtime.lastError?.message ||
                  'Không thể kết nối đến Extension DocxStacked.';
                resolve({ success: false, error: errMsg });
              } else if (!res.ok) {
                resolve({
                  success: false,
                  error: res.error || 'Extension từ chối nhận đề.',
                  isBusy: res.error === 'QUEUE_RUNNING',
                  currentExamTitle: res.currentExamTitle,
                  message: res.message,
                });
              } else {
                resolve({
                  success: true,
                  ack: Boolean(res.ack),
                  runId,
                  queuedCount: res.queued_count || payloadExams.length,
                  message: res.message || `Đã nhận ${res.queued_count || payloadExams.length} đề, đang soạn`,
                });
              }
            }
          );
        } catch (err: any) {
          if (!timedOut) {
            clearTimeout(timer);
            resolve({ success: false, error: err.message || 'Lỗi gửi tin nhắn sang Extension.' });
          }
        }
      });
    } catch (err: any) {
      return { success: false, error: err.message || 'Lỗi chuẩn bị danh sách đề.' };
    }
  }
  return { success: false, error: 'Extension chưa được cài đặt hoặc không khả dụng trên trình duyệt này.' };
}

function getInitialPlatform(): PlatformType | null {
  if (typeof window === 'undefined') return null;
  try {
    const params = new URLSearchParams(window.location.search);
    const p = params.get('platform');
    if (p === 'fuoverflow' || p === 'fuexam') {
      return p as PlatformType;
    }
    if (params.get('source') === 'extension' || params.get('ext') === '1') {
      return 'fuoverflow';
    }
    const saved = localStorage.getItem('docxstacked_platform');
    if (saved === 'fuoverflow' || saved === 'fuexam') {
      return saved as PlatformType;
    }
  } catch (e) {
    console.warn('Error reading initial platform from localStorage:', e);
  }
  return null;
}

type ScreenType = 'select' | 'progress' | 'result' | 'settings' | 'documents';

export const App: React.FC = () => {
  const [platform, setPlatform] = useState<PlatformType | null>(getInitialPlatform);
  const [isFuexamLoggedIn, setIsFuexamLoggedIn] = useState<boolean>(false);
  const [fuexamUsername, setFuexamUsername] = useState<string>('');
  const [fuexamAuthSource, setFuexamAuthSource] = useState<'headed_chromium' | 'extension' | null>(null);
  const [hasInitialFuexamChecked, setHasInitialFuexamChecked] = useState<boolean>(false);
  const [isBackendReady, setIsBackendReady] = useState<boolean>(true);
  const [currentScreen, setCurrentScreen] = useState<ScreenType>('select');
  const [jobId, setJobId] = useState<string | null>(null);
  const [activeRunningJobId, setActiveRunningJobId] = useState<string | null>(null);
  const [subjectCode, setSubjectCode] = useState<string>('');
  const [examType, setExamType] = useState<'FE' | 'PE'>('FE');
  const [limit, setLimit] = useState<number>(4);
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [initialOpenLogin, setInitialOpenLogin] = useState<boolean>(false);
  const [loginTrigger, setLoginTrigger] = useState<number>(0);
  const [extensionId, setExtensionId] = useState<string>(DEFAULT_PINNED_EXTENSION_ID);

  useEffect(() => {
    fetch('/api/settings')
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (data?.extension?.extension_id) {
          setExtensionId(data.extension.extension_id);
        }
      })
      .catch(() => {});
  }, []);

  // Authentication gate state machine (strictly 4 states: checking, no_extension, logged_out, logged_in)
  type AuthGateState = 'checking' | 'no_extension' | 'logged_out' | 'logged_in';
  const [gateState, setGateState] = useState<AuthGateState>('checking');
  const [authUsername, setAuthUsername] = useState<string>('');
  const [authSource, setAuthSource] = useState<'server' | 'extension'>('server');

  // Diagnostics info for status card
  const [lastFailureReason, setLastFailureReason] = useState<string>('Đang khởi tạo kết nối...');

  const gateStateRef = React.useRef<AuthGateState>('checking');
  const consecutiveFailuresRef = React.useRef<number>(0);
  const firstFailureTimeRef = React.useRef<number | null>(null);
  const inFlightRef = React.useRef<boolean>(false);
  const lastAuthCheckTimeRef = React.useRef<number>(0);

  const transitionTo = useCallback((nextState: AuthGateState, reason: string) => {
    const prevState = gateStateRef.current;
    if (prevState !== nextState) {
      console.log(`[AuthGate] State changed: ${prevState} -> ${nextState} (Reason: ${reason})`);
      gateStateRef.current = nextState;
      setGateState(nextState);
    }
  }, []);

  const checkAuthStatus = useCallback(async (forced: boolean = false) => {
    if (inFlightRef.current) return;
    if (typeof document !== 'undefined' && document.hidden) return;
    const nowTs = Date.now();
    if (!forced && nowTs - lastAuthCheckTimeRef.current < 30000) return;
    lastAuthCheckTimeRef.current = nowTs;
    inFlightRef.current = true;

    try {
      // 1. Probe extension presence and forum auth
      const activeExtId = extensionId || DEFAULT_PINNED_EXTENSION_ID;
      let extDetected = false;
      let extAuthLoggedIn: boolean | null = null;
      let extAuthUsername: string | null = null;

      if (typeof window !== 'undefined' && (window as any).__DOCXSTACKED_AUTH_LOGGED_IN__ !== undefined) {
        extDetected = true;
        extAuthLoggedIn = Boolean((window as any).__DOCXSTACKED_AUTH_LOGGED_IN__);
        extAuthUsername = (window as any).__DOCXSTACKED_AUTH_USERNAME__ || 'Extension User';
      } else if (typeof window !== 'undefined' && ((window as any).DocxStackedExtensionPresent || (window as any).__DOCXSTACKED_TEST_MODE__)) {
        extDetected = true;
        if ((window as any).__DOCXSTACKED_AUTH_LOGGED_OUT__) {
          extAuthLoggedIn = false;
        } else {
          extAuthLoggedIn = true;
          extAuthUsername = 'Extension User';
        }
      } else if (typeof (window as any).chrome !== 'undefined' && (window as any).chrome?.runtime?.id) {
        extDetected = true;
      } else if (typeof (window as any).chrome !== 'undefined' && (window as any).chrome?.runtime?.sendMessage) {
        try {
          const pingResult = await new Promise<any>((resolve) => {
            let done = false;
            const timer = setTimeout(() => {
              if (!done) {
                done = true;
                resolve(null);
              }
            }, 1500);
            (window as any).chrome.runtime.sendMessage(
              activeExtId,
              { type: 'PING_EXTENSION' },
              (response: any) => {
                if (!done) {
                  done = true;
                  clearTimeout(timer);
                  if (response && response.ok && !((window as any).chrome?.runtime?.lastError)) {
                    resolve(response);
                  } else {
                    resolve(null);
                  }
                }
              }
            );
          });
          if (pingResult) {
            extDetected = true;
            if (pingResult.logged_in !== undefined) {
              extAuthLoggedIn = Boolean(pingResult.logged_in);
              extAuthUsername = pingResult.username || null;
            }
          }
        } catch {
          extDetected = false;
        }
      }

      // 2. Probe backend auth status
      let authRes: Response | null = null;
      let authData: any = null;
      try {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 3500);
        authRes = await fetch('/api/auth/status', { signal: controller.signal });
        clearTimeout(timeoutId);
        if (authRes.ok) {
          authData = await authRes.json();
        }
      } catch {
        // Backend offline or timeout
      }

      // 3. Resolve single source of truth for forumLoggedIn
      const isExtLoggedIn = extAuthLoggedIn === true;
      const isServerLoggedIn = Boolean(authRes && authRes.ok && authData && authData.logged_in);

      if (isExtLoggedIn || isServerLoggedIn) {
        consecutiveFailuresRef.current = 0;
        firstFailureTimeRef.current = null;
        const resolvedUser = (authData && authData.username) || extAuthUsername || 'Extension User';
        setAuthUsername(resolvedUser);
        const resolvedSource = isExtLoggedIn ? 'Extension (FUOverflow)' : (authData?.auth_source || 'server');
        setAuthSource(resolvedSource);
        transitionTo('logged_in', `Xác thực thành công từ ${resolvedSource}`);
        return;
      }

      let failureReason = '';
      let targetDegradedState: AuthGateState = 'no_extension';

      if (!extDetected) {
        failureReason = 'Không tìm thấy Extension DocxStacked trên trình duyệt này';
        targetDegradedState = 'no_extension';
      } else if (!authRes || !authData) {
        failureReason = 'Không thể kết nối đến máy chủ backend (lỗi mạng hoặc backend chưa bật)';
        targetDegradedState = 'no_extension';
      } else {
        failureReason = 'Chưa đăng nhập tài khoản FUOverflow trên Extension';
        targetDegradedState = 'logged_out';
      }

      setLastFailureReason(failureReason);
      consecutiveFailuresRef.current += 1;
      const count =
        typeof (window as any).__mockFailureCount === 'number'
          ? (window as any).__mockFailureCount
          : consecutiveFailuresRef.current;

      const now = Date.now();
      if (firstFailureTimeRef.current === null) {
        firstFailureTimeRef.current = now;
      }
      const elapsedMs =
        typeof (window as any).__mockFailureElapsed === 'number'
          ? (window as any).__mockFailureElapsed
          : (now - firstFailureTimeRef.current);

      // Anti-flicker rule: only transition to no_extension or logged_out
      // after >= 3 consecutive failures over >= 30 seconds.
      // A single failure keeps current state.
      if (count >= 3 && elapsedMs >= 30000) {
        transitionTo(
          targetDegradedState,
          `${failureReason} (${count} lần thất bại liên tiếp trong ${Math.round(elapsedMs / 1000)}s)`
        );
      } else {
        console.log(
          `[AuthGate] Lần kiểm tra thất bại (${count}/3, đã trôi qua ${Math.round(elapsedMs / 1000)}s/30s): ${failureReason}. Giữ nguyên trạng thái: ${gateStateRef.current}`
        );
      }
    } finally {
      inFlightRef.current = false;
    }
  }, [transitionTo]);

  const checkFuexamAuth = useCallback(async () => {
    try {
      const res = await fetch('/api/auth/fuexam/status');
      if (res.ok) {
        const data = await res.json();
        const logged = Boolean(data && data.logged_in);
        setIsFuexamLoggedIn(logged);
        setFuexamUsername(data?.username || '');
        setFuexamAuthSource(data?.auth_source || null);
      } else {
        setIsFuexamLoggedIn(false);
        setFuexamUsername('');
        setFuexamAuthSource(null);
      }
    } catch {
      setIsFuexamLoggedIn(false);
      setFuexamUsername('');
      setFuexamAuthSource(null);
    } finally {
      setHasInitialFuexamChecked(true);
    }
  }, []);

  // Giám sát trạng thái sẵn sàng của Backend (/api/health)
  useEffect(() => {
    let mounted = true;
    const checkHealth = async () => {
      try {
        const res = await fetch('/api/health');
        if (mounted) {
          setIsBackendReady(res.ok);
        }
      } catch {
        if (mounted) {
          setIsBackendReady(false);
        }
      }
    };
    checkHealth();
    const intervalMs = isBackendReady ? 15000 : 3000;
    const t = setInterval(checkHealth, intervalMs);
    return () => {
      mounted = false;
      clearInterval(t);
    };
  }, [isBackendReady]);

  const handleSelectPlatform = useCallback((selected: PlatformType) => {
    setPlatform(selected);
    try {
      localStorage.setItem('docxstacked_platform', selected);
    } catch (e) {
      console.warn('Error saving platform to localStorage:', e);
    }
    if (selected === 'fuexam') {
      checkFuexamAuth();
    } else {
      checkAuthStatus(true);
    }
  }, [checkFuexamAuth, checkAuthStatus]);

  useEffect(() => {
    if (platform === 'fuexam') {
      checkFuexamAuth();
    } else if (platform === 'fuoverflow') {
      checkAuthStatus(true);
    }

    // Poll auth status at most once every 30 seconds, paused when tab is hidden
    const authTimer = setInterval(() => {
      if (typeof document !== 'undefined' && document.hidden) return;
      if (platform === 'fuexam') {
        checkFuexamAuth();
      } else if (platform === 'fuoverflow') {
        checkAuthStatus();
      }
    }, 30000);

    if (typeof window !== 'undefined') {
      (window as any).__triggerCheckAuth = () => {
        if (platform === 'fuexam') {
          checkFuexamAuth();
        } else {
          checkAuthStatus(true);
        }
      };
    }
    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible') {
        // Tab became visible: background check if at least 30s has passed since last check
        const elapsed = Date.now() - lastAuthCheckTimeRef.current;
        if (elapsed >= 30000) {
          if (platform === 'fuexam') {
            checkFuexamAuth();
          } else {
            checkAuthStatus(true);
          }
        }
      }
    };
    document.addEventListener('visibilitychange', handleVisibilityChange);

    return () => {
      clearInterval(authTimer);
      document.removeEventListener('visibilitychange', handleVisibilityChange);
    };
  }, [platform, checkAuthStatus, checkFuexamAuth]);

  const handleLogout = useCallback(async () => {
    try {
      if (platform === 'fuexam') {
        await fetch('/api/auth/fuexam/logout', { method: 'POST' }).catch(() => {});
        setIsFuexamLoggedIn(false);
        setFuexamUsername('');
        setFuexamAuthSource(null);
      } else {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 2000);
        await fetch('/api/auth/logout', { method: 'POST', signal: controller.signal }).catch(() => {});
        clearTimeout(timeoutId);
        consecutiveFailuresRef.current = 3;
        firstFailureTimeRef.current = Date.now() - 31000;
        transitionTo('logged_out', 'Người dùng chủ động nhấn Đăng xuất');
      }
    } catch (e) {
      console.error('Logout error:', e);
    }
  }, [platform, transitionTo]);

  const isPlatformLoggedIn = platform === 'fuexam' ? isFuexamLoggedIn : gateState === 'logged_in';

  const handleOpenLogin = () => {
    setCurrentScreen('select');
    setLoginTrigger((prev) => prev + 1);
  };

  const [completedFiles, setCompletedFiles] = useState<JobFile[]>([]);
  const [completedDetails, setCompletedDetails] = useState<JobDetails | null>(null);

  // Sync state to URL and history
  const navigateTo = useCallback((screen: ScreenType, targetJobId?: string | null, replace: boolean = false) => {
    setCurrentScreen(screen);
    const activeJobId = targetJobId !== undefined ? targetJobId : jobId;

    let targetPath = '/';
    if (screen === 'settings') {
      targetPath = '/settings';
    } else if (screen === 'documents') {
      targetPath = '/documents';
    } else if (screen === 'progress' && activeJobId) {
      targetPath = `/progress?job_id=${encodeURIComponent(activeJobId)}`;
    } else if (screen === 'result' && activeJobId) {
      targetPath = `/result?job_id=${encodeURIComponent(activeJobId)}`;
    }

    const currentUrl = window.location.pathname + window.location.search;
    if (currentUrl !== targetPath) {
      if (replace) {
        window.history.replaceState({ screen, jobId: activeJobId }, '', targetPath);
      } else {
        window.history.pushState({ screen, jobId: activeJobId }, '', targetPath);
      }
    }
  }, [jobId]);

  // Handle URL change from browser (back/forward button or initial load)
  const syncFromUrl = useCallback(() => {
    const pathname = window.location.pathname.toLowerCase();
    const params = new URLSearchParams(window.location.search);
    const pJobId = params.get('job_id') || params.get('jobId');
    const pScreen = params.get('screen') as ScreenType | null;

    if (pathname.includes('/settings') || pScreen === 'settings') {
      setCurrentScreen('settings');
    } else if (pathname.includes('/documents') || pScreen === 'documents') {
      setCurrentScreen('documents');
    } else if (pathname.includes('/progress') || (pJobId && pScreen !== 'result' && !pathname.includes('/result'))) {
      if (pJobId) {
        setJobId(pJobId);
        fetch(`/api/jobs/${pJobId}`)
          .then((r) => (r.ok ? r.json() : null))
          .then((j) => {
            if (j) {
              setSubjectCode(j.subject_code || '');
              setExamType((j.exam_type as 'FE' | 'PE') || 'FE');
              setLimit(j.exam_count || 4);
              if (j.status === 'completed' && j.details?.files) {
                setCompletedFiles(j.details.files);
                setCompletedDetails({
                  subject_code: j.subject_code || '',
                  exam_type: j.exam_type || 'FE',
                  total_exams: j.details?.total_exams || j.details.files.length,
                  total_questions: j.details?.total_questions || 0,
                  files: j.details.files,
                  exam_results: j.details?.exam_results,
                  failed_exams: j.details?.failed_exams,
                  crawl_metrics: j.details?.crawl_metrics,
                });
                setCurrentScreen('result');
              }
            }
          })
          .catch(() => {});
      }
      setCurrentScreen('progress');
    } else if (pathname.includes('/result') || (pJobId && pScreen === 'result')) {
      if (pJobId) {
        setJobId(pJobId);
        // Load completed job details if not already present
        fetch(`/api/jobs/${pJobId}`)
          .then((r) => (r.ok ? r.json() : null))
          .then((j) => {
            if (j) {
              setSubjectCode(j.subject_code || '');
              setExamType((j.exam_type as 'FE' | 'PE') || 'FE');
              const files = j.details?.files || [];
              setCompletedFiles(files);
              setCompletedDetails({
                subject_code: j.subject_code || '',
                exam_type: j.exam_type || 'FE',
                total_exams: j.details?.total_exams || files.length,
                total_questions: j.details?.total_questions || 0,
                files: files,
                exam_results: j.details?.exam_results,
                failed_exams: j.details?.failed_exams,
                crawl_metrics: j.details?.crawl_metrics,
              });
            }
          })
          .catch(() => {});
      }
      setCurrentScreen('result');
    } else if (pathname.includes('/login') || window.location.search.includes('login=true')) {
      setCurrentScreen('select');
      // Remove ?login=true from address bar so refresh does not keep re-triggering the modal
      if (window.location.search.includes('login=true')) {
        window.history.replaceState({}, '', window.location.pathname || '/');
      }
      setInitialOpenLogin(true);
      setLoginTrigger((prev) => prev + 1);
    } else {
      setCurrentScreen('select');
    }

    const pPlatform = params.get('platform') as PlatformType | null;
    if (pPlatform === 'fuoverflow' || pPlatform === 'fuexam') {
      setPlatform(pPlatform);
      try {
        localStorage.setItem('docxstacked_platform', pPlatform);
      } catch (e) {}
    } else if (params.get('source') === 'extension' || params.get('ext') === '1') {
      setPlatform('fuoverflow');
      try {
        localStorage.setItem('docxstacked_platform', 'fuoverflow');
      } catch (e) {}
    }
  }, []);

  const handleSwitchPlatform = useCallback(() => {
    setPlatform(null);
    try {
      localStorage.removeItem('docxstacked_platform');
    } catch (e) {
      console.warn('Error clearing platform from localStorage:', e);
    }
    navigateTo('select', null);
  }, [navigateTo]);

  useEffect(() => {
    syncFromUrl();
    const handlePopState = () => syncFromUrl();
    window.addEventListener('popstate', handlePopState);

    // Poll for active running/pending jobs created in this user session
    // ONLY poll when there is an active running job in this session or progress screen is active!
    let checkJobsInFlight = false;
    let lastJobCheckTs = 0;

    const checkActiveJobs = () => {
      if (typeof document !== 'undefined' && document.hidden) return;
      if (checkJobsInFlight) return;
      const myJobId = sessionStorage.getItem('docxstacked_active_job_id');
      const hasJob = Boolean(myJobId || activeRunningJobId || currentScreen === 'progress');
      if (!hasJob) return;

      const nowTs = Date.now();
      if (nowTs - lastJobCheckTs < 30000) return;
      lastJobCheckTs = nowTs;
      checkJobsInFlight = true;

      fetch('/api/jobs/active')
        .then((r) => (r.ok ? r.json() : null))
        .then((activeJob) => {
          if (activeJob && activeJob.job_id) {
            // Only show indicator if the job was started or interacted with in this session
            if (myJobId === activeJob.job_id) {
              setActiveRunningJobId(activeJob.job_id);
              if (!jobId) setJobId(activeJob.job_id);
            } else {
              setActiveRunningJobId(null);
            }
          } else {
            setActiveRunningJobId(null);
            sessionStorage.removeItem('docxstacked_active_job_id');
          }
        })
        .catch(() => {})
        .finally(() => {
          checkJobsInFlight = false;
        });
    };

    if (sessionStorage.getItem('docxstacked_active_job_id')) {
      checkActiveJobs();
    }
    const jobPollInterval = setInterval(checkActiveJobs, 30000);

    return () => {
      window.removeEventListener('popstate', handlePopState);
      clearInterval(jobPollInterval);
    };
  }, [syncFromUrl, activeRunningJobId, jobId]);

  const handleStartJob = async (
    selectedSubject: string,
    selectedExamType: 'FE' | 'PE',
    selectedLimit: number,
    selectedExamIds?: number[],
    selectedExamTitles?: Record<string, string>
  ) => {
    setIsLoading(true);
    setSubjectCode(selectedSubject);
    setExamType(selectedExamType);
    setLimit(selectedLimit);

    if (platform === 'fuexam') {
      try {
        const resp = await fetch('/api/jobs', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            platform: 'fuexam',
            subject_code: selectedSubject,
            exam_type: selectedExamType,
            limit: selectedLimit,
            exam_ids: selectedExamIds && selectedExamIds.length > 0 ? selectedExamIds : undefined,
            exam_titles: selectedExamTitles && Object.keys(selectedExamTitles).length > 0 ? selectedExamTitles : undefined,
          }),
        });

        if (!resp.ok) {
          throw new Error(`Tạo tiến trình fuexam thất bại: HTTP ${resp.status}`);
        }

        const data: JobStatusResponse = await resp.json();
        sessionStorage.setItem('docxstacked_active_job_id', data.job_id);
        setJobId(data.job_id);
        setActiveRunningJobId(data.job_id);
        navigateTo('progress', data.job_id);
      } catch (err: any) {
        await alertModal({
          title: 'Lỗi tạo tiến trình fuexam',
          message: err.message || 'Lỗi kết nối tới máy chủ API',
          type: 'error',
        });
      } finally {
        setIsLoading(false);
      }
      return;
    }

    // Option 1: Send selected exams to Chrome extension via externally_connectable
    const extResult = await tryEnqueueViaExtension(selectedSubject, selectedExamType, selectedExamIds, false, extensionId);
    if (extResult.success) {
      setIsLoading(false);
      await alertModal({
        title: 'Đã gửi sang Extension',
        message: extResult.message || `Đã nhận ${extResult.queuedCount || 1} đề, đang soạn!`,
        type: 'success',
      });
      return;
    }

    // If extension is busy running another queue, ask user whether to replace or keep
    if (extResult.isBusy) {
      const busyTitle = extResult.currentExamTitle || 'Một đề thi khác';
      const shouldReplace = await confirmModal({
        title: 'Hàng đợi Extension đang chạy',
        message: `Extension đang soạn: "${busyTitle}".\n\nBạn có muốn THAY THẾ hoàn toàn bằng đề mới không?`,
        confirmText: 'Thay thế hoàn toàn',
        cancelText: 'Giữ hàng đợi cũ',
        isDanger: true,
      });

      if (shouldReplace) {
        const replaceResult = await tryEnqueueViaExtension(selectedSubject, selectedExamType, selectedExamIds, true, extensionId);
        if (replaceResult.success) {
          setIsLoading(false);
          await alertModal({
            title: 'Đã thay thế hàng đợi',
            message: replaceResult.message || `Đã thay thế và bắt đầu soạn ${replaceResult.queuedCount || 1} đề mới!`,
            type: 'success',
          });
          return;
        } else {
          setIsLoading(false);
          await alertModal({
            title: 'Lỗi thay thế',
            message: replaceResult.error || 'Không thể thay thế hàng đợi Extension.',
            type: 'error',
          });
          return;
        }
      } else {
        setIsLoading(false);
        return;
      }
    }

    // If extension returned explicit failure or timeout
    if (authSource === 'extension' || (window as any).chrome?.runtime?.sendMessage) {
      setIsLoading(false);
      await alertModal({
        title: 'Lỗi gửi đề sang Extension',
        message: extResult.error || 'Extension không phản hồi trong 5 giây. Vui lòng kiểm tra lại Side Panel.',
        type: 'error',
      });
      return;
    }

    // Option 2: Fallback to backend Playwright runner
    if (gateState !== 'logged_in') {
      setIsLoading(false);
      await alertModal({
        title: 'Dùng Extension để soạn đề',
        message:
          'Trình duyệt đang xác thực phiên qua Extension. Máy chủ chưa có phiên đăng nhập FUOverflow độc lập (Playwright).\n\n' +
          'Vui lòng mở Side Panel của Extension để soạn đề trực tiếp từ trình duyệt, hoặc đăng nhập FUOverflow trong tab Cài đặt để chạy cào nền trên máy chủ.',
        type: 'info',
      });
      return;
    }

    try {
      const resp = await fetch('/api/jobs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          subject_code: selectedSubject,
          exam_type: selectedExamType,
          limit: selectedLimit,
          exam_ids: selectedExamIds && selectedExamIds.length > 0 ? selectedExamIds : undefined,
        }),
      });

      if (!resp.ok) {
        throw new Error(`Tạo tiến trình thất bại: HTTP ${resp.status}`);
      }

      const data: JobStatusResponse = await resp.json();
      sessionStorage.setItem('docxstacked_active_job_id', data.job_id);
      setJobId(data.job_id);
      setActiveRunningJobId(data.job_id);
      navigateTo('progress', data.job_id);
    } catch (err: any) {
      await alertModal({
        title: 'Lỗi tạo tiến trình',
        message: err.message || 'Lỗi kết nối tới máy chủ API',
        type: 'error',
      });
    } finally {
      setIsLoading(false);
    }
  };

  const handleComplete = (files: JobFile[], details: JobDetails) => {
    setActiveRunningJobId(null);
    sessionStorage.removeItem('docxstacked_active_job_id');
    setCompletedFiles(files);
    setCompletedDetails(details);
    navigateTo('result', jobId);
  };

  const handleRestart = () => {
    setActiveRunningJobId(null);
    sessionStorage.removeItem('docxstacked_active_job_id');
    setJobId(null);
    setCompletedFiles([]);
    setCompletedDetails(null);
    navigateTo('select', null);
  };

  const handleRetryFailed = async () => {
    if (!jobId) return;
    try {
      const resp = await fetch(`/api/jobs/${encodeURIComponent(jobId)}/retry-failed`, { method: 'POST' });
      if (!resp.ok) {
        throw new Error(`Không thể thử lại các đề lỗi (HTTP ${resp.status})`);
      }
      sessionStorage.setItem('docxstacked_active_job_id', jobId);
      setActiveRunningJobId(jobId);
      navigateTo('progress', jobId);
    } catch (err: any) {
      await alertModal({
        title: 'Lỗi thử lại đề',
        message: err.message || 'Không thể gửi yêu cầu thử lại các đề lỗi.',
        type: 'error',
      });
    }
  };

  const [previousScreen, setPreviousScreen] = useState<ScreenType>('select');

  const handleOpenSettings = () => {
    setPreviousScreen(currentScreen === 'settings' ? 'select' : currentScreen);
    navigateTo('settings');
  };

  const handleCloseSettings = () => {
    navigateTo(previousScreen);
  };

  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column', backgroundColor: 'var(--bg-canvas)' }}>
      {!isBackendReady && (
        <div
          data-testid="backend-not-ready-banner"
          style={{
            backgroundColor: '#fef2f2',
            borderBottom: '1px solid #fecaca',
            padding: '10px 16px',
            color: '#991b1b',
            textAlign: 'center',
            fontSize: '13px',
            fontWeight: 600,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: '8px',
            position: 'sticky',
            top: 0,
            zIndex: 9999,
          }}
        >
          <span style={{ fontSize: '13px', fontWeight: 700 }}>[Lưu ý]</span>
          <span>Backend chưa sẵn sàng, đang thử lại...</span>
        </div>
      )}
      <Header
        currentScreen={currentScreen}
        activeJobId={activeRunningJobId || (currentScreen !== 'progress' ? jobId : null)}
        onNavigateSettings={handleOpenSettings}
        onNavigateDocuments={() => navigateTo('documents')}
        onNavigateHome={() => navigateTo('select', null)}
        onNavigateProgress={() => {
          const target = activeRunningJobId || jobId;
          if (target) navigateTo('progress', target);
        }}
        onOpenLogin={handleOpenLogin}
        isBlocked={!isPlatformLoggedIn}
        isLoggedIn={isPlatformLoggedIn}
        username={platform === 'fuexam' ? (fuexamUsername || 'Thành viên') : authUsername}
        onLogout={handleLogout}
        platform={platform}
        onSwitchPlatform={handleSwitchPlatform}
        authSource={platform === 'fuexam' ? fuexamAuthSource : authSource}
      />

      <main style={{ flex: 1, padding: 'var(--space-6) var(--space-4)' }}>
        <div style={{ maxWidth: '1080px', margin: '0 auto' }}>
          {!platform ? (
            <ScreenSelectPlatform onSelectPlatform={handleSelectPlatform} />
          ) : (
            <>
              {currentScreen === 'settings' && (
                <ScreenSettings
                  onBack={handleCloseSettings}
                  platform={platform}
                  onFuexamLogout={() => {
                    setIsFuexamLoggedIn(false);
                    setFuexamUsername('');
                    setFuexamAuthSource(null);
                  }}
                  fuexamAuthSource={fuexamAuthSource}
                />
              )}

              {currentScreen === 'documents' && (
                <ScreenUserDocuments
                  onBack={() => navigateTo('select', null)}
                  platform={platform}
                />
              )}

              {currentScreen === 'select' && (
                <ScreenSelectSubject
                  onStartJob={handleStartJob}
                  isLoading={isLoading}
                  initialOpenLogin={initialOpenLogin}
                  loginTrigger={loginTrigger}
                  isLoggedIn={isPlatformLoggedIn}
                  forumLoggedIn={isPlatformLoggedIn}
                  platform={platform}
                />
              )}

              {currentScreen === 'progress' && jobId && (
                <ScreenProgress
                  jobId={jobId}
                  subjectCode={subjectCode}
                  examType={examType}
                  limit={limit}
                  onComplete={handleComplete}
                  onCancel={handleRestart}
                  platform={platform}
                />
              )}

              {currentScreen === 'result' && completedDetails && (
                <ScreenResult
                  jobId={jobId || undefined}
                  files={completedFiles}
                  details={completedDetails}
                  onRestart={handleRestart}
                  onRetryFailed={handleRetryFailed}
                />
              )}

              {/* Modals for unauthenticated states */}
              {platform === 'fuoverflow' && (
                <FuoverflowLoginModal
                  isOpen={gateState !== 'logged_in'}
                  gateState={gateState}
                  onCheckAgain={() => checkAuthStatus(true)}
                  lastFailureReason={lastFailureReason}
                />
              )}

              {platform === 'fuexam' && (
                <FuexamLoginModal
                  isOpen={hasInitialFuexamChecked && !isFuexamLoggedIn}
                  isBackendReady={isBackendReady}
                  extensionId={extensionId}
                  onUpdateExtensionId={(newId) => setExtensionId(newId)}
                  onClose={handleSwitchPlatform}
                  onSuccess={() => {
                    setIsFuexamLoggedIn(true);
                    checkFuexamAuth();
                  }}
                />
              )}
            </>
          )}
        </div>
      </main>

      <footer
        style={{
          borderTop: '1px solid var(--border-subtle)',
          padding: 'var(--space-4)',
          textAlign: 'center',
          fontSize: 'var(--text-xs)',
          color: 'var(--text-muted)',
          backgroundColor: 'var(--bg-surface)',
        }}
      >
        <div style={{ maxWidth: '1080px', margin: '0 auto' }}>
          DocxStacked — Công cụ biên soạn tài liệu đề thi ôn tập sinh viên FPT
        </div>
      </footer>
      <GlobalModalHost />
    </div>
  );
};

export default App;
