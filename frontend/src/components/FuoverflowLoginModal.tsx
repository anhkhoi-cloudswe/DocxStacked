import React from 'react';

interface FuoverflowLoginModalProps {
  isOpen: boolean;
  gateState: 'checking' | 'no_extension' | 'logged_out' | 'logged_in';
  onCheckAgain: () => void;
  onClose?: () => void;
  lastFailureReason?: string;
}

export const FuoverflowLoginModal: React.FC<FuoverflowLoginModalProps> = ({
  isOpen,
  gateState,
  onCheckAgain,
  onClose,
  lastFailureReason,
}) => {
  if (!isOpen || gateState === 'logged_in') return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      data-testid="fuoverflow-login-modal"
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
        <div style={{ marginBottom: '20px' }}>
          <div
            style={{
              fontSize: '11px',
              fontWeight: 600,
              color: 'var(--primary, #0284c7)',
              backgroundColor: 'rgba(2, 132, 199, 0.08)',
              display: 'inline-block',
              padding: '2px 8px',
              borderRadius: '4px',
              marginBottom: '8px',
              letterSpacing: '0.04em',
              textTransform: 'uppercase',
            }}
          >
            FUOverflow · Xác thực Extension
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
            {gateState === 'checking' && 'Đang kiểm tra phiên đăng nhập...'}
            {gateState === 'no_extension' && 'Chưa kết nối Extension DocxStacked'}
            {gateState === 'logged_out' && 'Chưa đăng nhập tài khoản FUOverflow'}
          </h2>
        </div>

        {gateState === 'checking' && (
          <div style={{ textAlign: 'center', padding: '16px 0' }}>
            <div
              style={{
                width: '32px',
                height: '32px',
                border: '3px solid #e2e8f0',
                borderTopColor: 'var(--primary, #0284c7)',
                borderRadius: '50%',
                margin: '0 auto 12px auto',
                animation: 'spin 1s linear infinite',
              }}
            />
            <p style={{ fontSize: '13px', color: 'var(--text-secondary, #475569)', margin: 0 }}>
              Đang xác minh tín hiệu từ Extension DocxStacked và diễn đàn fuoverflow.com...
            </p>
          </div>
        )}

        {gateState === 'no_extension' && (
          <div>
            <p
              style={{
                fontSize: '13px',
                color: 'var(--text-secondary, #475569)',
                lineHeight: 1.6,
                margin: '0 0 16px 0',
              }}
            >
              Extension DocxStacked trên Google Chrome / Edge là nguồn xác thực duy nhất cho nền tảng FUOverflow. Vui lòng
              cài đặt hoặc bật Extension trên trình duyệt này để tiếp tục.
            </p>

            <div
              style={{
                backgroundColor: 'var(--bg-subtle, #f8fafc)',
                border: '1px solid var(--border-subtle, #e2e8f0)',
                borderRadius: '6px',
                padding: '12px',
                marginBottom: '20px',
                fontSize: '12px',
                color: 'var(--text-secondary, #475569)',
                lineHeight: 1.5,
              }}
            >
              <div><strong>Hướng dẫn cài đặt Extension:</strong></div>
              <div>1. Mở trang Quản lý tiện ích Chrome: <code style={{ color: '#0369a1' }}>chrome://extensions</code></div>
              <div>2. Bật chế độ dành cho nhà phát triển (Developer mode).</div>
              <div>3. Tải tiện ích đã giải nén từ thư mục: <code style={{ color: '#0369a1' }}>extension/</code></div>
              {lastFailureReason && (
                <div style={{ marginTop: '6px', fontSize: '11px', color: 'var(--text-muted, #94a3b8)' }}>
                  Chi tiết: {lastFailureReason}
                </div>
              )}
            </div>

            <div style={{ display: 'flex', gap: '10px', justifyContent: 'flex-end' }}>
              {onClose && (
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
              )}
              <button
                type="button"
                onClick={onCheckAgain}
                style={{
                  padding: '8px 18px',
                  fontSize: '13px',
                  fontWeight: 600,
                  color: '#ffffff',
                  backgroundColor: 'var(--primary, #0284c7)',
                  border: 'none',
                  borderRadius: '5px',
                  cursor: 'pointer',
                }}
              >
                Kiểm tra lại
              </button>
            </div>
          </div>
        )}

        {gateState === 'logged_out' && (
          <div>
            <p
              style={{
                fontSize: '13px',
                color: 'var(--text-secondary, #475569)',
                lineHeight: 1.6,
                margin: '0 0 16px 0',
              }}
            >
              Extension DocxStacked đã hoạt động nhưng bạn chưa đăng nhập tài khoản trên diễn đàn fuoverflow.com. Vui lòng
              mở trang đăng nhập của diễn đàn trên tab mới. Cửa sổ này sẽ tự động đóng ngay khi bạn hoàn tất đăng nhập.
            </p>

            <div style={{ display: 'flex', gap: '10px', justifyContent: 'flex-end', marginTop: '24px' }}>
              {onClose && (
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
              )}
              <button
                type="button"
                onClick={onCheckAgain}
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
                Kiểm tra lại
              </button>
              <a
                href="https://fuoverflow.com/login"
                target="_blank"
                rel="noopener noreferrer"
                data-testid="btn-open-fuoverflow-login"
                style={{
                  padding: '8px 18px',
                  fontSize: '13px',
                  fontWeight: 600,
                  color: '#ffffff',
                  backgroundColor: 'var(--primary, #0284c7)',
                  border: 'none',
                  borderRadius: '5px',
                  textDecoration: 'none',
                  display: 'inline-flex',
                  alignItems: 'center',
                }}
              >
                Mở trang đăng nhập FUOverflow
              </a>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
