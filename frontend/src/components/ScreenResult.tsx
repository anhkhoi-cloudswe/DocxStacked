import React from 'react';
import type { JobDetails, JobFile } from '../types';

interface Props {
  files: JobFile[];
  details: JobDetails;
  onRestart: () => void;
}

export const ScreenResult: React.FC<Props> = ({ files, details, onRestart }) => {
  const handleDownload = (path: string) => {
    window.location.href = `/api/exports/download?path=${encodeURIComponent(path)}`;
  };

  const formatFileSize = (bytes: number): string => {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`;
  };

  return (
    <div style={{ maxWidth: '880px', margin: '0 auto' }}>
      <div className="card-paper">
        {/* Header */}
        <div
          style={{
            display: 'flex',
            alignItems: 'flex-start',
            justifyContent: 'space-between',
            marginBottom: 'var(--space-6)',
            borderBottom: '1px solid var(--border-subtle)',
            paddingBottom: 'var(--space-4)',
          }}
        >
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', marginBottom: 'var(--space-1)' }}>
              <span
                style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: 'var(--text-xs)',
                  padding: '2px 8px',
                  backgroundColor: 'var(--status-confident-bg)',
                  border: '1px solid var(--status-confident-border)',
                  color: 'var(--status-confident-text)',
                  borderRadius: 'var(--radius-sm)',
                  fontWeight: 600,
                }}
              >
                Hoàn tất biên soạn
              </span>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 'var(--text-sm)', color: 'var(--text-secondary)' }}>
                {details.subject_code} · {details.exam_type}
              </span>
            </div>
            <h2 className="serif-title" style={{ fontSize: 'var(--text-2xl)' }}>
              Tài liệu ôn tập đã sẵn sàng
            </h2>
          </div>

          <button
            onClick={onRestart}
            className="btn-secondary"
            style={{ fontSize: 'var(--text-sm)' }}
          >
            Biên soạn môn khác
          </button>
        </div>

        {/* Status Callout Card */}
        <div
          style={{
            padding: 'var(--space-4)',
            backgroundColor: 'var(--bg-subtle)',
            border: '1px solid var(--border-subtle)',
            borderRadius: 'var(--radius-sm)',
            marginBottom: 'var(--space-6)',
            fontSize: 'var(--text-sm)',
            lineHeight: 'var(--leading-relaxed)',
          }}
        >
          <div style={{ fontWeight: 600, color: 'var(--text-primary)', marginBottom: 'var(--space-1)' }}>
            Đặc điểm tài liệu biên soạn:
          </div>
          <ul style={{ paddingLeft: 'var(--space-4)', color: 'var(--text-secondary)' }}>
            <li>Tất cả hình ảnh câu hỏi được tải độ phân giải gốc full-res từ CDN/Media của FUOverflow.</li>
            <li>Đã căn chỉnh chiều rộng 16.0 cm chuẩn trang in A4 trong Word.</li>
            <li>Đã phân tích bình luận, tổng hợp ý kiến và xác định đáp án có độ tin cậy kèm chú thích chi tiết.</li>
          </ul>
        </div>

        {/* Files List Table */}
        <div style={{ marginBottom: 'var(--space-6)' }}>
          <h3
            className="serif-title"
            style={{ fontSize: 'var(--text-lg)', marginBottom: 'var(--space-3)' }}
          >
            Danh sách file Word đã tạo ({files.length} file)
          </h3>

          <div
            style={{
              border: '1px solid var(--border-subtle)',
              borderRadius: 'var(--radius-sm)',
              overflow: 'hidden',
            }}
          >
            {files.length === 0 ? (
              <div style={{ padding: 'var(--space-6)', textAlign: 'center', color: 'var(--text-muted)' }}>
                Không có file nào được tạo.
              </div>
            ) : (
              files.map((file, idx) => (
                <div
                  key={idx}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    padding: 'var(--space-4)',
                    borderBottom: idx < files.length - 1 ? '1px solid var(--border-subtle)' : 'none',
                    backgroundColor: 'var(--bg-surface)',
                  }}
                >
                  <div style={{ maxWidth: '65%' }}>
                    <div
                      style={{
                        fontFamily: 'var(--font-mono)',
                        fontSize: 'var(--text-sm)',
                        fontWeight: 600,
                        color: 'var(--text-primary)',
                        marginBottom: 'var(--space-1)',
                        wordBreak: 'break-all',
                      }}
                    >
                      {file.filename}
                    </div>
                    <div style={{ fontSize: 'var(--text-xs)', color: 'var(--text-secondary)' }}>
                      {file.exam_title} ·{' '}
                      <span style={{ fontFamily: 'var(--font-mono)' }}>{file.questions_count} câu</span> ·{' '}
                      <span style={{ fontFamily: 'var(--font-mono)' }}>{formatFileSize(file.size_bytes)}</span>
                    </div>
                  </div>

                  <button
                    onClick={() => handleDownload(file.path)}
                    className="btn-primary"
                    style={{
                      fontSize: 'var(--text-sm)',
                      padding: 'var(--space-2) var(--space-4)',
                      flexShrink: 0,
                    }}
                  >
                    Tải file .docx
                  </button>
                </div>
              ))
            )}
          </div>
        </div>

        {/* Footer info */}
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            fontSize: 'var(--text-xs)',
            color: 'var(--text-muted)',
            fontFamily: 'var(--font-mono)',
          }}
        >
          <span>Lưu trữ nội bộ: data/output/</span>
          <span>Định dạng: Microsoft Word (.docx)</span>
        </div>
      </div>
    </div>
  );
};
