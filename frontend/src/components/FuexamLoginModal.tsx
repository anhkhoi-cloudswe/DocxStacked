import React, { useEffect, useState, useRef } from 'react';
import type { FuexamLoginStatus, FuexamLoginSession } from '../types';

interface FuexamLoginModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess: () => void;
  isMidJob?: boolean;
  isBackendReady?: boolean;
}

export const FuexamLoginModal: React.FC<FuexamLoginModalProps> = ({
  isOpen,
  onClose,
  onSuccess,
  isMidJob = false,
  isBackendReady = true,
}) => {
  const [state, setState] = useState<FuexamLoginStatus>('idle');
  const [message, setMessage] = useState<string>('');
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [recentLogs, setRecentLogs] = useState<string[]>([]);
  const [showLogs, setShowLogs] = useState<boolean>(false);
  const pollTimerRef = useRef<any>(null);

  // Sync state on mount / open
  useEffect(() => {
    if (!isOpen) {
      if (pollTimerRef.current) clearInterval(pollTimerRef.current);
      setState('idle');
      setMessage('');
      setErrorMessage(null);
      setRecentLogs([]);
      return;
    }

    // Check backend login status on open to restore active session if present
    fetch('/api/auth/fuexam/login/status')
      .then((r) => (r.ok ? r.json() : null))
      .then((session: FuexamLoginSession | null) => {
        if (!session) return;
        if (session.recent_logs) {
          setRecentLogs(session.recent_logs);
        }
        if (session.state === 'waiting') {
          setState('waiting');
          setMessage(session.message || 'Hãy đăng nhập trong cửa sổ vừa mở.');
        } else if (session.state === 'starting') {
          setState('starting');
          setMessage(session.message || 'Đang khởi động cửa sổ Chromium...');
        } else if (session.state === 'success' || session.state === 'authenticated') {
          setState('success');
          setTimeout(() => {
            onSuccess();
          }, 800);
        } else if (session.state === 'failed' || session.state === 'error') {
          setState('failed');
          setErrorMessage(session.error || session.message || 'Tiến trình đăng nhập thất bại.');
        }
      })
      .catch(() => {});

    // Check if credentials/storage state is already valid
    fetch('/api/auth/fuexam/status')
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (data && data.logged_in) {
          setState('success');
          setTimeout(() => {
            onSuccess();
          }, 800);
        }
      })
      .catch(() => {});
  }, [isOpen, onSuccess]);

  // Sync when tab visibility changes (requirement 4: switching tab must not drop waiting state)
  useEffect(() => {
    const handleVisibility = () => {
      if (document.visibilityState === 'visible' && isOpen) {
        fetch('/api/auth/fuexam/login/status')
          .then((r) => (r.ok ? r.json() : null))
          .then((session: FuexamLoginSession | null) => {
            if (!session) return;
            if (session.recent_logs) {
              setRecentLogs(session.recent_logs);
            }
            if (session.state === 'waiting') {
              setState('waiting');
              setMessage(session.message || 'Hãy đăng nhập trong cửa sổ vừa mở.');
            } else if (session.state === 'starting') {
              setState('starting');
              setMessage(session.message || 'Đang khởi động cửa sổ Chromium...');
            } else if (session.state === 'success' || session.state === 'authenticated') {
              setState('success');
              setTimeout(() => onSuccess(), 800);
            } else if (session.state === 'failed' || session.state === 'error') {
              setState('failed');
              setErrorMessage(session.error || session.message || 'Tiến trình Chromium đã dừng.');
            } else if (session.state === 'timeout') {
              setState('timeout');
            }
          })
          .catch(() => {});
      }
    };

    document.addEventListener('visibilitychange', handleVisibility);
    return () => {
      document.removeEventListener('visibilitychange', handleVisibility);
    };
  }, [isOpen, onSuccess]);

  // Polling when waiting or starting
  useEffect(() => {
    if (state !== 'waiting' && state !== 'starting') {
      if (pollTimerRef.current) {
        clearInterval(pollTimerRef.current);
        pollTimerRef.current = null;
      }
      return;
    }

    const poll = async () => {
      try {
        const res = await fetch('/api/auth/fuexam/login/status');
        if (res.ok) {
          const session: FuexamLoginSession = await res.json();
          if (session.recent_logs) {
            setRecentLogs(session.recent_logs);
          }
          if (session.state === 'success' || session.state === 'authenticated') {
            setState('success');
            setMessage('Đăng nhập thành công! Đang tự động cập nhật hệ thống...');
            setTimeout(() => {
              onSuccess();
            }, 1000);
          } else if (session.state === 'waiting') {
            setState('waiting');
            setMessage(session.message || 'Hãy đăng nhập trong cửa sổ vừa mở.');
          } else if (session.state === 'timeout') {
            setState('timeout');
            setMessage(session.message || 'Quá thời hạn chờ 5 phút.');
          } else if (session.state === 'failed' || session.state === 'error') {
            setState('failed');
            setErrorMessage(session.error || session.message || 'Lỗi không xác định khi mở trình duyệt.');
          } else if (session.state === 'cancelled') {
            setState('idle');
            setMessage('Đã huỷ phiên đăng nhập.');
          }
        }
      } catch (err: any) {
        console.warn('Polling fuexam status error:', err);
      }
    };

    pollTimerRef.current = setInterval(poll, 1500);
    return () => {
      if (pollTimerRef.current) clearInterval(pollTimerRef.current);
    };
  }, [state, onSuccess]);

  const handleStartLogin = async () => {
    if (!isBackendReady) {
      setState('failed');
      setErrorMessage('Backend chưa sẵn sàng. Vui lòng đợi trong giây lát hoặc kiểm tra backend console.');
      return;
    }

    setState('starting');
    setMessage('Đang kết nối và khởi động cửa sổ Chromium...');
    setErrorMessage(null);

    try {
      const res = await fetch('/api/auth/fuexam/login/start', { method: 'POST' });
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        setState('failed');
        setErrorMessage(
          errData.detail ||
            errData.error ||
            'Không thể mở cửa sổ trình duyệt Chromium từ môi trường ngầm hoặc phiên không tương tác. Vui lòng chạy backend từ PowerShell trên máy thật: python run_dev.py'
        );
        return;
      }
      const data: FuexamLoginSession & { success?: boolean } = await res.json();
      if (data.recent_logs) {
        setRecentLogs(data.recent_logs);
      }
      const effectiveState = data.state || (data.success ? 'waiting' : 'failed');
      if (effectiveState === 'success' || effectiveState === 'authenticated') {
        setState('success');
        setTimeout(() => onSuccess(), 800);
      } else if (effectiveState === 'failed' || effectiveState === 'error') {
        setState('failed');
        setErrorMessage(data.error || data.message || 'Không thể mở cửa sổ trình duyệt Chromium.');
      } else if (effectiveState === 'waiting') {
        setState('waiting');
        setMessage(data.message || 'Hãy đăng nhập trong cửa sổ vừa mở.');
      } else {
        setState(effectiveState);
        setMessage(data.message || '');
      }
    } catch (err: any) {
      setState('failed');
      setErrorMessage(
        'Lỗi kết nối máy chủ backend (/api/auth/fuexam/login/start bị từ chối kết nối). Backend chưa sẵn sàng hoặc đã dừng.'
      );
    }
  };

  const handleCancelLogin = async () => {
    try {
      await fetch('/api/auth/fuexam/login/cancel', { method: 'POST' });
    } catch {}
    setState('idle');
    setMessage('Đã huỷ phiên.');
  };

  if (!isOpen) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      data-testid="fuexam-login-modal"
      style={{
        position: 'fixed',
        inset: 0,
        backgroundColor: 'rgba(15, 23, 42, 0.65)',
        zIndex: 1000,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '16px',
      }}
    >
      <div
        style={{
          backgroundColor: 'var(--bg-surface, #ffffff)',
          border: '1px solid var(--border-subtle, #e2e8f0)',
          borderRadius: '8px',
          width: '100%',
          maxWidth: '520px',
          padding: '28px',
          boxShadow: '0 20px 25px -5px rgba(0, 0, 0, 0.1), 0 8px 10px -6px rgba(0, 0, 0, 0.1)',
        }}
      >
        {/* Header */}
        <div style={{ marginBottom: '20px' }}>
          <div
            style={{
              fontSize: '11px',
              fontWeight: 600,
              color: '#b45309',
              backgroundColor: 'rgba(217, 119, 6, 0.08)',
              display: 'inline-block',
              padding: '2px 8px',
              borderRadius: '4px',
              marginBottom: '8px',
              letterSpacing: '0.04em',
              textTransform: 'uppercase',
            }}
          >
            fuexam.me · Quản lý phiên
          </div>
          <h2
            style={{
              fontSize: '20px',
              fontWeight: 700,
              color: 'var(--text-primary, #0f172a)',
              margin: 0,
              fontFamily: 'var(--font-serif, serif)',
            }}
          >
            {isMidJob ? 'Phiên đăng nhập fuexam đã hết hạn' : 'Đăng nhập nền tảng fuexam.me'}
          </h2>
        </div>

        {/* State: idle */}
        {state === 'idle' && (
          <div>
            <p
              style={{
                fontSize: '13px',
                color: 'var(--text-secondary, #475569)',
                lineHeight: 1.6,
                margin: '0 0 16px 0',
              }}
            >
              {isMidJob
                ? 'Phiên đăng nhập fuexam.me đã hết hạn trong lúc đang biên soạn đề. Vui lòng mở cửa sổ đăng nhập lại để hệ thống tự động tiếp tục tiến trình.'
                : 'Diễn đàn fuexam.me yêu cầu tài khoản thành viên để xem ảnh đề thi và thảo luận. Nhấn nút bên dưới để mở cửa sổ trình duyệt đăng nhập.'}
            </p>

            <div
              style={{
                backgroundColor: 'var(--bg-subtle, #f8fafc)',
                border: '1px solid var(--border-subtle, #e2e8f0)',
                borderRadius: '6px',
                padding: '12px 14px',
                marginBottom: '16px',
                fontSize: '12px',
                color: 'var(--text-secondary, #475569)',
                lineHeight: 1.5,
              }}
            >
              <div style={{ fontWeight: 600, color: 'var(--text-primary, #0f172a)', marginBottom: '4px' }}>
                Phương thức đăng nhập duy nhất:
              </div>
              <div>
                Hệ thống sẽ mở cửa sổ Chromium với tiêu đề <strong>"DocxStacked - Đăng nhập fuexam"</strong> để bạn tự gõ tài khoản và mật khẩu trực tiếp trên diễn đàn.
              </div>
            </div>

            {!isBackendReady && (
              <div
                data-testid="fuexam-backend-not-ready-notice"
                style={{
                  backgroundColor: '#fef2f2',
                  border: '1px solid #fecaca',
                  borderRadius: '6px',
                  padding: '10px 12px',
                  marginBottom: '16px',
                  fontSize: '12px',
                  color: '#991b1b',
                  lineHeight: 1.5,
                }}
              >
                ⚠️ <strong>Backend chưa sẵn sàng, đang thử lại kết nối...</strong>
                <div>Không thể mở cửa sổ đăng nhập lúc này. Vui lòng đợi trong giây lát.</div>
              </div>
            )}

            <div style={{ display: 'flex', gap: '10px', justifyContent: 'flex-end' }}>
              <button
                type="button"
                onClick={onClose}
                style={{
                  padding: '8px 16px',
                  fontSize: '13px',
                  fontWeight: 500,
                  color: 'var(--text-secondary, #475569)',
                  backgroundColor: 'transparent',
                  border: '1px solid var(--border-subtle, #cbd5e1)',
                  borderRadius: '5px',
                  cursor: 'pointer',
                }}
              >
                Đóng
              </button>
              <button
                type="button"
                onClick={handleStartLogin}
                disabled={!isBackendReady}
                data-testid="btn-open-fuexam-login"
                style={{
                  padding: '8px 18px',
                  fontSize: '13px',
                  fontWeight: 600,
                  color: '#ffffff',
                  backgroundColor: isBackendReady ? '#b45309' : '#94a3b8',
                  border: 'none',
                  borderRadius: '5px',
                  cursor: isBackendReady ? 'pointer' : 'not-allowed',
                  opacity: isBackendReady ? 1 : 0.65,
                }}
              >
                Mở cửa sổ đăng nhập
              </button>
            </div>
          </div>
        )}

        {/* State: starting (Requirement 1: Not waiting yet!) */}
        {state === 'starting' && (
          <div style={{ textAlign: 'center', padding: '16px 0' }}>
            <div
              style={{
                width: '36px',
                height: '36px',
                border: '3px solid #e2e8f0',
                borderTopColor: '#b45309',
                borderRadius: '50%',
                margin: '0 auto 16px auto',
                animation: 'spin 1s linear infinite',
              }}
            />
            <h3
              style={{
                fontSize: '16px',
                fontWeight: 600,
                color: 'var(--text-primary, #0f172a)',
                margin: '0 0 8px 0',
              }}
            >
              Đang khởi động cửa sổ Chromium...
            </h3>
            <p
              style={{
                fontSize: '13px',
                color: 'var(--text-secondary, #475569)',
                lineHeight: 1.5,
                margin: '0 0 20px 0',
              }}
            >
              {message || 'Hệ thống đang chuẩn bị tiến trình Chromium và mở trang đăng nhập fuexam.me...'}
            </p>
            <div style={{ fontSize: '12px', color: '#64748b' }}>
              Vui lòng đợi giây lát, cửa sổ sẽ xuất hiện ngay.
            </div>
          </div>
        )}

        {/* State: waiting */}
        {state === 'waiting' && (
          <div style={{ textAlign: 'center', padding: '10px 0' }}>
            <div
              style={{
                width: '36px',
                height: '36px',
                border: '3px solid #e2e8f0',
                borderTopColor: '#b45309',
                borderRadius: '50%',
                margin: '0 auto 16px auto',
                animation: 'spin 1s linear infinite',
              }}
            />
            <h3
              style={{
                fontSize: '16px',
                fontWeight: 600,
                color: 'var(--text-primary, #0f172a)',
                margin: '0 0 8px 0',
              }}
            >
              Hãy đăng nhập trong cửa sổ vừa mở
            </h3>
            <p
              style={{
                fontSize: '13px',
                color: 'var(--text-secondary, #475569)',
                lineHeight: 1.5,
                margin: '0 0 16px 0',
              }}
            >
              {message || 'Cửa sổ Chromium với tiêu đề "DocxStacked - Đăng nhập fuexam" đã sẵn sàng. Hãy nhập tài khoản của bạn trên cửa sổ đó. Hệ thống đang tự động theo dõi (tối đa 5 phút)...'}
            </p>

            {/* Collapsible recent logs (filtered) */}
            {recentLogs.length > 0 && (
              <div style={{ textAlign: 'left', marginBottom: '16px' }}>
                <button
                  type="button"
                  onClick={() => setShowLogs(!showLogs)}
                  style={{
                    background: 'none',
                    border: 'none',
                    color: '#0284c7',
                    fontSize: '11px',
                    fontWeight: 600,
                    cursor: 'pointer',
                    padding: '2px 0',
                  }}
                >
                  {showLogs ? 'Ẩn nhật ký trình duyệt ▲' : `Xem nhật ký trình duyệt gần nhất (${recentLogs.length} dòng) ▼`}
                </button>
                {showLogs && (
                  <pre
                    style={{
                      maxHeight: '130px',
                      overflowY: 'auto',
                      backgroundColor: '#0f172a',
                      color: '#f8fafc',
                      fontSize: '11px',
                      padding: '8px 10px',
                      borderRadius: '4px',
                      marginTop: '6px',
                      lineHeight: 1.4,
                    }}
                  >
                    {recentLogs.join('\n')}
                  </pre>
                )}
              </div>
            )}

            <div style={{ display: 'flex', justifyContent: 'center' }}>
              <button
                type="button"
                onClick={handleCancelLogin}
                data-testid="btn-cancel-fuexam-login"
                style={{
                  padding: '8px 20px',
                  fontSize: '13px',
                  fontWeight: 500,
                  color: 'var(--text-secondary, #475569)',
                  backgroundColor: 'transparent',
                  border: '1px solid var(--border-subtle, #cbd5e1)',
                  borderRadius: '5px',
                  cursor: 'pointer',
                }}
              >
                Huỷ thao tác
              </button>
            </div>
          </div>
        )}

        {/* State: success / authenticated */}
        {(state === 'success' || state === 'authenticated') && (
          <div style={{ textAlign: 'center', padding: '16px 0' }}>
            <div
              style={{
                width: '40px',
                height: '40px',
                borderRadius: '50%',
                backgroundColor: 'rgba(22, 163, 74, 0.1)',
                color: '#16a34a',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                margin: '0 auto 12px auto',
                fontWeight: 700,
                fontSize: '20px',
              }}
            >
              [✓]
            </div>
            <h3
              style={{
                fontSize: '16px',
                fontWeight: 600,
                color: '#16a34a',
                margin: '0 0 6px 0',
              }}
            >
              Đăng nhập thành công!
            </h3>
            <p style={{ fontSize: '13px', color: 'var(--text-secondary, #475569)', margin: 0 }}>
              Phiên làm việc fuexam.me đã được xác thực và lưu an toàn. Đang chuyển tiếp...
            </p>
          </div>
        )}

        {/* State: timeout */}
        {state === 'timeout' && (
          <div>
            <div
              style={{
                backgroundColor: 'rgba(239, 68, 68, 0.05)',
                border: '1px solid rgba(239, 68, 68, 0.2)',
                borderRadius: '6px',
                padding: '12px 14px',
                marginBottom: '18px',
                fontSize: '13px',
                color: '#b91c1c',
                lineHeight: 1.5,
              }}
            >
              <strong>Quá thời hạn chờ:</strong> Đã quá 5 phút mà chưa hoàn tất đăng nhập. Vui lòng thử lại.
            </div>

            <div style={{ display: 'flex', gap: '10px', justifyContent: 'flex-end' }}>
              <button
                type="button"
                onClick={onClose}
                style={{
                  padding: '8px 16px',
                  fontSize: '13px',
                  color: 'var(--text-secondary, #475569)',
                  backgroundColor: 'transparent',
                  border: '1px solid var(--border-subtle, #cbd5e1)',
                  borderRadius: '5px',
                  cursor: 'pointer',
                }}
              >
                Đóng
              </button>
              <button
                type="button"
                onClick={handleStartLogin}
                style={{
                  padding: '8px 18px',
                  fontSize: '13px',
                  fontWeight: 600,
                  color: '#ffffff',
                  backgroundColor: '#b45309',
                  border: 'none',
                  borderRadius: '5px',
                  cursor: 'pointer',
                }}
              >
                Thử lại
              </button>
            </div>
          </div>
        )}

        {/* State: failed / error (Requirement 1 & 3: Clear error + Retry button) */}
        {(state === 'failed' || state === 'error') && (
          <div>
            <div
              data-testid="fuexam-error-message"
              style={{
                backgroundColor: 'rgba(239, 68, 68, 0.06)',
                border: '1px solid rgba(239, 68, 68, 0.25)',
                borderRadius: '6px',
                padding: '14px',
                marginBottom: '18px',
                fontSize: '13px',
                color: '#991b1b',
                lineHeight: 1.6,
              }}
            >
              <div style={{ fontWeight: 700, marginBottom: '4px' }}>Lỗi tiến trình đăng nhập:</div>
              <div>{errorMessage || 'Không thể mở cửa sổ trình duyệt Chromium hoặc tiến trình đã dừng.'}</div>
            </div>

            <div
              style={{
                backgroundColor: 'var(--bg-subtle, #f8fafc)',
                border: '1px solid var(--border-subtle, #e2e8f0)',
                borderRadius: '6px',
                padding: '10px 12px',
                marginBottom: '18px',
                fontSize: '12px',
                color: 'var(--text-secondary, #475569)',
                lineHeight: 1.5,
              }}
            >
              <strong>Hướng dẫn vận hành:</strong>
              <div>
                Đảm bảo backend đang chạy từ cửa sổ console tương tác: <code style={{ color: '#0369a1' }}>python run_dev.py</code> hoặc chạy kiểm tra Chromium trong phần <strong>Cài đặt</strong>.
              </div>
            </div>

            <div style={{ display: 'flex', gap: '10px', justifyContent: 'flex-end' }}>
              <button
                type="button"
                onClick={onClose}
                style={{
                  padding: '8px 16px',
                  fontSize: '13px',
                  color: 'var(--text-secondary, #475569)',
                  backgroundColor: 'transparent',
                  border: '1px solid var(--border-subtle, #cbd5e1)',
                  borderRadius: '5px',
                  cursor: 'pointer',
                }}
              >
                Đóng
              </button>
              <button
                type="button"
                onClick={handleStartLogin}
                data-testid="btn-retry-fuexam-login"
                style={{
                  padding: '8px 18px',
                  fontSize: '13px',
                  fontWeight: 600,
                  color: '#ffffff',
                  backgroundColor: '#b45309',
                  border: 'none',
                  borderRadius: '5px',
                  cursor: 'pointer',
                }}
              >
                Thử lại
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
