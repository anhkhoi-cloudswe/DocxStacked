import React, { useEffect, useRef, useState } from 'react';
import type { JobDetails, JobFile, SSEEvent } from '../types';

interface Props {
  jobId: string;
  subjectCode: string;
  examType: string;
  limit: number;
  onComplete: (files: JobFile[], details: JobDetails) => void;
  onCancel: () => void;
}

interface LogEntry {
  id: string;
  time: string;
  text: string;
  step?: string;
}

export const ScreenProgress: React.FC<Props> = ({
  jobId,
  subjectCode,
  examType,
  limit,
  onComplete,
  onCancel,
}) => {
  const [progress, setProgress] = useState<number>(0);
  const [currentStep, setCurrentStep] = useState<string>('Khởi tạo tiến trình...');
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [currentExam, setCurrentExam] = useState<number>(0);
  const [totalExams, setTotalExams] = useState<number>(limit);
  const [currentQuestion, setCurrentQuestion] = useState<number>(0);
  const [totalQuestions, setTotalQuestions] = useState<number>(0);
  const [completedFiles, setCompletedFiles] = useState<JobFile[]>([]);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [isResuming, setIsResuming] = useState<boolean>(false);
  const [reconnectTrigger, setReconnectTrigger] = useState<number>(0);

  // Re-login Modal State
  const [showLoginModal, setShowLoginModal] = useState<boolean>(false);
  const [loginMode, setLoginMode] = useState<'account' | 'cookie'>('account');
  const [usernameInput, setUsernameInput] = useState<string>('');
  const [passwordInput, setPasswordInput] = useState<string>('');
  const [cookieInput, setCookieInput] = useState<string>('');
  const [isLoggingIn, setIsLoggingIn] = useState<boolean>(false);
  const [loginMessage, setLoginMessage] = useState<string | null>(null);
  const [loginError, setLoginError] = useState<string | null>(null);

  // Handle Escape key to close modal
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && showLoginModal) {
        setShowLoginModal(false);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [showLoginModal]);

  const logsEndRef = useRef<HTMLDivElement>(null);

  const handleLoginAccount = async () => {
    if (!usernameInput.trim() || !passwordInput.trim()) {
      setLoginError('Vui lòng nhập đầy đủ tên đăng nhập và mật khẩu.');
      return;
    }
    setIsLoggingIn(true);
    setLoginError(null);
    setLoginMessage(null);
    try {
      const res = await fetch('/api/auth/login-account', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          username: usernameInput.trim(),
          password: passwordInput.trim(),
        }),
      });
      const data = await res.json();
      if (data.success && data.logged_in) {
        setLoginMessage('Đăng nhập thành công! Đang tự động tiếp tục tiến trình...');
        setTimeout(() => {
          setShowLoginModal(false);
          setLoginMessage(null);
          handleResume();
        }, 1200);
      } else {
        setLoginError(data.message || 'Đăng nhập không thành công.');
      }
    } catch (err: any) {
      setLoginError('Lỗi kết nối máy chủ: ' + err.message);
    } finally {
      setIsLoggingIn(false);
    }
  };

  const handleLoginCookie = async () => {
    if (!cookieInput.trim()) {
      setLoginError('Vui lòng dán chuỗi cookie (xf_user / xf_session).');
      return;
    }
    setIsLoggingIn(true);
    setLoginError(null);
    setLoginMessage(null);
    try {
      const res = await fetch('/api/auth/cookies', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ cookie_string: cookieInput.trim() }),
      });
      const data = await res.json();
      if (data.success && data.logged_in) {
        setLoginMessage('Đã lưu Cookie thành công! Đang tự động tiếp tục tiến trình...');
        setTimeout(() => {
          setShowLoginModal(false);
          setLoginMessage(null);
          handleResume();
        }, 1200);
      } else {
        setLoginError(data.message || 'Cookie không hợp lệ hoặc đã hết hạn.');
      }
    } catch (err: any) {
      setLoginError('Lỗi kết nối khi gửi cookie: ' + err.message);
    } finally {
      setIsLoggingIn(false);
    }
  };

  const handleDownload = (path: string) => {
    window.location.href = `/api/exports/download?path=${encodeURIComponent(path)}`;
  };

  const formatFileSize = (bytes: number): string => {
    if (!bytes || bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`;
  };

  // Check initial job status in case it was interrupted or completed earlier
  useEffect(() => {
    fetch(`/api/jobs/${jobId}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((j) => {
        if (!j) return;
        if (j.details?.files && Array.isArray(j.details.files) && j.details.files.length > 0) {
          setCompletedFiles(j.details.files);
        }
        if (j.status === 'failed') {
          setErrorMessage(j.error_message || 'Tiến trình đã bị dừng do sự cố hoặc ngắt kết nối.');
        } else if (j.status === 'completed' && j.details?.files) {
          setProgress(100);
          onComplete(j.details.files, {
            subject_code: subjectCode || j.subject_code,
            exam_type: examType || j.exam_type,
            total_exams: j.details.total_exams || j.details.files.length,
            total_questions: j.details.total_questions || 0,
            files: j.details.files,
          });
        }
      })
      .catch(() => {});
  }, [jobId]);

  useEffect(() => {
    const eventSource = new EventSource(`/api/jobs/${jobId}/stream`);

    eventSource.onmessage = (event) => {
      try {
        const data: SSEEvent = JSON.parse(event.data);
        const timeStr = new Date().toLocaleTimeString('vi-VN', {
          hour12: false,
          hour: '2-digit',
          minute: '2-digit',
          second: '2-digit',
        });

        if (data.type === 'exam_completed') {
          if (data.message) {
            setLogs((prev) => [
              ...prev,
              { id: Math.random().toString(), time: timeStr, text: `✅ ${data.message!}`, step: data.step },
            ]);
            setCurrentStep(data.message);
          }
          if (data.files && data.files.length > 0) {
            setCompletedFiles(data.files);
          } else if (data.completed_file) {
            setCompletedFiles((prev) =>
              prev.some((f) => f.filename === data.completed_file!.filename)
                ? prev
                : [...prev, data.completed_file!]
            );
          }
          if (data.progress !== undefined) setProgress(data.progress);
          if (data.total_exams !== undefined) setTotalExams(data.total_exams);
          if (data.current_exam !== undefined) setCurrentExam(data.current_exam);
        } else if (data.type === 'log') {
          if (data.message) {
            setLogs((prev) => [
              ...prev,
              { id: Math.random().toString(), time: timeStr, text: data.message!, step: data.step },
            ]);
            setCurrentStep(data.message);
          }
          if (data.progress !== undefined) setProgress(data.progress);
          if (data.total_exams !== undefined) setTotalExams(data.total_exams);
          if (data.current_exam !== undefined) setCurrentExam(data.current_exam);
        } else if (data.type === 'progress') {
          if (data.progress !== undefined) setProgress(data.progress);
          if (data.current_question !== undefined) setCurrentQuestion(data.current_question);
          if (data.total_questions !== undefined) setTotalQuestions(data.total_questions);
          if (data.message) setCurrentStep(data.message);
        } else if (data.type === 'completed') {
          setProgress(100);
          eventSource.close();
          const files = data.files || [];
          if (files.length > 0) {
            setCompletedFiles(files);
          }
          onComplete(files, {
            subject_code: subjectCode,
            exam_type: examType,
            total_exams: data.total_exams || files.length,
            total_questions: data.total_questions,
            files: files,
          });
        } else if (data.type === 'error') {
          if (data.files && data.files.length > 0) {
            setCompletedFiles(data.files);
          }
          setErrorMessage(data.message || 'Xảy ra lỗi trong quá trình biên soạn.');
          eventSource.close();
        }
      } catch (err) {
        console.error('Error parsing SSE event:', err);
      }
    };

    eventSource.onerror = (err) => {
      console.warn('SSE connection error:', err);
      setErrorMessage('Mất kết nối với máy chủ (backend đã tắt hoặc đường truyền mạng bị gián đoạn).');
      eventSource.close();
    };

    return () => {
      eventSource.close();
    };
  }, [jobId, reconnectTrigger]);

  const handleResume = async () => {
    setIsResuming(true);
    setErrorMessage(null);
    setCurrentStep('Đang khôi phục và tiếp tục tiến trình...');
    setLogs((prev) => [
      ...prev,
      {
        id: Math.random().toString(),
        time: new Date().toLocaleTimeString('vi-VN', { hour12: false }),
        text: '🔄 Đang gửi yêu cầu tiếp tục tiến trình từ điểm dừng...',
      },
    ]);

    try {
      const resp = await fetch(`/api/jobs/${jobId}/resume`, { method: 'POST' });
      if (!resp.ok) {
        const errJson = await resp.json().catch(() => null);
        throw new Error(errJson?.detail || `Không thể tiếp tục tiến trình (HTTP ${resp.status})`);
      }
      // Reconnect SSE
      setReconnectTrigger((prev) => prev + 1);
    } catch (err: any) {
      setErrorMessage(err.message || 'Lỗi khi gửi yêu cầu tiếp tục.');
    } finally {
      setIsResuming(false);
    }
  };

  useEffect(() => {
    logsEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [logs]);

  return (
    <div style={{ maxWidth: '840px', margin: '0 auto' }}>
      <div className="card-paper" style={{ position: 'relative', overflow: 'hidden' }}>
        {/* Top 2px Progress Line */}
        <div
          style={{
            position: 'absolute',
            top: 0,
            left: 0,
            right: 0,
            height: '3px',
            backgroundColor: 'var(--border-subtle)',
          }}
        >
          <div
            style={{
              height: '100%',
              width: `${progress}%`,
              backgroundColor: errorMessage ? 'var(--status-conflict-text)' : 'var(--primary)',
              transition: 'width 200ms ease-out',
            }}
          />
        </div>

        {/* Header Information */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            marginBottom: 'var(--space-5)',
            borderBottom: '1px solid var(--border-subtle)',
            paddingBottom: 'var(--space-4)',
          }}
        >
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', marginBottom: 'var(--space-1)' }}>
              <span
                style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: 'var(--text-base)',
                  fontWeight: 700,
                  color: 'var(--primary)',
                }}
              >
                {subjectCode}
              </span>
              <span
                style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: 'var(--text-xs)',
                  padding: '2px 8px',
                  backgroundColor: 'var(--bg-subtle)',
                  border: '1px solid var(--border-subtle)',
                  borderRadius: 'var(--radius-sm)',
                }}
              >
                {examType} · {limit} đề
              </span>
            </div>
            <h2 className="serif-title" style={{ fontSize: 'var(--text-xl)' }}>
              Đang biên soạn tài liệu ôn tập
            </h2>
          </div>

          <div style={{ textAlign: 'right' }}>
            <div
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: 'var(--text-2xl)',
                fontWeight: 700,
                color: 'var(--text-primary)',
              }}
            >
              {Math.round(progress)}%
            </div>
            <span style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>
              Tiến độ tổng thể
            </span>
          </div>
        </div>

        {/* Live Counters */}
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))',
            gap: 'var(--space-3)',
            marginBottom: 'var(--space-5)',
          }}
        >
          <div
            style={{
              padding: 'var(--space-3)',
              backgroundColor: 'var(--bg-subtle)',
              border: '1px solid var(--border-subtle)',
              borderRadius: 'var(--radius-sm)',
            }}
          >
            <div style={{ fontSize: 'var(--text-xs)', color: 'var(--text-secondary)' }}>Đề đang xử lý</div>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 'var(--text-lg)', fontWeight: 600 }}>
              {currentExam > 0 ? `${currentExam} / ${totalExams}` : 'Đang quét...'}
            </div>
          </div>

          <div
            style={{
              padding: 'var(--space-3)',
              backgroundColor: 'var(--bg-subtle)',
              border: '1px solid var(--border-subtle)',
              borderRadius: 'var(--radius-sm)',
            }}
          >
            <div style={{ fontSize: 'var(--text-xs)', color: 'var(--text-secondary)' }}>Câu hỏi hiện tại</div>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 'var(--text-lg)', fontWeight: 600 }}>
              {totalQuestions > 0 ? `${currentQuestion} / ${totalQuestions}` : 'Đang chờ...'}
            </div>
          </div>

          <div
            style={{
              padding: 'var(--space-3)',
              backgroundColor: 'var(--bg-subtle)',
              border: '1px solid var(--border-subtle)',
              borderRadius: 'var(--radius-sm)',
            }}
          >
            <div style={{ fontSize: 'var(--text-xs)', color: 'var(--text-secondary)' }}>Trạng thái</div>
            <div
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: 'var(--text-xs)',
                fontWeight: 600,
                color: errorMessage ? 'var(--status-conflict-text)' : 'var(--primary)',
                whiteSpace: 'nowrap',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
              }}
            >
              {errorMessage ? 'Lỗi dừng' : currentStep}
            </div>
          </div>
        </div>

        {/* Live Completed Files Section (Downloadable & Reviewable Per Exam) */}
        {completedFiles.length > 0 && (
          <div
            style={{
              marginBottom: 'var(--space-5)',
              padding: 'var(--space-4)',
              backgroundColor: 'var(--bg-surface)',
              border: '1px solid var(--border-subtle)',
              borderRadius: 'var(--radius-sm)',
            }}
          >
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                marginBottom: 'var(--space-3)',
                flexWrap: 'wrap',
                gap: 'var(--space-2)',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <span style={{ fontSize: 'var(--text-base)', fontWeight: 700, color: 'var(--text-primary)' }}>
                  📄 Đề đã hoàn thành ({completedFiles.length} đề)
                </span>
                <span
                  style={{
                    fontSize: 'var(--text-xs)',
                    padding: '2px 8px',
                    backgroundColor: 'var(--status-confident-bg)',
                    color: 'var(--status-confident-text)',
                    borderRadius: 'var(--radius-sm)',
                    fontWeight: 600,
                  }}
                >
                  Sẵn sàng tải ngay
                </span>
              </div>
              <span style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>
                Tải về xem kết quả ngay không cần chờ các đề sau
              </span>
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-2)' }}>
              {completedFiles.map((file, idx) => (
                <div
                  key={idx}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    padding: 'var(--space-3)',
                    backgroundColor: 'var(--bg-subtle)',
                    border: '1px solid var(--border-subtle)',
                    borderRadius: 'var(--radius-sm)',
                    gap: 'var(--space-3)',
                  }}
                >
                  <div style={{ minWidth: 0, flex: 1 }}>
                    <div
                      style={{
                        fontWeight: 600,
                        fontSize: 'var(--text-sm)',
                        color: 'var(--text-primary)',
                        marginBottom: '2px',
                        whiteSpace: 'nowrap',
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                      }}
                    >
                      {file.exam_title}
                    </div>
                    <div style={{ fontSize: 'var(--text-xs)', color: 'var(--text-secondary)' }}>
                      <span style={{ fontFamily: 'var(--font-mono)' }}>{file.filename}</span> ·{' '}
                      <span style={{ fontFamily: 'var(--font-mono)' }}>{file.questions_count} câu</span> ·{' '}
                      <span style={{ fontFamily: 'var(--font-mono)' }}>{formatFileSize(file.size_bytes)}</span>
                    </div>
                  </div>

                  <button
                    onClick={() => handleDownload(file.path)}
                    className="btn-primary"
                    style={{
                      fontSize: 'var(--text-xs)',
                      padding: 'var(--space-2) var(--space-3)',
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: '6px',
                      flexShrink: 0,
                    }}
                  >
                    📥 Tải file Word (.docx)
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Error Alert Box */}
        {errorMessage && (
          <div
            style={{
              padding: 'var(--space-4)',
              backgroundColor: 'var(--status-conflict-bg)',
              border: '1px solid var(--status-conflict-border)',
              borderRadius: 'var(--radius-sm)',
              color: 'var(--status-conflict-text)',
              marginBottom: 'var(--space-5)',
              fontSize: 'var(--text-sm)',
            }}
          >
            <div style={{ fontWeight: 700, marginBottom: 'var(--space-1)' }}>
              {errorMessage.toLowerCase().includes('đăng nhập') || errorMessage.toLowerCase().includes('auth') || errorMessage.toLowerCase().includes('session') || errorMessage.toLowerCase().includes('1 phiên')
                ? '⚠️ Cần đăng nhập lại (Chính sách 1 phiên duy nhất của FUOverflow):'
                : errorMessage.toLowerCase().includes('kết nối') || errorMessage.toLowerCase().includes('mạng')
                ? '🌐 Lỗi kết nối mạng:'
                : '❌ Đã xảy ra lỗi:'}
            </div>
            <div style={{ lineHeight: 1.5 }}>
              {errorMessage}
            </div>
            {errorMessage.toLowerCase().includes('1 phiên') || errorMessage.toLowerCase().includes('đăng nhập') ? (
              <div style={{ marginTop: 'var(--space-2)', fontSize: 'var(--text-xs)', color: 'var(--text-secondary)' }}>
                💡 <em>Lưu ý:</em> FUOverflow chỉ cho phép 1 phiên đăng nhập hoạt động cùng lúc. Nếu bạn vừa mở FUOverflow trên trình duyệt khác, phiên hiện tại sẽ bị ngắt. Hãy đăng nhập lại rồi bấm <strong>"Chạy tiếp từ chỗ dừng"</strong> bên dưới để tiếp tục từ đúng câu hỏi dang dở mà không bị mất dữ liệu đã tải.
              </div>
            ) : null}
            <div style={{ display: 'flex', gap: 'var(--space-2)', marginTop: 'var(--space-3)', flexWrap: 'wrap' }}>
              <button
                type="button"
                onClick={() => {
                  setLoginError(null);
                  setLoginMessage(null);
                  setShowLoginModal(true);
                }}
                style={{
                  fontSize: 'var(--text-xs)',
                  padding: 'var(--space-2) var(--space-4)',
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '6px',
                  fontWeight: 600,
                  backgroundColor: '#C53030',
                  color: '#ffffff',
                  border: 'none',
                  borderRadius: 'var(--radius-sm)',
                  cursor: 'pointer',
                  boxShadow: 'var(--shadow-sm)',
                }}
              >
                🔑 Đăng nhập lại tài khoản
              </button>

              <button
                onClick={handleResume}
                disabled={isResuming}
                className="btn-primary"
                style={{
                  fontSize: 'var(--text-xs)',
                  padding: 'var(--space-2) var(--space-4)',
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '6px',
                  fontWeight: 600,
                  cursor: isResuming ? 'not-allowed' : 'pointer',
                }}
              >
                {isResuming ? '⏳ Đang khôi phục...' : '🔄 Chạy tiếp từ chỗ dừng'}
              </button>
              <button
                onClick={onCancel}
                className="btn-secondary"
                style={{ fontSize: 'var(--text-xs)', padding: 'var(--space-2) var(--space-3)' }}
              >
                Quay lại màn hình chọn môn
              </button>
            </div>
          </div>
        )}

        {/* Monospace Log Feed */}
        <div style={{ marginBottom: 'var(--space-4)' }}>
          <div
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              marginBottom: 'var(--space-2)',
            }}
          >
            <span style={{ fontSize: 'var(--text-xs)', color: 'var(--text-secondary)', fontWeight: 600 }}>
              Nhật ký xử lý thời gian thực
            </span>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>
              {logs.length} sự kiện
            </span>
          </div>

          <div
            style={{
              backgroundColor: 'var(--bg-subtle)',
              border: '1px solid var(--border-subtle)',
              borderRadius: 'var(--radius-sm)',
              padding: 'var(--space-3)',
              height: '240px',
              overflowY: 'auto',
              fontFamily: 'var(--font-mono)',
              fontSize: 'var(--text-xs)',
              lineHeight: 1.7,
              color: 'var(--text-primary)',
            }}
          >
            {logs.length === 0 ? (
              <div style={{ color: 'var(--text-muted)' }}>Đang kết nối tới server...</div>
            ) : (
              logs.map((log) => (
                <div key={log.id} style={{ display: 'flex', gap: 'var(--space-2)' }}>
                  <span style={{ color: 'var(--text-muted)', flexShrink: 0 }}>[{log.time}]</span>
                  <span style={{ color: 'var(--text-primary)' }}>{log.text}</span>
                </div>
              ))
            )}
            <div ref={logsEndRef} />
          </div>
        </div>

        {/* Footer actions */}
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 'var(--space-3)' }}>
          <button
            onClick={onCancel}
            className="btn-secondary"
            style={{ fontSize: 'var(--text-sm)', padding: 'var(--space-2) var(--space-4)' }}
          >
            Huỷ bỏ & Quay lại
          </button>
        </div>
      </div>

      {/* Re-login Modal Popup directly on ScreenProgress */}
      {showLoginModal && (
        <div
          role="dialog"
          aria-modal="true"
          style={{
            position: 'fixed',
            inset: 0,
            backgroundColor: 'rgba(0, 0, 0, 0.65)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 9999,
            padding: '16px',
          }}
          onClick={() => !isLoggingIn && setShowLoginModal(false)}
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="login-dialog-title"
            style={{
              backgroundColor: 'var(--bg-surface)',
              borderRadius: 'var(--radius-md)',
              maxWidth: '480px',
              width: '100%',
              padding: 'var(--space-6)',
              boxShadow: 'var(--shadow-lg)',
              border: '1px solid var(--border-subtle)',
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 'var(--space-3)' }}>
              <h3 id="login-dialog-title" style={{ margin: 0, fontFamily: 'var(--font-serif)', fontSize: 'var(--text-lg)' }}>
                🔑 Đăng nhập lại FUOverflow
              </h3>
              <button
                type="button"
                disabled={isLoggingIn}
                onClick={() => setShowLoginModal(false)}
                style={{
                  background: 'none',
                  border: 'none',
                  fontSize: '20px',
                  cursor: isLoggingIn ? 'not-allowed' : 'pointer',
                  color: 'var(--text-muted)',
                }}
              >
                ✕
              </button>
            </div>

            <p style={{ fontSize: 'var(--text-xs)', color: 'var(--text-secondary)', marginBottom: 'var(--space-4)', lineHeight: 1.5 }}>
              Phiên FUOverflow của bạn đã hết hạn hoặc bị đăng xuất ở trình duyệt khác. Hãy nhập thông tin để hệ thống đăng nhập lại và tự động chạy tiếp.
            </p>

            {/* Mode Tabs */}
            <div style={{ display: 'flex', gap: '8px', marginBottom: 'var(--space-4)' }}>
              <button
                type="button"
                onClick={() => setLoginMode('account')}
                style={{
                  flex: 1,
                  padding: '6px',
                  fontSize: '12px',
                  fontWeight: 600,
                  backgroundColor: loginMode === 'account' ? 'var(--primary)' : 'var(--bg-subtle)',
                  color: loginMode === 'account' ? '#fff' : 'var(--text-primary)',
                  border: '1px solid var(--border-subtle)',
                  borderRadius: 'var(--radius-sm)',
                  cursor: 'pointer',
                }}
              >
                👤 Tài khoản FUOverflow
              </button>
              <button
                type="button"
                onClick={() => setLoginMode('cookie')}
                style={{
                  flex: 1,
                  padding: '6px',
                  fontSize: '12px',
                  fontWeight: 600,
                  backgroundColor: loginMode === 'cookie' ? 'var(--primary)' : 'var(--bg-subtle)',
                  color: loginMode === 'cookie' ? '#fff' : 'var(--text-primary)',
                  border: '1px solid var(--border-subtle)',
                  borderRadius: 'var(--radius-sm)',
                  cursor: 'pointer',
                }}
              >
                🍪 Dán Cookie
              </button>
            </div>

            {loginMode === 'account' ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                <div>
                  <label style={{ fontSize: '11px', fontWeight: 600, color: 'var(--text-secondary)', display: 'block', marginBottom: '4px' }}>
                    Tên đăng nhập / Email:
                  </label>
                  <input
                    type="text"
                    value={usernameInput}
                    onChange={(e) => setUsernameInput(e.target.value)}
                    placeholder="Nhập tên hoặc email"
                    style={{
                      width: '100%',
                      padding: '8px 10px',
                      fontSize: '13px',
                      backgroundColor: 'var(--bg-canvas)',
                      border: '1px solid var(--border-strong)',
                      borderRadius: 'var(--radius-sm)',
                      color: 'var(--text-primary)',
                    }}
                  />
                </div>
                <div>
                  <label style={{ fontSize: '11px', fontWeight: 600, color: 'var(--text-secondary)', display: 'block', marginBottom: '4px' }}>
                    Mật khẩu:
                  </label>
                  <input
                    type="password"
                    value={passwordInput}
                    onChange={(e) => setPasswordInput(e.target.value)}
                    placeholder="Mật khẩu FUOverflow"
                    style={{
                      width: '100%',
                      padding: '8px 10px',
                      fontSize: '13px',
                      backgroundColor: 'var(--bg-canvas)',
                      border: '1px solid var(--border-strong)',
                      borderRadius: 'var(--radius-sm)',
                      color: 'var(--text-primary)',
                    }}
                  />
                </div>
                <button
                  type="button"
                  onClick={handleLoginAccount}
                  disabled={isLoggingIn}
                  className="btn-primary"
                  style={{
                    marginTop: '6px',
                    padding: '8px 14px',
                    fontSize: '13px',
                    fontWeight: 600,
                    cursor: isLoggingIn ? 'not-allowed' : 'pointer',
                  }}
                >
                  {isLoggingIn ? '⏳ Đang đăng nhập...' : 'Đăng nhập & Tiếp tục'}
                </button>
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                <textarea
                  rows={4}
                  value={cookieInput}
                  onChange={(e) => setCookieInput(e.target.value)}
                  placeholder="Dán chuỗi cookie (xf_user=...; xf_session=...)"
                  style={{
                    width: '100%',
                    padding: '8px 10px',
                    fontSize: '12px',
                    fontFamily: 'var(--font-mono)',
                    backgroundColor: 'var(--bg-canvas)',
                    border: '1px solid var(--border-strong)',
                    borderRadius: 'var(--radius-sm)',
                    color: 'var(--text-primary)',
                  }}
                />
                <button
                  type="button"
                  onClick={handleLoginCookie}
                  disabled={isLoggingIn}
                  className="btn-primary"
                  style={{
                    padding: '8px 14px',
                    fontSize: '13px',
                    fontWeight: 600,
                    cursor: isLoggingIn ? 'not-allowed' : 'pointer',
                  }}
                >
                  {isLoggingIn ? '⏳ Đang kiểm tra cookie...' : 'Lưu Cookie & Tiếp tục'}
                </button>
              </div>
            )}

            {loginMessage && (
              <div style={{ marginTop: '10px', padding: '8px', backgroundColor: 'var(--status-confident-bg)', color: 'var(--status-confident-text)', borderRadius: 'var(--radius-sm)', fontSize: '12px', fontWeight: 600 }}>
                {loginMessage}
              </div>
            )}

            {loginError && (
              <div style={{ marginTop: '10px', padding: '8px', backgroundColor: 'var(--status-conflict-bg)', color: 'var(--status-conflict-text)', borderRadius: 'var(--radius-sm)', fontSize: '12px' }}>
                ❌ {loginError}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};
