import React, { useEffect, useState } from 'react';
import type { PlatformType } from '../types';
import { ActivityIcon, BookIcon, LogoutIcon, MoonIcon, SettingsIcon, SunIcon, UserIcon } from './icons';
import { confirmModal } from './ModalDialog';

interface HeaderProps {
  onNavigateSettings?: () => void;
  onNavigateHome?: () => void;
  onNavigateDocuments?: () => void;
  onNavigateProgress?: () => void;
  activeJobId?: string | null;
  onOpenLogin?: () => void;
  currentScreen?: string;
  isBlocked?: boolean;
  isLoggedIn?: boolean;
  username?: string;
  onLogout?: () => void;
  platform?: PlatformType | null;
  onSwitchPlatform?: () => void;
  authSource?: 'headed_chromium' | 'extension' | 'server' | null;
}

export const Header: React.FC<HeaderProps> = ({
  onNavigateSettings,
  onNavigateHome,
  onNavigateDocuments,
  onNavigateProgress,
  activeJobId,
  currentScreen,
  isBlocked = false,
  isLoggedIn = false,
  username,
  onLogout,
  platform,
  onSwitchPlatform,
  authSource,
}) => {
  const [isDark, setIsDark] = useState<boolean>(() => {
    return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
  });

  const isExtensionAuth = platform === 'fuexam' && authSource === 'extension';

  const handleLogout = async () => {
    const platformName = platform === 'fuexam' ? 'fuexam.me' : 'FUOverflow';
    const ok = await confirmModal({
      title: isExtensionAuth ? 'Ngắt kết nối DocxStacked' : 'Đăng xuất tài khoản',
      message: isExtensionAuth
        ? 'Bạn có chắc muốn ngắt kết nối phiên fuexam.me trên DocxStacked? Thao tác này chỉ xoá phiên lưu cục bộ trên DocxStacked, không làm đăng xuất tài khoản trên trình duyệt của bạn.'
        : `Bạn có chắc chắn muốn đăng xuất phiên tài khoản ${platformName}?`,
      confirmText: isExtensionAuth ? 'Ngắt kết nối' : 'Đăng xuất',
      isDanger: true,
    });
    if (!ok) return;
    if (onLogout) {
      onLogout();
      return;
    }
    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 2000);
      const logoutEndpoint = platform === 'fuexam' ? '/api/auth/fuexam/logout' : '/api/auth/logout';
      await fetch(logoutEndpoint, { method: 'POST', signal: controller.signal }).catch(() => {});
      clearTimeout(timeoutId);
    } catch (e) {
      console.error('Logout error:', e);
    } finally {
      window.location.reload();
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
        zIndex: 1001,
      }}
    >
      <div className="header-inner">
        {/* Brand, Subtitle & Platform Badge */}
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

          {platform && (
            <div style={{ display: 'inline-flex', alignItems: 'center', gap: '6px' }}>
              <span
                data-testid="platform-indicator"
                style={{
                  fontFamily: 'var(--font-sans)',
                  fontSize: '11px',
                  padding: '2px 8px',
                  backgroundColor: platform === 'fuexam' ? 'rgba(217, 119, 6, 0.1)' : 'rgba(2, 132, 199, 0.1)',
                  border: `1px solid ${platform === 'fuexam' ? 'rgba(217, 119, 6, 0.3)' : 'rgba(2, 132, 199, 0.3)'}`,
                  borderRadius: 'var(--radius-sm)',
                  color: platform === 'fuexam' ? '#b45309' : 'var(--primary)',
                  fontWeight: 600,
                }}
              >
                [{platform === 'fuexam' ? 'fuexam' : 'FUOverflow'}]
              </span>
              {onSwitchPlatform && (
                <button
                  type="button"
                  onClick={onSwitchPlatform}
                  data-testid="btn-switch-platform"
                  style={{
                    background: 'none',
                    border: '1px solid var(--border-subtle)',
                    borderRadius: 'var(--radius-sm)',
                    padding: '2px 8px',
                    fontSize: '11px',
                    fontWeight: 500,
                    color: 'var(--text-secondary)',
                    cursor: 'pointer',
                  }}
                  title="Nhấn để đổi giữa FUOverflow và fuexam.me"
                >
                  Đổi nền tảng
                </button>
              )}
            </div>
          )}
        </div>

        {/* Navigation & Controls - strictly rendered ONLY in logged_in state */}
        {isLoggedIn && !isBlocked && (
          <nav className="header-nav" aria-label="Điều hướng chính">
            {activeJobId && currentScreen !== 'progress' && onNavigateProgress && (
              <button
                type="button"
                onClick={onNavigateProgress}
                aria-label="Quay lại tiến trình đang chạy"
                style={{
                  background: 'var(--primary-subtle)',
                  border: '1px solid var(--primary-border)',
                  borderRadius: 'var(--radius-sm)',
                  padding: '6px 12px',
                  fontSize: 'var(--text-xs)',
                  fontWeight: 600,
                  color: 'var(--primary)',
                  cursor: 'pointer',
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '6px',
                  minHeight: '34px',
                  boxShadow: 'var(--shadow-sm)',
                  animation: 'pulseGlow 2s infinite ease-in-out',
                }}
                title="Nhấn để quay lại màn hình theo dõi tiến trình cào đề đang thực hiện"
              >
                <ActivityIcon size={14} className="spin-slow" />
                <span>Đang cào (Xem tiến trình)</span>
              </button>
            )}

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
                <BookIcon size={15} />
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
                <SettingsIcon size={15} />
                <span>Cài đặt</span>
              </button>
            )}

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
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '4px',
                }}
              >
                <UserIcon size={13} /> {username || 'Thành viên'}
              </span>
              <button
                type="button"
                onClick={handleLogout}
                aria-label={
                  isExtensionAuth
                    ? 'Ngắt kết nối phiên fuexam.me trên DocxStacked'
                    : platform === 'fuexam'
                    ? 'Đăng xuất khỏi tài khoản fuexam.me'
                    : 'Đăng xuất khỏi tài khoản FUOverflow'
                }
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
                title={
                  isExtensionAuth
                    ? 'Ngắt kết nối phiên trên DocxStacked (không làm đăng xuất trên trình duyệt thật)'
                    : platform === 'fuexam'
                    ? 'Đăng xuất khỏi tài khoản fuexam.me'
                    : 'Đăng xuất khỏi tài khoản FUOverflow'
                }
              >
                <LogoutIcon size={14} />
                <span>{isExtensionAuth ? 'Ngắt kết nối' : 'Đăng xuất'}</span>
              </button>
            </div>

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
              {isDark ? <SunIcon size={15} /> : <MoonIcon size={15} />}
              <span className="desktop-only">{isDark ? 'Sáng' : 'Tối'}</span>
            </button>
          </nav>
        )}
      </div>
    </header>
  );
};
