import React from 'react';
import type { JobDetails, JobFile } from '../types';
import { FolderIcon } from './icons';

interface Props {
  jobId?: string;
  files: JobFile[];
  details: JobDetails;
  onRestart: () => void;
  onRetryFailed?: () => void;
}

export const ScreenResult: React.FC<Props> = ({ jobId, files, details, onRestart, onRetryFailed }) => {
  const [downloadingFolder, setDownloadingFolder] = React.useState(false);
  const [openFolderStatus, setOpenFolderStatus] = React.useState<string | null>(null);
  const examResults = details.exam_results || [];
  const failedExams = details.failed_exams || [];
  const hasAnyFailureOrWarning =
    failedExams.length > 0 ||
    examResults.some((e) => e.status === 'failed' || e.status === 'completed_with_warnings') ||
    files.some((f) => f.fetch_failed_questions && f.fetch_failed_questions.length > 0);

  const handleDownload = (path: string) => {
    window.location.href = `/api/exports/download?path=${encodeURIComponent(path)}`;
  };

  const handleDownloadFolder = async () => {
    if (files.length === 0) return;
    setDownloadingFolder(true);
    setOpenFolderStatus(`Đang tạo folder và lưu vào thư mục Downloads...`);

    try {
      // Direct Server-side folder creator: saves directly into user's Downloads/{SUBJECT}_{CAT} without zip
      const resp = await fetch('/api/exports/export-folder', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          job_id: jobId || undefined,
          subject: details.subject_code || undefined,
          exam_type: details.exam_type || undefined,
          paths: files.map((f) => f.path),
        }),
      });

      if (resp.ok) {
        const data = await resp.json();
        setOpenFolderStatus(data.message || `Đã lưu thành công vào folder Downloads/${data.folder_name}!`);
        setTimeout(() => setOpenFolderStatus(null), 6000);
        // Automatically open the created folder in Windows Explorer
        fetch('/api/exports/open-folder', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ path: data.folder_path }),
        }).catch(() => {});
        return;
      }

      throw new Error(`Server returned HTTP ${resp.status}`);
    } catch (err: any) {
      console.error('Error saving folder:', err);
      // Fallback: trigger zip download if server export failed
      const url = jobId
        ? `/api/jobs/${encodeURIComponent(jobId)}/download-folder`
        : `/api/exports/download-folder?subject=${encodeURIComponent(details.subject_code || '')}&type=${encodeURIComponent(details.exam_type || '')}`;
      window.location.href = url;
    } finally {
      setDownloadingFolder(false);
    }
  };

  const handleOpenLocalFolder = async () => {
    try {
      const resp = await fetch('/api/exports/open-folder', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ subject: details.subject_code }),
      });
      const data = await resp.json();
      if (data.success) {
        setOpenFolderStatus('Đã mở thư mục lưu trữ trên máy.');
        setTimeout(() => setOpenFolderStatus(null), 4000);
      }
    } catch (e) {
      console.error('Failed to open local folder:', e);
    }
  };

  const formatFileSize = (bytes: number): string => {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`;
  };

  const isFuexam =
    details.exam_type === 'FUE' ||
    files.some((f) => f.platform === 'fuexam' || f.filename.includes(' - FUE - ') || f.path.includes('/FUE/'));

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

          <div style={{ display: 'flex', gap: '8px', alignItems: 'center', flexWrap: 'wrap' }}>
            {hasAnyFailureOrWarning && onRetryFailed && jobId && (
              <button
                type="button"
                onClick={onRetryFailed}
                className="btn-primary"
                style={{ fontSize: 'var(--text-sm)', backgroundColor: '#D97706', borderColor: '#B45309' }}
              >
                Thử lại các đề lỗi
              </button>
            )}
            <button
              onClick={onRestart}
              className="btn-secondary"
              style={{ fontSize: 'var(--text-sm)' }}
            >
              Biên soạn môn khác
            </button>
          </div>
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
            Đặc điểm tài liệu biên soạn ({isFuexam ? 'nền tảng fuexam.me' : 'nền tảng FUOverflow'}):
          </div>
          <ul style={{ paddingLeft: 'var(--space-4)', color: 'var(--text-secondary)' }}>
            {isFuexam ? (
              <>
                <li>Ảnh đề tải trực tiếp từ fuexam.me. Đáp án đọc từ dải đáp án in trong ảnh nếu có; nếu không có thì tổng hợp từ bình luận cộng đồng.</li>
                <li>Đã căn chỉnh kích thước lề chuẩn khổ Letter (8.5 x 11 inch) trong Word.</li>
              </>
            ) : (
              <>
                <li>Tất cả hình ảnh câu hỏi được tải độ phân giải gốc full-res từ CDN/Media của FUOverflow.</li>
                <li>Đã căn chỉnh kích thước lề chuẩn khổ Letter (8.5 x 11 inch) trong Word.</li>
                <li>Đã phân tích bình luận, tổng hợp ý kiến và xác định đáp án có độ tin cậy kèm chú thích chi tiết.</li>
              </>
            )}
          </ul>
        </div>

        {/* Per-exam status summary (Xong / Xong có cảnh báo / Lỗi + lý do) */}
        {examResults.length > 0 && (
          <div
            data-testid="result-exam-status-list"
            style={{
              padding: 'var(--space-4)',
              backgroundColor: 'var(--bg-subtle)',
              border: '1px solid var(--border-subtle)',
              borderRadius: 'var(--radius-sm)',
              marginBottom: 'var(--space-6)',
              fontSize: 'var(--text-xs)',
            }}
          >
            <div style={{ fontWeight: 600, color: 'var(--text-primary)', marginBottom: '8px' }}>
              Tổng kết từng đề ({examResults.length} đề):
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
              {examResults.map((er) => (
                <div
                  key={er.thread_id}
                  style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    gap: '12px',
                    padding: '6px 8px',
                    backgroundColor: 'var(--bg-surface)',
                    border: '1px solid var(--border-subtle)',
                    borderRadius: 'var(--radius-sm)',
                  }}
                >
                  <span style={{ fontWeight: 500, color: 'var(--text-primary)' }}>{er.exam_title}</span>
                  <span
                    style={{
                      fontWeight: 600,
                      color:
                        er.status === 'completed'
                          ? 'var(--status-confident-text)'
                          : er.status === 'completed_with_warnings'
                          ? '#B45309'
                          : '#991B1B',
                    }}
                  >
                    {er.status === 'completed'
                      ? 'Xong'
                      : er.status === 'completed_with_warnings'
                      ? `Xong có cảnh báo (lỗi tải bình luận: Câu ${(er.fetch_failed_questions || []).join(', ')})`
                      : `Lỗi: ${er.reason || er.error_code || 'Không thành công'}`}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Files List Table */}
        <div style={{ marginBottom: 'var(--space-6)' }}>
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              marginBottom: 'var(--space-3)',
              paddingRight: 'calc(var(--space-4) + 1px)',
              flexWrap: 'wrap',
              gap: 'var(--space-2)',
            }}
          >
            <h3
              className="serif-title"
              style={{ fontSize: 'var(--text-lg)', margin: 0 }}
            >
              Danh sách file Word đã tạo ({files.length} file)
            </h3>

            {files.length > 0 && (
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <button
                  type="button"
                  onClick={handleDownloadFolder}
                  disabled={downloadingFolder}
                  style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: '6px',
                    fontSize: 'var(--text-xs)',
                    padding: 'var(--space-2) var(--space-4)',
                    fontWeight: 600,
                    cursor: downloadingFolder ? 'wait' : 'pointer',
                    backgroundColor: '#D97706',
                    color: '#ffffff',
                    border: '1px solid #B45309',
                    borderRadius: 'var(--radius-sm)',
                    boxShadow: 'var(--shadow-sm)',
                    opacity: downloadingFolder ? 0.7 : 1,
                  }}
                  title="Tải toàn bộ file Word được lưu thẳng vào 1 folder máy tính (không cần giải nén zip)"
                >
                  <FolderIcon size={14} />
                  <span>{downloadingFolder ? 'Đang lưu folder...' : 'Tải Folder'}</span>
                </button>

                <button
                  type="button"
                  onClick={handleOpenLocalFolder}
                  className="btn-secondary"
                  style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: '5px',
                    fontSize: 'var(--text-xs)',
                    padding: 'var(--space-2) var(--space-3)',
                    cursor: 'pointer',
                  }}
                  title="Mở trực tiếp thư mục lưu trữ file Word trên máy tính (Windows Explorer)"
                >
                  <span>Mở trên máy</span>
                </button>
              </div>
            )}
          </div>

          {openFolderStatus && (
            <div
              style={{
                marginBottom: 'var(--space-3)',
                padding: '6px 12px',
                backgroundColor: 'var(--status-confident-bg)',
                border: '1px solid var(--status-confident-border)',
                color: 'var(--status-confident-text)',
                borderRadius: 'var(--radius-sm)',
                fontSize: 'var(--text-xs)',
                fontWeight: 500,
              }}
            >
              {openFolderStatus}
            </div>
          )}

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

                    {/* Metadata & Confidence Stats & Answer Sources (.meta.json) */}
                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px', flexWrap: 'wrap', marginTop: '6px' }}>
                      {file.image_count !== undefined && file.image_count > 0 && (
                        <span
                          style={{
                            fontSize: '11px',
                            padding: '1px 6px',
                            borderRadius: '3px',
                            backgroundColor: '#ECFDF5',
                            color: '#065F46',
                            border: '1px solid #A7F3D0',
                            fontWeight: 600,
                          }}
                          title="Số câu lấy đáp án từ dải đáp án trong ảnh (.meta.json)"
                        >
                          Ảnh: {file.image_count} câu
                        </span>
                      )}
                      {file.comment_count !== undefined && file.comment_count > 0 && (
                        <span
                          style={{
                            fontSize: '11px',
                            padding: '1px 6px',
                            borderRadius: '3px',
                            backgroundColor: '#EFF6FF',
                            color: '#1E40AF',
                            border: '1px solid #BFDBFE',
                            fontWeight: 600,
                          }}
                          title="Số câu lấy đáp án tổng hợp từ bình luận (.meta.json)"
                        >
                          Bình luận: {file.comment_count} câu
                        </span>
                      )}
                      {file.ai_count !== undefined && file.ai_count > 0 && (
                        <span
                          style={{
                            fontSize: '11px',
                            padding: '1px 6px',
                            borderRadius: '3px',
                            backgroundColor: '#FEF3C7',
                            color: '#92400E',
                            border: '1px solid #FCD34D',
                            fontWeight: 600,
                          }}
                          title="Số câu đọc giải thích hoặc giải quyết xung đột bằng AI (.meta.json)"
                        >
                          AI: {file.ai_count} câu
                        </span>
                      )}
                      {file.confident_count !== undefined && file.confident_count > 0 && (
                        <span
                          style={{
                            fontSize: '11px',
                            padding: '1px 6px',
                            borderRadius: '3px',
                            backgroundColor: 'var(--status-confident-bg)',
                            color: 'var(--status-confident-text)',
                            border: '1px solid var(--status-confident-border)',
                            fontWeight: 600,
                          }}
                        >
                          CONFIDENT: {file.confident_count}
                        </span>
                      )}
                      {file.weak_count !== undefined && file.weak_count > 0 && (
                        <span
                          style={{
                            fontSize: '11px',
                            padding: '1px 6px',
                            borderRadius: '3px',
                            backgroundColor: '#FEF3C7',
                            color: '#92400E',
                            border: '1px solid #FCD34D',
                            fontWeight: 600,
                          }}
                        >
                          WEAK: {file.weak_count}
                        </span>
                      )}
                      {file.conflict_count !== undefined && file.conflict_count > 0 && (
                        <span
                          style={{
                            fontSize: '11px',
                            padding: '1px 6px',
                            borderRadius: '3px',
                            backgroundColor: '#FEE2E2',
                            color: '#991B1B',
                            border: '1px solid #FCA5A5',
                            fontWeight: 600,
                          }}
                        >
                          CONFLICT: {file.conflict_count}
                        </span>
                      )}
                      {file.no_data_count !== undefined && file.no_data_count > 0 && (
                        <span
                          style={{
                            fontSize: '11px',
                            padding: '1px 6px',
                            borderRadius: '3px',
                            backgroundColor: '#F3F4F6',
                            color: '#4B5563',
                            border: '1px solid #D1D5DB',
                            fontWeight: 600,
                          }}
                        >
                          CHƯA CÓ ĐÁP ÁN (?): {file.no_data_count}
                        </span>
                      )}
                      {file.ai_count !== undefined && file.ai_count > 0 && (
                        <span
                          style={{
                            fontSize: '11px',
                            padding: '1px 6px',
                            borderRadius: '3px',
                            backgroundColor: '#EFF6FF',
                            color: '#1D4ED8',
                            border: '1px solid #BFDBFE',
                            fontWeight: 600,
                          }}
                        >
                          AI: {file.ai_count}
                        </span>
                      )}
                    </div>

                    {file.review_needed_questions && file.review_needed_questions.length > 0 && (
                      <div style={{ fontSize: '11px', color: '#B45309', marginTop: '4px', fontWeight: 500 }}>
                        Cần xem lại: Câu {file.review_needed_questions.join(', ')}
                      </div>
                    )}
                    {file.image_warnings && Object.keys(file.image_warnings).length > 0 && (
                      <div data-testid="image-warnings-note" style={{ fontSize: '11px', color: '#92400E', marginTop: '3px' }}>
                        Cảnh báo ảnh ({Object.keys(file.image_warnings).length} câu):{' '}
                        {Object.entries(file.image_warnings)
                          .slice(0, 6)
                          .map(([qNum, ws]) => `Câu ${qNum} (${ws.join(', ')})`)
                          .join('; ')}
                        {Object.keys(file.image_warnings).length > 6 ? '…' : ''}
                      </div>
                    )}
                    {file.fetch_failed_questions && file.fetch_failed_questions.length > 0 && (
                      <div
                        data-testid="fetch-failed-warning"
                        style={{
                          fontSize: '11px',
                          color: '#991B1B',
                          backgroundColor: '#FEE2E2',
                          border: '1px solid #FCA5A5',
                          borderRadius: '3px',
                          padding: '3px 8px',
                          marginTop: '6px',
                          fontWeight: 600,
                        }}
                      >
                        Cảnh báo: Tải bình luận thất bại ở Câu {file.fetch_failed_questions.join(', ')} (không lưu cache rỗng)
                      </div>
                    )}
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
