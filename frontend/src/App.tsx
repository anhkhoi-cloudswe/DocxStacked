import React, { useState, useEffect, useCallback } from 'react';
import { Header } from './components/Header';
import { ScreenProgress } from './components/ScreenProgress';
import { ScreenResult } from './components/ScreenResult';
import { ScreenSelectSubject } from './components/ScreenSelectSubject';
import { ScreenSettings } from './components/ScreenSettings';
import { ScreenUserDocuments } from './components/ScreenUserDocuments';
import type { JobDetails, JobFile, JobStatusResponse } from './types';

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

  // Authentication gate state
  const [isAuthChecking, setIsAuthChecking] = useState<boolean>(true);
  const [isAuthenticated, setIsAuthenticated] = useState<boolean>(false);
  const [authDetail, setAuthDetail] = useState<string>('Đang kiểm tra trạng thái đăng nhập...');

  const checkAuthStatus = useCallback(async () => {
    try {
      const res = await fetch('/api/auth/status');
      if (res.ok) {
        const data = await res.json();
        setIsAuthenticated(Boolean(data.logged_in));
        setAuthDetail(data.detail || '');
      } else {
        setIsAuthenticated(false);
      }
    } catch {
      setIsAuthenticated(false);
    } finally {
      setIsAuthChecking(false);
    }
  }, []);

  useEffect(() => {
    checkAuthStatus();
    // Poll auth status every 3 seconds to auto-close when user logs in via browser/extension
    const authTimer = setInterval(checkAuthStatus, 3000);
    return () => clearInterval(authTimer);
  }, [checkAuthStatus]);

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
      alert(err.message || 'Lỗi kết nối tới máy chủ API');
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
      />

      <main style={{ flex: 1, padding: 'var(--space-6) var(--space-4)' }}>
        <div style={{ maxWidth: '1080px', margin: '0 auto' }}>
          {!isAuthChecking && !isAuthenticated ? (
            /* Blocking Login Gate Modal / Card */
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
                <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <rect x="3" y="11" width="18" height="11" rx="2" ry="2"></rect>
                  <path d="M7 11V7a5 5 0 0 1 10 0v4"></path>
                </svg>
              </div>

              <h2 style={{ fontSize: 'var(--text-xl)', fontWeight: 700, marginBottom: 'var(--space-2)' }}>
                Yêu cầu đăng nhập FUOverflow
              </h2>
              <p style={{ color: 'var(--text-muted)', fontSize: 'var(--text-sm)', marginBottom: 'var(--space-6)' }}>
                {authDetail || 'Vui lòng đăng nhập tài khoản FUOverflow để kích hoạt dashboard và sử dụng các tính năng.'}
              </p>

              <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
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
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path>
                    <polyline points="15 3 21 3 21 9"></polyline>
                    <line x1="10" y1="14" x2="21" y2="3"></line>
                  </svg>
                  Mở fuoverflow.com để đăng nhập
                </a>

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
                  Kiểm tra lại trạng thái
                </button>
              </div>

              <div
                style={{
                  marginTop: 'var(--space-6)',
                  padding: 'var(--space-3)',
                  backgroundColor: 'rgba(255, 255, 255, 0.03)',
                  borderRadius: 'var(--radius-sm)',
                  fontSize: 'var(--text-xs)',
                  color: 'var(--text-muted)',
                }}
              >
                Hộp thoại sẽ tự động mở trang Dashboard ngay khi Extension hoặc trình duyệt xác nhận đã đăng nhập.
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
    </div>
  );
};

export default App;
