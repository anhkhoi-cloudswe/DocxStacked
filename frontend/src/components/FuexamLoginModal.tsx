import React, { useEffect, useState, useRef } from 'react';
import type { FuexamLoginStatus, FuexamLoginSession } from '../types';

interface FuexamLoginModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess: () => void;
  isMidJob?: boolean;
}

export const FuexamLoginModal: React.FC<FuexamLoginModalProps> = ({
  isOpen,
  onClose,
  onSuccess,
  isMidJob = false,
}) => {
  const [state, setState] = useState<FuexamLoginStatus>('idle');
  const [message, setMessage] = useState<string>('');
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const pollTimerRef = useRef<any>(null);

  useEffect(() => {
    if (!isOpen) {
      if (pollTimerRef.current) clearInterval(pollTimerRef.current);
      setState('idle');
      setMessage('');
      setErrorMessage(null);
      return;
    }

    // Check status on open
    fetch('/api/auth/fuexam/status')
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (data && data.logged_in) {
          setState('authenticated');
          setTimeout(() => {
            onSuccess();
          }, 800);
        }
      })
      .catch(() => {});
  }, [isOpen, onSuccess]);

  // Polling when waiting
  useEffect(() => {
    if (state !== 'waiting') {
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
          if (session.state === 'authenticated') {
            setState('authenticated');
            setMessage('Đăng nhập thành công! Đang tự động cập nhật hệ thống...');
            setTimeout(() => {
              onSuccess();
            }, 1000);
          } else if (session.state === 'timeout') {
            setState('timeout');
            setMessage(session.message || 'Quá thời hạn chờ 5 phút.');
          } else if (session.state === 'error') {
            setState('error');
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
    setState('waiting');
    setMessage('Đang kết nối và khởi động cửa sổ Chromium...');
    setErrorMessage(null);

    try {
      const res = await fetch('/api/auth/fuexam/login/start', { method: 'POST' });
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        setState('error');
        setErrorMessage(
          errData.detail ||
            errData.error ||
            'Không thể mở cửa sổ trình duyệt Chromium từ môi trường ngầm hoặc phiên không tương tác. Vui lòng chạy backend từ PowerShell trên máy thật: python run_dev.py'
        );
        return;
      }
      const data: FuexamLoginSession = await res.json();
      if (data.state === 'authenticated') {
        setState('authenticated');
        setTimeout(() => onSuccess(), 800);
      } else if (data.state === 'error') {
        setState('error');
        setErrorMessage(data.error || data.message || 'Không thể mở cửa sổ trình duyệt Chromium.');
      } else {
        setState('waiting');
        setMessage(data.message || 'Hãy đăng nhập trong cửa sổ vừa mở.');
      }
    } catch (err: any) {
      setState('error');
      setErrorMessage(
        'Lỗi kết nối máy chủ backend. Khắc phục: Chạy backend từ PowerShell trên máy thật: python run_dev.py'
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

        {/* Body based on State Machine */}
        {state === 'idle' && (
          <div>
            <p
              style={{
                fontSize: '13px',
                color: 'var(--text-secondary, #475569)',
                lineHeight: 1.6,
                margin: '0 0 20px 0',
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
                marginBottom: '20px',
                fontSize: '12px',
                color: 'var(--text-secondary, #475569)',
                lineHeight: 1.5,
              }}
            >
              <div style={{ fontWeight: 600, color: 'var(--text-primary, #0f172a)', marginBottom: '4px' }}>
                Phương thức đăng nhập duy nhất:
              </div>
              <div>
                Hệ thống sẽ mở cửa sổ Chromium thật để bạn tự gõ tài khoản và mật khẩu trực tiếp trên diễn đàn.
              </div>
            </div>

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
                data-testid="btn-open-fuexam-login"
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
                Mở cửa sổ đăng nhập
              </button>
            </div>
          </div>
        )}

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
                margin: '0 0 20px 0',
              }}
            >
              {message || 'Cửa sổ trình duyệt Chromium đã được khởi động. Hãy nhập tài khoản fuexam.me của bạn trên cửa sổ đó. Hệ thống đang tự động theo dõi (tối đa 5 phút)...'}
            </p>

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

        {state === 'authenticated' && (
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
              [v]
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
              <strong>Quá thời hạn chờ:</strong> Đã quá 5 phút mà chưa hoàn tất đăng nhập. Vui lòng thử lại hoặc đăng
              nhập qua dòng lệnh CLI.
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

        {state === 'error' && (
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
              <div style={{ fontWeight: 700, marginBottom: '4px' }}>Không thể mở cửa sổ trình duyệt Chromium:</div>
              <div>{errorMessage}</div>
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
              <div>Mở cửa sổ PowerShell thật trên Windows: <code style={{ color: '#0369a1' }}>python run_dev.py</code> (hoặc chạy <code style={{ color: '#0369a1' }}>python scripts/fuexam_login.py</code>) để mở cửa sổ Chromium.</div>
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
