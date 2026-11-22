import React from 'react';
import type { PlatformType } from '../types';

interface ScreenSelectPlatformProps {
  onSelectPlatform: (platform: PlatformType) => void;
}

export const ScreenSelectPlatform: React.FC<ScreenSelectPlatformProps> = ({ onSelectPlatform }) => {
  return (
    <div style={{ maxWidth: '860px', margin: '40px auto', padding: '0 16px' }}>
      <div style={{ textAlign: 'center', marginBottom: '32px' }}>
        <h1
          style={{
            fontSize: '28px',
            fontWeight: 700,
            color: 'var(--text-primary, #0f172a)',
            letterSpacing: '-0.02em',
            margin: '0 0 8px 0',
            fontFamily: 'var(--font-serif, serif)',
          }}
        >
          Chọn nền tảng đề thi
        </h1>
        <p
          style={{
            fontSize: '14px',
            color: 'var(--text-secondary, #475569)',
            margin: 0,
            lineHeight: 1.5,
          }}
        >
          DocxStacked hỗ trợ hai nguồn tài liệu độc lập. Vui lòng chọn nền tảng bạn muốn làm việc.
        </p>
      </div>

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))',
          gap: '20px',
        }}
      >
        {/* Card: FUOverflow */}
        <div
          role="button"
          tabIndex={0}
          onClick={() => onSelectPlatform('fuoverflow')}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault();
              onSelectPlatform('fuoverflow');
            }
          }}
          data-testid="platform-card-fuoverflow"
          style={{
            backgroundColor: 'var(--bg-surface, #ffffff)',
            border: '1px solid var(--border-subtle, #e2e8f0)',
            borderRadius: '6px',
            padding: '24px',
            cursor: 'pointer',
            display: 'flex',
            flexDirection: 'column',
            justifyContent: 'space-between',
            transition: 'border-color 0.15s ease, box-shadow 0.15s ease',
            outline: 'none',
          }}
        >
          <div>
            <div
              style={{
                display: 'inline-block',
                fontSize: '11px',
                fontWeight: 600,
                color: 'var(--primary, #0284c7)',
                backgroundColor: 'rgba(2, 132, 199, 0.08)',
                padding: '2px 8px',
                borderRadius: '4px',
                marginBottom: '12px',
                letterSpacing: '0.04em',
                textTransform: 'uppercase',
              }}
            >
              Diễn đàn sinh viên
            </div>
            <h2
              style={{
                fontSize: '20px',
                fontWeight: 700,
                color: 'var(--text-primary, #0f172a)',
                margin: '0 0 10px 0',
                fontFamily: 'var(--font-serif, serif)',
              }}
            >
              FUOverflow
            </h2>
            <p
              style={{
                fontSize: '13px',
                color: 'var(--text-secondary, #475569)',
                lineHeight: 1.6,
                margin: '0 0 16px 0',
              }}
            >
              Diễn đàn thảo luận và chia sẻ đề thi ôn tập FE / PE của sinh viên FPT. Xác thực phiên trực tiếp thông qua
              Extension DocxStacked trên trình duyệt.
            </p>
          </div>
          <div
            style={{
              paddingTop: '16px',
              borderTop: '1px solid var(--border-subtle, #f1f5f9)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
            }}
          >
            <span style={{ fontSize: '12px', color: 'var(--text-muted, #94a3b8)' }}>Xác thực qua Extension</span>
            <span
              style={{
                fontSize: '13px',
                fontWeight: 600,
                color: 'var(--primary, #0284c7)',
              }}
            >
              Vào nền tảng &rarr;
            </span>
          </div>
        </div>

        {/* Card: fuexam */}
        <div
          role="button"
          tabIndex={0}
          onClick={() => onSelectPlatform('fuexam')}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault();
              onSelectPlatform('fuexam');
            }
          }}
          data-testid="platform-card-fuexam"
          style={{
            backgroundColor: 'var(--bg-surface, #ffffff)',
            border: '1px solid var(--border-subtle, #e2e8f0)',
            borderRadius: '6px',
            padding: '24px',
            cursor: 'pointer',
            display: 'flex',
            flexDirection: 'column',
            justifyContent: 'space-between',
            transition: 'border-color 0.15s ease, box-shadow 0.15s ease',
            outline: 'none',
          }}
        >
          <div>
            <div
              style={{
                display: 'inline-block',
                fontSize: '11px',
                fontWeight: 600,
                color: '#b45309',
                backgroundColor: 'rgba(217, 119, 6, 0.08)',
                padding: '2px 8px',
                borderRadius: '4px',
                marginBottom: '12px',
                letterSpacing: '0.04em',
                textTransform: 'uppercase',
              }}
            >
              Ngân hàng đề trắc nghiệm
            </div>
            <h2
              style={{
                fontSize: '20px',
                fontWeight: 700,
                color: 'var(--text-primary, #0f172a)',
                margin: '0 0 10px 0',
                fontFamily: 'var(--font-serif, serif)',
              }}
            >
              fuexam.me
            </h2>
            <p
              style={{
                fontSize: '13px',
                color: 'var(--text-secondary, #475569)',
                lineHeight: 1.6,
                margin: '0 0 16px 0',
              }}
            >
              Kho lưu trữ 292 môn học với ảnh đề thi trắc nghiệm. Quản lý phiên độc lập qua trình duyệt Chromium hoặc
              dòng lệnh CLI an toàn.
            </p>
          </div>
          <div
            style={{
              paddingTop: '16px',
              borderTop: '1px solid var(--border-subtle, #f1f5f9)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
            }}
          >
            <span style={{ fontSize: '12px', color: 'var(--text-muted, #94a3b8)' }}>Xác thực độc lập</span>
            <span
              style={{
                fontSize: '13px',
                fontWeight: 600,
                color: '#b45309',
              }}
            >
              Vào nền tảng &rarr;
            </span>
          </div>
        </div>
      </div>
    </div>
  );
};

