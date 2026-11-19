import React, { useState, useEffect, useCallback } from 'react';
import { Header } from './components/Header';
import { ScreenProgress } from './components/ScreenProgress';
import { ScreenResult } from './components/ScreenResult';
import { ScreenSelectSubject } from './components/ScreenSelectSubject';
import { ScreenSettings } from './components/ScreenSettings';
import { ScreenUserDocuments } from './components/ScreenUserDocuments';
import { GlobalModalHost, alertModal } from './components/ModalDialog';
import type { JobDetails, JobFile, JobStatusResponse } from './types';

const EXTENSION_ID = 'kicplcdfmbcfjildbbimpfiljlmfokea';

async function tryEnqueueViaExtension(
  subjectCode: string,
  examType: string,
  examIds?: number[]
): Promise<boolean> {
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
              question_count: e.question_count || 40,
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

      return new Promise<boolean>((resolve) => {
        (window as any).chrome.runtime.sendMessage(
          EXTENSION_ID,
          {
            type: 'ENQUEUE_EXAMS',
            payload: {
              subjectCode,
              exams: payloadExams,
            },
          },
          (res: any) => {
            if ((window as any).chrome.runtime.lastError || !res || !res.ok) {
              resolve(false);
            } else {
              resolve(true);
            }
          }
        );
      });
    } catch {
      return false;
    }
  }
  return false;
}

type ScreenType = 'select' | 'progress' | 'result' | 'settings' | 'documents';

