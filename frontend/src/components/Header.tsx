import React, { useEffect, useState } from 'react';

interface HeaderProps {
  onNavigateSettings?: () => void;
  onNavigateHome?: () => void;
  onNavigateDocuments?: () => void;
  currentScreen?: string;
}

export const Header: React.FC<HeaderProps> = ({
  onNavigateSettings,
  onNavigateHome,
  onNavigateDocuments,
  currentScreen,
}) => {
  const [isDark, setIsDark] = useState<boolean>(() => {
    return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
  });

  const [authStatus, setAuthStatus] = useState<{ logged_in: boolean; username?: string } | null>(null);

  const checkAuth = () => {
    fetch('/api/auth/status')
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (data) setAuthStatus(data);
      })
      .catch(() => {});
  };

  useEffect(() => {
    checkAuth();
    const interval = setInterval(checkAuth, 15000);
    return () => clearInterval(interval);
  }, []);

  const handleLogout = async () => {
    if (!window.confirm('Bạn có chắc chắn muốn đăng xuất phiên tài khoản FUOverflow?')) return;
    try {
      await fetch('/api/auth/logout', { method: 'POST' });
      setAuthStatus({ logged_in: false });
      window.location.reload();
    } catch (e) {
      console.error('Logout error:', e);
    }
  };

  useEffect(() => {
    if (isDark) {
      document.body.classList.add('theme-dark');
      document.body.classList.remove('theme-light');
    } else {
      document.body.classList.add('theme-light');
      document.body.classList.remove('theme-dark');
    }
  }, [isDark]);

  return (
    <header
      role="banner"
      style={{
        borderBottom: '1px solid var(--border-subtle)',
        backgroundColor: 'var(--bg-surface)',
        padding: 'var(--space-2) var(--space-4)',
        position: 'sticky',
        top: 0,
        zIndex: 50,
      }}
    >
      <div className="header-inner">
        {/* Brand & Subtitle */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', flexWrap: 'wrap' }}>
          <a
            href="/"
            role="button"
            onClick={(e) => {
              e.preventDefault();
              onNavigateHome?.();
            }}
            aria-label="DocxStacked - Về trang chủ"
            style={{
              fontFamily: 'var(--font-serif)',
              fontSize: 'var(--text-xl)',
              fontWeight: 700,
              color: 'var(--primary)',
              letterSpacing: '-0.02em',
              textDecoration: 'none',
              cursor: onNavigateHome ? 'pointer' : 'default',
              display: 'inline-flex',
              alignItems: 'center',
            }}
          >
            DocxStacked
          </a>
          <span
            style={{
              fontFamily: 'var(--font-sans)',
              fontSize: '11px',
              padding: '2px 8px',
              backgroundColor: 'var(--bg-subtle)',
              border: '1px solid var(--border-subtle)',
              borderRadius: 'var(--radius-sm)',
              color: 'var(--text-secondary)',
              fontWeight: 500,
            }}
          >
            Biên soạn đề ôn FE / PE
          </span>
        </div>

        {/* Navigation & Controls */}
        <nav className="header-nav" aria-label="Điều hướng chính">
          {onNavigateDocuments && (
            <button
              type="button"
              onClick={onNavigateDocuments}
              aria-label="Kho tài liệu đã cào"
              style={{
                background: currentScreen === 'documents' ? 'var(--bg-hover)' : 'var(--bg-surface)',
                border: `1px solid ${currentScreen === 'documents' ? 'var(--primary)' : 'var(--border-strong)'}`,
                borderRadius: 'var(--radius-sm)',
                padding: '6px 10px',
                fontSize: 'var(--text-xs)',
                fontWeight: 600,
                color: currentScreen === 'documents' ? 'var(--primary)' : 'var(--text-secondary)',
                cursor: 'pointer',
                display: 'inline-flex',
                alignItems: 'center',
                gap: '6px',
                minHeight: '34px',
              }}
            >
              <span aria-hidden="true">📚</span>
              <span>Tài liệu đã cào</span>
            </button>
          )}

          {onNavigateSettings && (
            <button
              type="button"
              onClick={onNavigateSettings}
              aria-label="Cài đặt hệ thống"
              style={{
                background: currentScreen === 'settings' ? 'var(--bg-hover)' : 'var(--bg-surface)',
                border: `1px solid ${currentScreen === 'settings' ? 'var(--primary)' : 'var(--border-strong)'}`,
                borderRadius: 'var(--radius-sm)',
                padding: '6px 10px',
                fontSize: 'var(--text-xs)',
                fontWeight: 600,
                color: currentScreen === 'settings' ? 'var(--primary)' : 'var(--text-secondary)',
                cursor: 'pointer',
                display: 'inline-flex',
                alignItems: 'center',
                gap: '6px',
                minHeight: '34px',
              }}
            >
              <span aria-hidden="true">⚙️</span>
              <span>Cài đặt</span>
            </button>
          )}

          {authStatus?.logged_in && (
            <div style={{ display: 'inline-flex', alignItems: 'center', gap: '6px' }}>
              <span
                style={{
                  fontSize: '11px',
                  fontFamily: 'var(--font-mono)',
                  color: 'var(--text-secondary)',
                  padding: '4px 8px',
                  backgroundColor: 'var(--bg-subtle)',
                  borderRadius: 'var(--radius-sm)',
                  border: '1px solid var(--border-subtle)',
                  whiteSpace: 'nowrap',
                }}
              >
                👤 {authStatus.username || 'Thành viên'}
              </span>
              <button
                type="button"
                onClick={handleLogout}
                aria-label="Đăng xuất khỏi tài khoản FUOverflow"
                style={{
                  background: 'none',
                  border: '1px solid var(--border-subtle)',
                  borderRadius: 'var(--radius-sm)',
                  padding: '5px 8px',
                  fontSize: 'var(--text-xs)',
                  fontWeight: 600,
                  color: '#E53E3E',
                  cursor: 'pointer',
                  minHeight: '34px',
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '4px',
                }}
                title="Đăng xuất khỏi tài khoản FUOverflow"
              >
                <span aria-hidden="true">🚪</span>
                <span>Thoát</span>
              </button>
            </div>
          )}

          <button
            type="button"
            onClick={() => setIsDark(!isDark)}
            aria-label={isDark ? 'Chuyển sang giao diện sáng' : 'Chuyển sang giao diện tối'}
            style={{
              background: 'none',
              border: '1px solid var(--border-subtle)',
              borderRadius: 'var(--radius-sm)',
              padding: '5px 10px',
              fontSize: 'var(--text-xs)',
              fontFamily: 'var(--font-sans)',
              color: 'var(--text-secondary)',
              cursor: 'pointer',
              display: 'inline-flex',
              alignItems: 'center',
              gap: '6px',
              minHeight: '34px',
            }}
          >
            <span aria-hidden="true">{isDark ? '☀️' : '🌙'}</span>
            <span className="desktop-only">{isDark ? 'Sáng' : 'Tối'}</span>
          </button>
        </nav>
      </div>
    </header>
  );
};
