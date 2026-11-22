import React, { useEffect, useState, useRef } from 'react';
import type { FuexamLoginStatus, FuexamLoginSession, FuexamAuthStatus } from '../types';

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
  // Sync state & extension state
  const [successUsername, setSuccessUsername] = useState<string | null>(null);
  const [extensionHeartbeatAlive, setExtensionHeartbeatAlive] = useState<boolean>(true);
  const [secondsOpen, setSecondsOpen] = useState<number>(0);
  const [showExtensionWarning, setShowExtensionWarning] = useState<boolean>(false);

  // Advanced Chromium headed launcher state
  const [chromiumState, setChromiumState] = useState<FuexamLoginStatus>('idle');
  const [chromiumMessage, setChromiumMessage] = useState<string>('');
  const [chromiumError, setChromiumError] = useState<string | null>(null);
  const [recentLogs, setRecentLogs] = useState<string[]>([]);
  const [showLogs, setShowLogs] = useState<boolean>(false);

  // Direct extension sync via externally_connectable
  const EXTENSION_ID = 'kicplcdfmbcfjildbbimpfiljlmfokea';
  const [isSyncingDirectly, setIsSyncingDirectly] = useState<boolean>(false);
  const [syncFeedback, setSyncFeedback] = useState<string | null>(null);

  const triggerDirectExtensionSync = () => {
    setIsSyncingDirectly(true);
    setSyncFeedback('Đang gửi yêu cầu trực tiếp tới extension...');
    fetch('/api/auth/fuexam/sync-request', { method: 'POST' }).catch(() => {});

    if (typeof (window as any).chrome !== 'undefined' && (window as any).chrome?.runtime?.sendMessage) {
      try {
        (window as any).chrome.runtime.sendMessage(
          EXTENSION_ID,
          { type: 'SYNC_FUEXAM_SESSION' },
          (response: any) => {
            setIsSyncingDirectly(false);
            if ((window as any).chrome?.runtime?.lastError) {
              setSyncFeedback('Chờ backend nhận phiên từ heartbeat...');
              setTimeout(() => setSyncFeedback(null), 3000);
              return;
            }
            if (response && response.ok) {
              setSuccessUsername(response.username || 'Thành viên');
              setTimeout(() => onSuccess(), 800);
            } else if (response && response.message) {
              setSyncFeedback(response.message);
              setTimeout(() => setSyncFeedback(null), 4000);
            }
          }
        );
      } catch (e: any) {
        setIsSyncingDirectly(false);
        setSyncFeedback('Lỗi gọi extension.');
        setTimeout(() => setSyncFeedback(null), 3000);
      }
    } else {
      setIsSyncingDirectly(false);
      setSyncFeedback('Trình duyệt chưa hỗ trợ chrome.runtime hoặc chưa nạp extension.');
      setTimeout(() => setSyncFeedback(null), 3000);
    }
  };

  const pollTimerRef = useRef<any>(null);
  const secondsTimerRef = useRef<any>(null);

  // When modal opens/closes
  useEffect(() => {
    if (!isOpen) {
      if (pollTimerRef.current) clearInterval(pollTimerRef.current);
      if (secondsTimerRef.current) clearInterval(secondsTimerRef.current);
      setSuccessUsername(null);
      setSecondsOpen(0);
      setShowExtensionWarning(false);
      setChromiumState('idle');
      setChromiumMessage('');
      setChromiumError(null);
      setRecentLogs([]);
      return;
    }

    // 1. Trigger direct extension sync via externally_connectable & notify backend
    triggerDirectExtensionSync();

    // 2. Start seconds timer for 30s extension heartbeat warning
    setSecondsOpen(0);
    secondsTimerRef.current = setInterval(() => {
      setSecondsOpen((prev) => {
        const next = prev + 1;
        if (next >= 30) {
          setShowExtensionWarning(true);
        }
        return next;
      });
    }, 1000);

    // 3. Status polling loop (check auth status & chromium session status)
    const checkStatus = async () => {
      try {
        // A. Check if valid auth is detected (from extension sync or chromium)
        const authRes = await fetch('/api/auth/fuexam/status');
        if (authRes.ok) {
          const authData: FuexamAuthStatus = await authRes.json();
          if (authData.extension_heartbeat_alive !== undefined) {
            setExtensionHeartbeatAlive(authData.extension_heartbeat_alive);
            if (authData.extension_heartbeat_alive) {
              setShowExtensionWarning(false);
            }
          }
          if (authData.logged_in && authData.username) {
            setSuccessUsername(authData.username);
            setTimeout(() => {
              onSuccess();
            }, 1000);
            return;
          }
        }

        // B. Check advanced Chromium session status if active
        const sessionRes = await fetch('/api/auth/fuexam/login/status');
        if (sessionRes.ok) {
          const session: FuexamLoginSession = await sessionRes.json();
          if (session.recent_logs) {
            setRecentLogs(session.recent_logs);
          }
          if (session.state === 'success' || session.state === 'authenticated') {
            setSuccessUsername(session.message || 'Thành viên');
            setTimeout(() => {
              onSuccess();
            }, 1000);
          } else if (session.state === 'waiting') {
            setChromiumState('waiting');
            setChromiumMessage(session.message || 'Hãy đăng nhập trong cửa sổ vừa mở.');
          } else if (session.state === 'starting') {
            setChromiumState('starting');
            setChromiumMessage(session.message || 'Đang khởi động cửa sổ Chromium...');
          } else if (session.state === 'timeout') {
            setChromiumState('timeout');
            setChromiumMessage(session.message || 'Quá thời hạn chờ 5 phút.');
          } else if (session.state === 'failed' || session.state === 'error') {
            setChromiumState('failed');
            setChromiumError(session.error || session.message || 'Tiến trình đăng nhập thất bại.');
          }
        }
      } catch (e) {
        // network or server starting
      }
    };

    checkStatus();
    pollTimerRef.current = setInterval(checkStatus, 1500);

    return () => {
      if (pollTimerRef.current) clearInterval(pollTimerRef.current);
      if (secondsTimerRef.current) clearInterval(secondsTimerRef.current);
    };
  }, [isOpen, onSuccess]);

  // Tab visibility listener: trigger sync-request & check status immediately when user returns to tab
  useEffect(() => {
    const handleVisibility = () => {
      if (document.visibilityState === 'visible' && isOpen) {
        triggerDirectExtensionSync();
        fetch('/api/auth/fuexam/status')
          .then((r) => (r.ok ? r.json() : null))
          .then((data: FuexamAuthStatus | null) => {
            if (data?.logged_in && data.username) {
              setSuccessUsername(data.username);
              setTimeout(() => onSuccess(), 800);
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

  // Primary Action: Open fuexam.me/login in user's default browser
  const handleOpenBrowserLogin = () => {
    window.open('https://fuexam.me/login/', '_blank');
  };

  // Chromium actions
  const handleStartChromiumLogin = async () => {
    if (!isBackendReady) {
      setChromiumState('failed');
      setChromiumError('Backend chưa sẵn sàng. Vui lòng đợi trong giây lát hoặc kiểm tra backend console.');
      return;
    }

    setChromiumState('starting');
    setChromiumMessage('Đang kết nối và khởi động cửa sổ Chromium...');
    setChromiumError(null);

    try {
      const res = await fetch('/api/auth/fuexam/login/start', { method: 'POST' });
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        setChromiumState('failed');
        setChromiumError(
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
        setSuccessUsername('Thành viên');
        setTimeout(() => onSuccess(), 800);
      } else if (effectiveState === 'failed' || effectiveState === 'error') {
        setChromiumState('failed');
        setChromiumError(data.error || data.message || 'Không thể mở cửa sổ trình duyệt Chromium.');
      } else if (effectiveState === 'waiting') {
        setChromiumState('waiting');
        setChromiumMessage(data.message || 'Hãy đăng nhập trong cửa sổ vừa mở.');
      } else {
        setChromiumState(effectiveState);
        setChromiumMessage(data.message || '');
      }
    } catch (err: any) {
      setChromiumState('failed');
      setChromiumError(
        'Lỗi kết nối máy chủ backend (/api/auth/fuexam/login/start bị từ chối kết nối). Backend chưa sẵn sàng hoặc đã dừng.'
      );
    }
  };

  const handleCancelChromiumLogin = async () => {
    try {
      await fetch('/api/auth/fuexam/login/cancel', { method: 'POST' });
    } catch {}
    setChromiumState('idle');
    setChromiumMessage('Đã huỷ phiên Chromium.');
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
          maxWidth: '540px',
          padding: '28px',
          boxShadow: '0 20px 25px -5px rgba(0, 0, 0, 0.1), 0 8px 10px -6px rgba(0, 0, 0, 0.1)',
        }}
      >
        {/* Header */}
        <div style={{ marginBottom: '16px' }}>
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

        {/* Success State */}
        {successUsername ? (
          <div style={{ textAlign: 'center', padding: '24px 0' }}>
            <div
              style={{
                width: '44px',
                height: '44px',
                borderRadius: '50%',
                backgroundColor: 'rgba(22, 163, 74, 0.1)',
                color: '#16a34a',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                margin: '0 auto 12px auto',
                fontWeight: 700,
                fontSize: '22px',
              }}
            >
              ✓
            </div>
            <h3
              style={{
                fontSize: '17px',
                fontWeight: 600,
                color: '#16a34a',
                margin: '0 0 6px 0',
              }}
            >
              Đăng nhập thành công!
            </h3>
            <p style={{ fontSize: '14px', color: 'var(--text-secondary, #475569)', margin: 0 }}>
              Đã nhận phiên từ tài khoản <strong>{successUsername}</strong>. Hệ thống đang tự động tiếp tục...
            </p>
          </div>
        ) : (
          <div>
            {/* Mid-Job Notice (Requirement 6) */}
            {isMidJob && (
              <div
                data-testid="mid-job-expiration-notice"
                style={{
                  backgroundColor: '#fffbeb',
                  border: '1px solid #fde68a',
                  borderRadius: '6px',
                  padding: '12px 14px',
                  marginBottom: '16px',
                  fontSize: '13px',
                  color: '#92400e',
                  lineHeight: 1.5,
                }}
              >
                <div style={{ fontWeight: 700, marginBottom: '2px' }}>
                  ⚠️ Đăng nhập lại fuexam.me ở tab trình duyệt, DocxStacked sẽ tự nhận
                </div>
                <div>Tiến trình cào đề đang tạm dừng và sẽ tự động tiếp tục ngay khi nhận phiên mới.</div>
              </div>
            )}

            {/* 30s Extension Missing Warning (Requirement 5) */}
            {showExtensionWarning && !extensionHeartbeatAlive && (
              <div
                data-testid="extension-missing-warning"
                style={{
                  backgroundColor: '#fef2f2',
                  border: '1px solid #fecaca',
                  borderRadius: '6px',
                  padding: '12px 14px',
                  marginBottom: '16px',
                  fontSize: '12.5px',
                  color: '#991b1b',
                  lineHeight: 1.5,
                }}
              >
                <div style={{ fontWeight: 700, marginBottom: '4px' }}>
                  ⚠️ Chưa phát hiện extension DocxStacked
                </div>
                <div>
                  Vui lòng mở <code>chrome://extensions</code> (hoặc <code>edge://extensions</code>), bấm nút <strong>Tải lại (Reload)</strong> extension DocxStacked và chấp nhận quyền mới (<strong>Cookies &amp; fuexam.me</strong>).
                </div>
              </div>
            )}

            {/* Default Extension Flow: Explanation */}
            <p
              style={{
                fontSize: '13px',
                color: 'var(--text-secondary, #475569)',
                lineHeight: 1.6,
                margin: '0 0 16px 0',
              }}
            >
              DocxStacked tự động đồng bộ phiên đăng nhập từ extension trình duyệt của bạn (Chrome / Edge). Bạn không cần nhập mật khẩu vào DocxStacked.
            </p>

            {/* Auto-sync Status Card */}
            <div
              data-testid="extension-sync-status"
              style={{
                backgroundColor: 'var(--bg-subtle, #f8fafc)',
                border: '1px solid var(--border-subtle, #e2e8f0)',
                borderRadius: '6px',
                padding: '14px',
                marginBottom: '20px',
                display: 'flex',
                alignItems: 'center',
                gap: '12px',
              }}
            >
              <div
                style={{
                  width: '20px',
                  height: '20px',
                  border: '2.5px solid #cbd5e1',
                  borderTopColor: '#b45309',
                  borderRadius: '50%',
                  animation: 'spin 1s linear infinite',
                  flexShrink: 0,
                }}
              />
              <div style={{ fontSize: '13px', color: 'var(--text-secondary, #475569)', lineHeight: 1.4 }}>
                <strong>Đang chờ đồng bộ phiên ({secondsOpen}s):</strong> Mở tab fuexam.me đăng nhập, modal sẽ tự động phát hiện và đóng lại.
                {syncFeedback && (
                  <div style={{ marginTop: '4px', fontSize: '12px', color: '#b45309', fontWeight: 500 }}>
                    {syncFeedback}
                  </div>
                )}
              </div>
            </div>

            {/* Primary Action Button & Fast Sync (Requirement 3) */}
            <div style={{ display: 'flex', gap: '10px', justifyContent: 'flex-end', flexWrap: 'wrap', marginBottom: '20px' }}>
              <button
                type="button"
                onClick={onClose}
                style={{
                  padding: '9px 16px',
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
                onClick={triggerDirectExtensionSync}
                disabled={isSyncingDirectly}
                data-testid="btn-sync-now"
                style={{
                  padding: '9px 16px',
                  fontSize: '13px',
                  fontWeight: 600,
                  color: '#b45309',
                  backgroundColor: 'rgba(217, 119, 6, 0.08)',
                  border: '1px solid rgba(217, 119, 6, 0.3)',
                  borderRadius: '5px',
                  cursor: isSyncingDirectly ? 'wait' : 'pointer',
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '6px',
                }}
              >
                <span>{isSyncingDirectly ? 'Đang đồng bộ...' : 'Đồng bộ ngay'}</span>
              </button>
              <button
                type="button"
                onClick={handleOpenBrowserLogin}
                data-testid="btn-open-browser-fuexam-login"
                style={{
                  padding: '9px 20px',
                  fontSize: '13px',
                  fontWeight: 600,
                  color: '#ffffff',
                  backgroundColor: '#b45309',
                  border: 'none',
                  borderRadius: '5px',
                  cursor: 'pointer',
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '6px',
                }}
              >
                <span>Mở fuexam.me/login trong trình duyệt của bạn</span>
                <span style={{ fontSize: '11px' }}>↗</span>
              </button>
            </div>

            {/* Collapsed Advanced Section: Chromium Launcher (Requirement 5) */}
            <details
              style={{
                borderTop: '1px solid var(--border-subtle, #e2e8f0)',
                paddingTop: '12px',
                marginTop: '12px',
              }}
            >
              <summary
                data-testid="summary-advanced-chromium"
                style={{
                  fontSize: '12px',
                  color: 'var(--text-muted, #64748b)',
                  cursor: 'pointer',
                  userSelect: 'none',
                  fontWeight: 500,
                }}
              >
                Nâng cao: Dùng cửa sổ Chromium riêng (thu gọn mặc định)
              </summary>

              <div
                style={{
                  backgroundColor: 'var(--bg-subtle, #f8fafc)',
                  border: '1px solid var(--border-subtle, #e2e8f0)',
                  borderRadius: '6px',
                  padding: '14px',
                  marginTop: '10px',
                }}
              >
                <p style={{ fontSize: '12px', color: 'var(--text-secondary, #475569)', margin: '0 0 12px 0', lineHeight: 1.5 }}>
                  Khởi động cửa sổ Playwright Chromium độc lập để nhập thông tin đăng nhập. Chỉ dùng khi bạn không thể cài extension.
                </p>

                {!isBackendReady && (
                  <div
                    data-testid="fuexam-backend-not-ready-notice"
                    style={{
                      backgroundColor: '#fef2f2',
                      border: '1px solid #fecaca',
                      borderRadius: '4px',
                      padding: '8px 10px',
                      marginBottom: '10px',
                      fontSize: '11.5px',
                      color: '#991b1b',
                    }}
                  >
                    ⚠️ Backend chưa sẵn sàng, đang thử lại kết nối...
                  </div>
                )}

                {chromiumState === 'starting' && (
                  <div style={{ textAlign: 'center', padding: '10px 0', fontSize: '12px', color: '#b45309' }}>
                    <div
                      style={{
                        width: '24px',
                        height: '24px',
                        border: '2px solid #cbd5e1',
                        borderTopColor: '#b45309',
                        borderRadius: '50%',
                        margin: '0 auto 8px auto',
                        animation: 'spin 1s linear infinite',
                      }}
                    />
                    <div>{chromiumMessage || 'Đang chuẩn bị Chromium...'}</div>
                  </div>
                )}

                {chromiumState === 'waiting' && (
                  <div style={{ textAlign: 'center', padding: '10px 0' }}>
                    <div style={{ fontSize: '13px', fontWeight: 600, color: '#b45309', marginBottom: '6px' }}>
                      Cửa sổ Chromium đã mở ("DocxStacked - Đăng nhập fuexam")
                    </div>
                    <div style={{ fontSize: '12px', color: '#64748b', marginBottom: '10px' }}>
                      {chromiumMessage || 'Hãy nhập thông tin đăng nhập trên cửa sổ Chromium.'}
                    </div>
                    <button
                      type="button"
                      onClick={handleCancelChromiumLogin}
                      data-testid="btn-cancel-fuexam-login"
                      style={{
                        padding: '6px 14px',
                        fontSize: '12px',
                        color: '#64748b',
                        background: '#fff',
                        border: '1px solid #cbd5e1',
                        borderRadius: '4px',
                        cursor: 'pointer',
                      }}
                    >
                      Huỷ phiên Chromium
                    </button>
                  </div>
                )}

                {(chromiumState === 'failed' || chromiumState === 'error') && (
                  <div
                    data-testid="fuexam-error-message"
                    style={{
                      backgroundColor: 'rgba(239, 68, 68, 0.08)',
                      border: '1px solid rgba(239, 68, 68, 0.25)',
                      borderRadius: '4px',
                      padding: '10px',
                      marginBottom: '10px',
                      fontSize: '12px',
                      color: '#991b1b',
                    }}
                  >
                    <div style={{ fontWeight: 600 }}>Lỗi Chromium:</div>
                    <div>{chromiumError || 'Không thể mở trình duyệt.'}</div>
                  </div>
                )}

                {chromiumState === 'idle' && (
                  <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
                    <button
                      type="button"
                      onClick={handleStartChromiumLogin}
                      disabled={!isBackendReady}
                      data-testid="btn-open-fuexam-login"
                      style={{
                        padding: '7px 14px',
                        fontSize: '12px',
                        fontWeight: 600,
                        color: '#ffffff',
                        backgroundColor: isBackendReady ? '#475569' : '#94a3b8',
                        border: 'none',
                        borderRadius: '4px',
                        cursor: isBackendReady ? 'pointer' : 'not-allowed',
                      }}
                    >
                      Mở cửa sổ Chromium riêng
                    </button>
                  </div>
                )}

                {(chromiumState === 'failed' || chromiumState === 'error') && (
                  <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: '8px' }}>
                    <button
                      type="button"
                      onClick={handleStartChromiumLogin}
                      data-testid="btn-retry-fuexam-login"
                      style={{
                        padding: '6px 12px',
                        fontSize: '12px',
                        fontWeight: 600,
                        color: '#fff',
                        backgroundColor: '#b45309',
                        border: 'none',
                        borderRadius: '4px',
                        cursor: 'pointer',
                      }}
                    >
                      Thử lại Chromium
                    </button>
                  </div>
                )}

                {recentLogs.length > 0 && (
                  <div style={{ marginTop: '10px' }}>
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
                        padding: 0,
                      }}
                    >
                      {showLogs ? 'Ẩn nhật ký ▲' : `Xem nhật ký Chromium (${recentLogs.length} dòng) ▼`}
                    </button>
                    {showLogs && (
                      <pre
                        style={{
                          maxHeight: '110px',
                          overflowY: 'auto',
                          backgroundColor: '#0f172a',
                          color: '#f8fafc',
                          fontSize: '10.5px',
                          padding: '6px 8px',
                          borderRadius: '4px',
                          marginTop: '4px',
                          lineHeight: 1.4,
                        }}
                      >
                        {recentLogs.join('\n')}
                      </pre>
                    )}
                  </div>
                )}
              </div>
            </details>
          </div>
        )}
      </div>
    </div>
  );
};