export const App: React.FC = () => {
  const [currentScreen, setCurrentScreen] = useState<ScreenType>('select');
  const [jobId, setJobId] = useState<string | null>(null);
  const [activeRunningJobId, setActiveRunningJobId] = useState<string | null>(null);
  const [subjectCode, setSubjectCode] = useState<string>('');
  const [examType, setExamType] = useState<'FE' | 'PE'>('FE');
  const [limit, setLimit] = useState<number>(4);
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [initialOpenLogin, setInitialOpenLogin] = useState<boolean>(false);
  const [loginTrigger, setLoginTrigger] = useState<number>(0);

  // Authentication gate state machine (strictly 4 states: checking, no_extension, logged_out, logged_in)
  type AuthGateState = 'checking' | 'no_extension' | 'logged_out' | 'logged_in';
  const [gateState, setGateState] = useState<AuthGateState>('checking');
  const [authUsername, setAuthUsername] = useState<string>('');
  const [authSource, setAuthSource] = useState<'server' | 'extension'>('server');

  // Diagnostics info for status card
  const [lastFailureReason, setLastFailureReason] = useState<string>('Đang khởi tạo kết nối...');
  const [lastCheckTime, setLastCheckTime] = useState<string>('');
  const [consecutiveFailures, setConsecutiveFailures] = useState<number>(0);

  const gateStateRef = React.useRef<AuthGateState>('checking');
  const consecutiveFailuresRef = React.useRef<number>(0);
  const firstFailureTimeRef = React.useRef<number | null>(null);
  const inFlightRef = React.useRef<boolean>(false);

  const transitionTo = useCallback((nextState: AuthGateState, reason: string) => {
    const prevState = gateStateRef.current;
    if (prevState !== nextState) {
      console.log(`[AuthGate] State changed: ${prevState} -> ${nextState} (Reason: ${reason})`);
      gateStateRef.current = nextState;
      setGateState(nextState);
    }
  }, []);

  const checkAuthStatus = useCallback(async () => {
    if (inFlightRef.current) return;
    inFlightRef.current = true;

    try {
      // 1. Probe backend auth status
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

      // If backend reports logged in, immediately unlock
      if (authRes && authRes.ok && authData && authData.logged_in) {
        consecutiveFailuresRef.current = 0;
        firstFailureTimeRef.current = null;
        setConsecutiveFailures(0);
        if (authData.username) setAuthUsername(authData.username);
        if (authData.auth_source) setAuthSource(authData.auth_source);
        transitionTo('logged_in', `Xác thực thành công từ ${authData.auth_source || 'server'}`);
        return;
      }

      // 2. Probe extension presence
      const PINNED_EXT_ID = 'kicplcdfmbcfjildbbimpfiljlmfokea';
      let extDetected = false;

      if (typeof window !== 'undefined' && ((window as any).DocxStackedExtensionPresent || (window as any).__DOCXSTACKED_TEST_MODE__)) {
        extDetected = true;
      } else if (typeof (window as any).chrome !== 'undefined' && (window as any).chrome?.runtime?.id) {
        extDetected = true;
      } else if (typeof (window as any).chrome !== 'undefined' && (window as any).chrome?.runtime?.sendMessage) {
        try {
          extDetected = await new Promise<boolean>((resolve) => {
            let done = false;
            const timer = setTimeout(() => {
              if (!done) {
                done = true;
                resolve(false);
              }
            }, 1500);
            (window as any).chrome.runtime.sendMessage(
              PINNED_EXT_ID,
              { type: 'PING_EXTENSION' },
              (response: any) => {
                if (!done) {
                  done = true;
                  clearTimeout(timer);
                  if (response && response.ok && !((window as any).chrome?.runtime?.lastError)) {
                    resolve(true);
                  } else {
                    resolve(false);
                  }
                }
              }
            );
          });
        } catch {
          extDetected = false;
        }
      }

      let failureReason = '';
      let targetDegradedState: AuthGateState = 'no_extension';

      if (!authRes || !authData) {
        failureReason = 'Không thể kết nối đến máy chủ backend (lỗi mạng hoặc backend chưa bật)';
        targetDegradedState = 'no_extension';
      } else if (!extDetected) {
        failureReason = 'Không tìm thấy Extension DocxStacked trên trình duyệt này';
        targetDegradedState = 'no_extension';
      } else {
        failureReason = 'Chưa đăng nhập tài khoản FUOverflow';
        targetDegradedState = 'logged_out';
      }

      const nowTimeStr = new Date().toLocaleTimeString();
      setLastCheckTime(nowTimeStr);
      setLastFailureReason(failureReason);

      consecutiveFailuresRef.current += 1;
      const count = consecutiveFailuresRef.current;
      setConsecutiveFailures(count);

      const now = Date.now();
      if (firstFailureTimeRef.current === null) {
        firstFailureTimeRef.current = now;
      }
      const elapsedMs = now - firstFailureTimeRef.current;

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

  useEffect(() => {
    checkAuthStatus();
    // Poll auth status every 5 seconds to detect login
    const authTimer = setInterval(checkAuthStatus, 5000);

    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible') {
        // Tab became visible: background check without flashing error UI
        console.log('[AuthGate] Tab trở lại (visible): Kiểm tra ngầm trạng thái phiên...');
        checkAuthStatus();
      }
    };
    document.addEventListener('visibilitychange', handleVisibilityChange);

    return () => {
      clearInterval(authTimer);
      document.removeEventListener('visibilitychange', handleVisibilityChange);
    };
  }, [checkAuthStatus]);

  const handleLogout = useCallback(async () => {
    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 2000);
      await fetch('/api/auth/logout', { method: 'POST', signal: controller.signal }).catch(() => {});
      clearTimeout(timeoutId);
    } catch (e) {
      console.error('Logout error:', e);
    } finally {
      consecutiveFailuresRef.current = 3;
      firstFailureTimeRef.current = Date.now() - 31000;
      transitionTo('logged_out', 'Người dùng chủ động nhấn Đăng xuất');
      window.location.reload();
    }
  }, [transitionTo]);

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
  }, []);

  useEffect(() => {
    syncFromUrl();
    const handlePopState = () => syncFromUrl();
    window.addEventListener('popstate', handlePopState);

    // Poll for active running/pending jobs created in this user session
    const checkActiveJobs = () => {
      fetch('/api/jobs/active')
        .then((r) => (r.ok ? r.json() : null))
        .then((activeJob) => {
          if (activeJob && activeJob.job_id) {
            // Only show indicator if the job was started or interacted with in this session
            const myJobId = sessionStorage.getItem('docxstacked_active_job_id');
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
        .catch(() => {});
    };

    checkActiveJobs();
    const jobPollInterval = setInterval(checkActiveJobs, 5000);

    return () => {
      window.removeEventListener('popstate', handlePopState);
      clearInterval(jobPollInterval);
    };
  }, [syncFromUrl, activeRunningJobId, jobId]);

  const handleStartJob = async (
    selectedSubject: string,
    selectedExamType: 'FE' | 'PE',
    selectedLimit: number,
    selectedExamIds?: number[]
  ) => {
    setIsLoading(true);
    setSubjectCode(selectedSubject);
    setExamType(selectedExamType);
    setLimit(selectedLimit);

    // Option 1: Send selected exams to Chrome extension via externally_connectable
    const sentToExt = await tryEnqueueViaExtension(selectedSubject, selectedExamType, selectedExamIds);
    if (sentToExt) {
      setIsLoading(false);
      await alertModal({
        title: 'Đã gửi sang Extension',
        message: 'Danh sách đề đã được gửi thành công sang Side Panel của Extension DocxStacked để bắt đầu cào và xuất Word!',
        type: 'success',
      });
      return;
    }

    // Option 2: Fallback to backend Playwright runner
    if (authSource === 'extension' || gateState !== 'logged_in') {
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
        isBlocked={gateState !== 'logged_in'}
        isLoggedIn={gateState === 'logged_in'}
        username={authUsername}
        onLogout={handleLogout}
      />

      <main style={{ flex: 1, padding: 'var(--space-6) var(--space-4)' }}>
        <div style={{ maxWidth: '1080px', margin: '0 auto' }}>
          {gateState !== 'logged_in' ? (
            /* Blocking Login Gate Modal / Card with exactly 3 non-logged-in states */
            <div
              style={{
                backgroundColor: 'var(--bg-surface)',
                border: '1px solid var(--border-subtle)',
                borderRadius: 'var(--radius-lg)',
                padding: 'var(--space-8)',
                textAlign: 'center',
                maxWidth: '560px',
                margin: 'var(--space-12) auto',
                boxShadow: 'var(--shadow-lg, 0 10px 25px rgba(0,0,0,0.3))',
              }}
            >
              <div
                style={{
                  width: '56px',
                  height: '56px',
                  margin: '0 auto var(--space-4)',
                  borderRadius: '50%',
                  backgroundColor: 'rgba(99, 102, 241, 0.15)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  color: 'var(--primary, #6366f1)',
                }}
              >
                {gateState === 'checking' && (
                  <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ animation: 'spin 1.5s linear infinite' }}>
                    <path d="M21 12a9 9 0 1 1-6.219-8.56"></path>
                  </svg>
                )}
                {gateState === 'no_extension' && (
                  <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"></path>
                    <polyline points="3.27 6.96 12 12.01 20.73 6.96"></polyline>
                    <line x1="12" y1="22.08" x2="12" y2="12"></line>
                  </svg>
                )}
                {gateState === 'logged_out' && (
                  <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <rect x="3" y="11" width="18" height="11" rx="2" ry="2"></rect>
                    <path d="M7 11V7a5 5 0 0 1 10 0v4"></path>
                  </svg>
                )}
              </div>

              {gateState === 'checking' && (
                <>
                  <h2 style={{ fontSize: 'var(--text-xl)', fontWeight: 700, marginBottom: 'var(--space-2)' }}>
                    Đang kiểm tra
                  </h2>
                  <p style={{ color: 'var(--text-muted)', fontSize: 'var(--text-sm)', marginBottom: 'var(--space-6)' }}>
                    Đang kết nối backend và kiểm tra trạng thái phiên làm việc...
                  </p>
                </>
              )}

              {gateState === 'no_extension' && (
                <>
                  <h2 style={{ fontSize: 'var(--text-xl)', fontWeight: 700, marginBottom: 'var(--space-2)' }}>
                    Chưa thấy extension trên trình duyệt này
                  </h2>
                  <p style={{ color: 'var(--text-muted)', fontSize: 'var(--text-sm)', marginBottom: 'var(--space-4)' }}>
                    Mở bằng trình duyệt đã cài extension DocxStacked để tiếp tục.
                  </p>
                  <div
                    style={{
                      margin: '0 auto var(--space-6)',
                      padding: 'var(--space-3) var(--space-4)',
                      backgroundColor: 'var(--bg-subtle, rgba(0,0,0,0.03))',
                      borderRadius: 'var(--radius-md)',
                      border: '1px solid var(--border-subtle)',
                      fontSize: 'var(--text-xs)',
                      textAlign: 'left',
                      color: 'var(--text-secondary)',
                      lineHeight: 1.6,
                    }}
                  >
                    <div><strong style={{ color: 'var(--text-primary)' }}>Chẩn đoán kết nối:</strong></div>
                    <div>• Lý do lỗi cuối cùng: <span style={{ fontFamily: 'var(--font-mono)' }}>{lastFailureReason || 'Không có'}</span></div>
                    <div>• Thời điểm kiểm tra cuối: <span style={{ fontFamily: 'var(--font-mono)' }}>{lastCheckTime || 'Chưa kiểm tra'}</span></div>
                    <div>• Số lần thất bại liên tiếp: <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 600 }}>{consecutiveFailures}</span></div>
                  </div>
                </>
              )}

              {gateState === 'logged_out' && (
                <>
                  <h2 style={{ fontSize: 'var(--text-xl)', fontWeight: 700, marginBottom: 'var(--space-2)' }}>
                    Chưa đăng nhập FUOverflow
                  </h2>
                  <p style={{ color: 'var(--text-muted)', fontSize: 'var(--text-sm)', marginBottom: 'var(--space-6)' }}>
                    Vui lòng đăng nhập tài khoản FUOverflow để sử dụng hệ thống.
                  </p>
                </>
              )}

              <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
                {gateState === 'logged_out' && (
                  <a
                    href="https://fuoverflow.com/login"
                    target="_blank"
                    rel="noopener noreferrer"
                    style={{
                      display: 'inline-flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      gap: 'var(--space-2)',
                      padding: 'var(--space-3) var(--space-6)',
                      backgroundColor: 'var(--primary, #6366f1)',
                      color: '#fff',
                      borderRadius: 'var(--radius-md)',
                      fontWeight: 600,
                      fontSize: 'var(--text-sm)',
                      textDecoration: 'none',
                      transition: 'background-color 0.15s ease',
                    }}
                  >
                    Mở fuoverflow.com để đăng nhập
                  </a>
                )}

                <button
                  type="button"
                  onClick={checkAuthStatus}
                  style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    gap: 'var(--space-2)',
                    padding: 'var(--space-2) var(--space-4)',
                    backgroundColor: 'transparent',
                    border: '1px solid var(--border-subtle)',
                    color: 'var(--text-muted)',
                    borderRadius: 'var(--radius-md)',
                    fontSize: 'var(--text-xs)',
                    cursor: 'pointer',
                  }}
                >
                  Kiểm tra lại
                </button>
              </div>
            </div>
          ) : (
            <>
              {currentScreen === 'settings' && (
                <ScreenSettings onBack={handleCloseSettings} />
              )}

              {currentScreen === 'documents' && (
                <ScreenUserDocuments onBack={() => navigateTo('select', null)} />
              )}

              {currentScreen === 'select' && (
                <ScreenSelectSubject
                  onStartJob={handleStartJob}
                  isLoading={isLoading}
                  initialOpenLogin={initialOpenLogin}
                  loginTrigger={loginTrigger}
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
                />
              )}

              {currentScreen === 'result' && completedDetails && (
                <ScreenResult
                  jobId={jobId || undefined}
                  files={completedFiles}
                  details={completedDetails}
                  onRestart={handleRestart}
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
