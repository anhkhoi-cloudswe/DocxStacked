import React, { useEffect, useState, useMemo } from 'react';
import {
  ArrowLeftIcon,
  BookIcon,
  CheckIcon,
  CrossIcon,
  DownloadIcon,
  FolderIcon,
  RefreshIcon,
  TagIcon,
  TrashIcon,
  WarningIcon,
  ZapIcon,
} from './icons';

interface DocumentItem {
  filename: string;
  subject_code: string;
  exam_title: string;
  questions_count: number;
  size_bytes: number;
  size_formatted: string;
  download_url: string;
  created_at?: string;
  is_cached: boolean;
}

interface UserProfile {
  logged_in: boolean;
  username?: string;
  display_name?: string;
  last_login_at?: string;
  total_documents: number;
  total_subjects: number;
}

interface Props {
  onBack: () => void;
}

export const ScreenUserDocuments: React.FC<Props> = ({ onBack }) => {
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [documents, setDocuments] = useState<DocumentItem[]>([]);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [searchFilter, setSearchFilter] = useState<string>('');
  const [selectedSubject, setSelectedSubject] = useState<string>('ALL');
  const [toast, setToast] = useState<{ message: string; type: 'success' | 'error' } | null>(null);

  const showToast = (message: string, type: 'success' | 'error' = 'success') => {
    setToast({ message, type });
    setTimeout(() => setToast(null), 4000);
  };

  const loadData = () => {
    setIsLoading(true);
    Promise.all([
      fetch('/api/user/me').then((r) => (r.ok ? r.json() : null)),
      fetch('/api/user/documents').then((r) => (r.ok ? r.json() : [])),
    ])
      .then(([profData, docData]) => {
        if (profData) setProfile(profData);
        if (Array.isArray(docData)) setDocuments(docData);
      })
      .catch((err) => {
        console.error('Error fetching user documents:', err);
        showToast('Không thể tải danh sách tài liệu từ máy chủ.', 'error');
      })
      .finally(() => {
        setIsLoading(false);
      });
  };

  useEffect(() => {
    loadData();
  }, []);

  // Compute unique subjects and their stats
  const subjectsWithCounts = useMemo(() => {
    const map = new Map<string, { count: number; totalQuestions: number }>();
    for (const d of documents) {
      const existing = map.get(d.subject_code) || { count: 0, totalQuestions: 0 };
      map.set(d.subject_code, {
        count: existing.count + 1,
        totalQuestions: existing.totalQuestions + (d.questions_count || 0),
      });
    }
    return Array.from(map.entries()).map(([code, stats]) => ({
      code,
      count: stats.count,
      totalQuestions: stats.totalQuestions,
    }));
  }, [documents]);

  const handleDelete = async (doc: DocumentItem) => {
    const ok = window.confirm(`Bạn có chắc chắn muốn xóa file "${doc.filename}" không?`);
    if (!ok) return;
    try {
      const res = await fetch(`/api/user/documents?file=${encodeURIComponent(`data/output/${doc.subject_code}/${doc.filename}`)}`, {
        method: 'DELETE',
      });
      if (res.ok) {
        setDocuments((prev) => prev.filter((d) => !(d.subject_code === doc.subject_code && d.filename === doc.filename)));
        showToast(`Đã xóa thành công file "${doc.filename}".`, 'success');
      } else {
        const err = await res.json().catch(() => ({}));
        showToast(err.detail || 'Không thể xóa file.', 'error');
      }
    } catch (e: any) {
      showToast('Lỗi kết nối khi xóa file: ' + e.message, 'error');
    }
  };

  const handleDownloadFolder = async (subjectCode?: string) => {
    const subj = subjectCode || (selectedSubject !== 'ALL' ? selectedSubject : '');
    const targetDocs = filteredDocs.filter((d) => !subj || d.subject_code === subj);
    if (targetDocs.length === 0) return;

    showToast(`Đang tải ${targetDocs.length} file về thư mục Downloads...`, 'success');

    try {
      for (let i = 0; i < targetDocs.length; i++) {
        const doc = targetDocs[i];
        const a = document.createElement('a');
        a.href = doc.download_url;
        a.download = doc.filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);

        if (i < targetDocs.length - 1) {
          await new Promise((resolve) => setTimeout(resolve, 400));
        }
      }
      showToast(`Đã tải thành công ${targetDocs.length} file Word về thư mục Downloads!`, 'success');
    } catch (err) {
      console.error('Error downloading files:', err);
      const url = subj
        ? `/api/exports/download-folder?subject=${encodeURIComponent(subj)}`
        : `/api/exports/download-folder`;
      window.location.href = url;
    }
  };

  const handleOpenLocalFolder = async () => {
    try {
      const resp = await fetch('/api/exports/open-folder', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ subject: selectedSubject !== 'ALL' ? selectedSubject : undefined }),
      });
      const data = await resp.json();
      if (data.success) {
        showToast('Đã mở thư mục lưu trữ trên máy tính.', 'success');
      }
    } catch (e) {
      console.error('Failed to open local folder:', e);
    }
  };

  const filteredDocs = documents.filter((d) => {
    if (selectedSubject !== 'ALL' && d.subject_code !== selectedSubject) {
      return false;
    }
    if (!searchFilter.trim()) return true;
    const q = searchFilter.toLowerCase();
    return (
      d.subject_code.toLowerCase().includes(q) ||
      d.exam_title.toLowerCase().includes(q) ||
      d.filename.toLowerCase().includes(q)
    );
  });

  return (
    <div style={{ maxWidth: '1080px', margin: '0 auto', padding: 'var(--space-4) var(--space-3)' }}>
      {/* Toast Notification */}
      {toast && (
        <div
          role="status"
          style={{
            marginBottom: 'var(--space-4)',
            padding: 'var(--space-3) var(--space-4)',
            borderRadius: 'var(--radius-sm)',
            fontSize: 'var(--text-sm)',
            fontWeight: 500,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            backgroundColor: toast.type === 'success' ? 'var(--status-confident-bg)' : 'var(--status-conflict-bg)',
            border: `1px solid ${toast.type === 'success' ? 'var(--status-confident-border)' : 'var(--status-conflict-border)'}`,
            color: toast.type === 'success' ? 'var(--status-confident-text)' : 'var(--status-conflict-text)',
            boxShadow: 'var(--shadow-sm)',
          }}
        >
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: '8px' }}>
            {toast.type === 'success' ? <CheckIcon size={16} /> : <WarningIcon size={16} />}
            <span>{toast.message}</span>
          </span>
          <button
            type="button"
            onClick={() => setToast(null)}
            aria-label="Đóng thông báo"
            style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'inherit', fontWeight: 700, display: 'inline-flex', alignItems: 'center' }}
          >
            <CrossIcon size={14} />
          </button>
        </div>
      )}

      {/* Top Header Card */}
      <div
        className="card-paper"
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: 'var(--space-4)',
          flexWrap: 'wrap',
          gap: 'var(--space-3)',
        }}
      >
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', marginBottom: '4px', flexWrap: 'wrap' }}>
            <h1 className="serif-title" style={{ fontSize: 'var(--text-2xl)', margin: 0 }}>
              Kho tài liệu đã cào của tôi
            </h1>
            <span
              style={{
                fontSize: '11px',
                padding: '2px 8px',
                backgroundColor: 'var(--status-confident-bg)',
                color: 'var(--status-confident-text)',
                borderRadius: 'var(--radius-sm)',
                fontWeight: 600,
                border: '1px solid var(--status-confident-border)',
                display: 'inline-flex',
                alignItems: 'center',
                gap: '4px',
              }}
            >
              <ZapIcon size={12} />
              <span>Trích xuất tức thì (Không cần cào lại)</span>
            </span>
          </div>
          <p style={{ margin: 0, fontSize: 'var(--text-xs)', color: 'var(--text-secondary)' }}>
            Tài khoản FUOverflow: <strong>{profile?.username || 'Thành viên FUOverflow'}</strong> · Quản lý và tải nhanh các đề ôn thi đã biên soạn.
          </p>
        </div>

        <div style={{ display: 'flex', gap: 'var(--space-3)', alignItems: 'center', flexWrap: 'wrap' }}>
          <div
            style={{
              padding: 'var(--space-2) var(--space-4)',
              backgroundColor: 'var(--bg-subtle)',
              border: '1px solid var(--border-subtle)',
              borderRadius: 'var(--radius-sm)',
              textAlign: 'center',
            }}
          >
            <div style={{ fontSize: '18px', fontWeight: 700, color: 'var(--primary)', fontFamily: 'var(--font-mono)' }}>
              {documents.length}
            </div>
            <div style={{ fontSize: '11px', color: 'var(--text-secondary)' }}>File Word đã tạo</div>
          </div>

          {documents.length > 0 && (
            <div style={{ display: 'inline-flex', alignItems: 'center', gap: '8px' }}>
              <button
                type="button"
                onClick={() => handleDownloadFolder()}
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '6px',
                  fontSize: 'var(--text-sm)',
                  padding: 'var(--space-2) var(--space-4)',
                  minHeight: '38px',
                  fontWeight: 600,
                  backgroundColor: '#D97706',
                  color: '#ffffff',
                  border: '1px solid #B45309',
                  borderRadius: 'var(--radius-sm)',
                  cursor: 'pointer',
                  boxShadow: 'var(--shadow-sm)',
                }}
                title={
                  selectedSubject !== 'ALL'
                    ? `Tải toàn bộ file Word môn ${selectedSubject} gom thành folder`
                    : 'Tải toàn bộ file Word trong kho gom theo từng môn và thể loại thi'
                }
              >
                <FolderIcon size={14} />
                <span>Tải Folder {selectedSubject !== 'ALL' ? `(${selectedSubject})` : ''}</span>
              </button>

              <button
                type="button"
                onClick={handleOpenLocalFolder}
                className="btn-secondary"
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '5px',
                  fontSize: 'var(--text-sm)',
                  padding: 'var(--space-2) var(--space-3)',
                  minHeight: '38px',
                  cursor: 'pointer',
                }}
                title="Mở thư mục lưu trữ file trên máy tính (Windows Explorer)"
              >
                <span>Mở trên máy</span>
              </button>
            </div>
          )}

          <button
            onClick={onBack}
            className="btn-secondary"
            style={{ fontSize: 'var(--text-sm)', padding: 'var(--space-2) var(--space-4)', minHeight: '38px', display: 'inline-flex', alignItems: 'center', gap: '6px' }}
          >
            <ArrowLeftIcon size={14} />
            <span>Về trang chọn môn</span>
          </button>
        </div>
      </div>

      {/* Subject Filter Boxes */}
      {subjectsWithCounts.length > 0 && (
        <div
          className="card-paper"
          style={{
            marginBottom: 'var(--space-4)',
            padding: 'var(--space-3) var(--space-4)',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 'var(--space-2)', flexWrap: 'wrap', gap: '6px' }}>
            <span style={{ fontSize: 'var(--text-xs)', fontWeight: 600, color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: '6px' }}>
              <TagIcon size={14} />
              <span>Lọc theo môn học:</span>
            </span>
            {selectedSubject !== 'ALL' && (
              <button
                type="button"
                onClick={() => setSelectedSubject('ALL')}
                style={{
                  background: 'none',
                  border: 'none',
                  fontSize: '11px',
                  color: 'var(--primary)',
                  cursor: 'pointer',
                  textDecoration: 'underline',
                  fontWeight: 600,
                }}
              >
                Hiển thị tất cả môn ({documents.length} đề)
              </button>
            )}
          </div>

          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))',
              gap: 'var(--space-2)',
            }}
          >
            {/* All Subjects Card */}
            <button
              type="button"
              onClick={() => setSelectedSubject('ALL')}
              style={{
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'flex-start',
                padding: 'var(--space-2) var(--space-3)',
                borderRadius: 'var(--radius-sm)',
                backgroundColor: selectedSubject === 'ALL' ? 'var(--primary-subtle)' : 'var(--bg-canvas)',
                border: `2px solid ${selectedSubject === 'ALL' ? 'var(--primary)' : 'var(--border-subtle)'}`,
                cursor: 'pointer',
                textAlign: 'left',
                transition: 'all var(--transition-fast)',
              }}
            >
              <div style={{ fontWeight: 700, fontSize: 'var(--text-sm)', color: selectedSubject === 'ALL' ? 'var(--primary)' : 'var(--text-primary)' }}>
                Tất cả môn
              </div>
              <div style={{ fontSize: '11px', color: 'var(--text-secondary)', marginTop: '2px' }}>
                {documents.length} đề thi
              </div>
            </button>

            {/* Individual Subject Cards */}
            {subjectsWithCounts.map((sub) => {
              const isSelected = selectedSubject === sub.code;
              return (
                <button
                  key={sub.code}
                  type="button"
                  onClick={() => setSelectedSubject(isSelected ? 'ALL' : sub.code)}
                  style={{
                    display: 'flex',
                    flexDirection: 'column',
                    alignItems: 'flex-start',
                    padding: 'var(--space-2) var(--space-3)',
                    borderRadius: 'var(--radius-sm)',
                    backgroundColor: isSelected ? 'var(--primary-subtle)' : 'var(--bg-canvas)',
                    border: `2px solid ${isSelected ? 'var(--primary)' : 'var(--border-subtle)'}`,
                    cursor: 'pointer',
                    textAlign: 'left',
                    transition: 'all var(--transition-fast)',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', width: '100%' }}>
                    <span
                      style={{
                        fontFamily: 'var(--font-mono)',
                        fontWeight: 700,
                        fontSize: 'var(--text-sm)',
                        color: isSelected ? 'var(--primary)' : 'var(--text-primary)',
                      }}
                    >
                      {sub.code}
                    </span>
                    <span
                      style={{
                        fontSize: '11px',
                        padding: '1px 6px',
                        borderRadius: 'var(--radius-sm)',
                        backgroundColor: isSelected ? 'var(--primary)' : 'var(--bg-subtle)',
                        color: isSelected ? '#FFFFFF' : 'var(--text-secondary)',
                        fontWeight: 600,
                      }}
                    >
                      {sub.count} đề
                    </span>
                  </div>
                  <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '2px' }}>
                    {sub.totalQuestions} câu hỏi
                  </div>
                </button>
              );
            })}
          </div>
        </div>
      )}

      {/* Filter and Search Bar */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: 'var(--space-4)',
          gap: 'var(--space-3)',
          flexWrap: 'wrap',
        }}
      >
        <div style={{ position: 'relative', flex: 1, minWidth: '240px', maxWidth: '440px' }}>
          <input
            type="text"
            placeholder={
              selectedSubject !== 'ALL'
                ? `Tìm đề thi trong môn ${selectedSubject}...`
                : 'Tìm theo mã môn (PRM392, CSD202...) hoặc tên đề...'
            }
            value={searchFilter}
            onChange={(e) => setSearchFilter(e.target.value)}
            style={{
              width: '100%',
              padding: 'var(--space-2) var(--space-3)',
              backgroundColor: 'var(--bg-canvas)',
              border: '1px solid var(--border-strong)',
              borderRadius: 'var(--radius-sm)',
              fontSize: 'var(--text-sm)',
              color: 'var(--text-primary)',
            }}
          />
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)', flexWrap: 'wrap' }}>
          <div style={{ fontSize: 'var(--text-xs)', color: 'var(--text-secondary)' }}>
            {selectedSubject !== 'ALL' && (
              <span style={{ marginRight: '8px', color: 'var(--primary)', fontWeight: 600 }}>
                [Đang lọc: {selectedSubject}]
              </span>
            )}
            Hiển thị <strong>{filteredDocs.length}</strong> / {documents.length} tài liệu
          </div>

          {filteredDocs.length > 0 && (
            <button
              type="button"
              onClick={() => handleDownloadFolder()}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '6px',
                fontSize: 'var(--text-xs)',
                padding: '6px 14px',
                fontWeight: 600,
                backgroundColor: '#D97706',
                color: '#ffffff',
                border: '1px solid #B45309',
                borderRadius: 'var(--radius-sm)',
                cursor: 'pointer',
                boxShadow: 'var(--shadow-sm)',
              }}
              title="Tải toàn bộ file Word trong danh sách này dưới dạng Folder zip"
            >
              <FolderIcon size={14} />
              <span>Tải Folder</span>
            </button>
          )}
        </div>
      </div>

      {/* Content Area */}
      {isLoading ? (
        <div style={{ textAlign: 'center', padding: 'var(--space-8)', color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '8px' }}>
          <RefreshIcon size={16} className="spin" />
          <span>Đang tải danh sách tài liệu...</span>
        </div>
      ) : filteredDocs.length === 0 ? (
        <div
          className="card-paper"
          style={{
            padding: 'var(--space-8) var(--space-4)',
            textAlign: 'center',
            color: 'var(--text-secondary)',
          }}
        >
          <div style={{ marginBottom: 'var(--space-3)', display: 'flex', justifyContent: 'center' }}>
            <BookIcon size={36} />
          </div>
          <h3 className="serif-title" style={{ fontSize: 'var(--text-lg)', marginBottom: 'var(--space-2)' }}>
            Chưa có tài liệu nào trong kho
          </h3>
          <p style={{ fontSize: 'var(--text-sm)', maxWidth: '420px', margin: '0 auto var(--space-5)' }}>
            {selectedSubject !== 'ALL'
              ? `Không tìm thấy file nào cho môn ${selectedSubject} với bộ lọc hiện tại.`
              : `Bạn chưa biên soạn đề thi nào hoặc không tìm thấy kết quả phù hợp với từ khóa "${searchFilter}".`}
          </p>
          {selectedSubject !== 'ALL' ? (
            <button
              type="button"
              onClick={() => setSelectedSubject('ALL')}
              className="btn-secondary"
              style={{ fontSize: 'var(--text-sm)' }}
            >
              Xem tất cả các môn
            </button>
          ) : (
            <button
              type="button"
              onClick={onBack}
              className="btn-primary"
              style={{ fontSize: 'var(--text-sm)' }}
            >
              Chọn môn và biên soạn đề mới
            </button>
          )}
        </div>
      ) : (
        <div
          style={{
            backgroundColor: 'var(--bg-surface)',
            border: '1px solid var(--border-subtle)',
            borderRadius: 'var(--radius-md)',
            overflowX: 'auto',
            boxShadow: 'var(--shadow-sm)',
          }}
        >
          <table style={{ width: '100%', minWidth: '650px', borderCollapse: 'collapse', textAlign: 'left', fontSize: 'var(--text-sm)' }}>
            <thead>
              <tr style={{ backgroundColor: 'var(--bg-subtle)', borderBottom: '1px solid var(--border-subtle)' }}>
                <th style={{ padding: 'var(--space-3) var(--space-4)', fontWeight: 600 }}>Môn</th>
                <th style={{ padding: 'var(--space-3) var(--space-4)', fontWeight: 600 }}>Tên đề thi</th>
                <th style={{ padding: 'var(--space-3) var(--space-4)', fontWeight: 600 }}>Số câu</th>
                <th style={{ padding: 'var(--space-3) var(--space-4)', fontWeight: 600 }}>Dung lượng</th>
                <th style={{ padding: 'var(--space-3) var(--space-4)', fontWeight: 600 }}>Thời gian</th>
                <th style={{ padding: 'var(--space-3) var(--space-4)', fontWeight: 600, textAlign: 'right' }}>Thao tác</th>
              </tr>
            </thead>
            <tbody>
              {filteredDocs.map((doc, idx) => (
                <tr
                  key={idx}
                  style={{
                    borderBottom: idx < filteredDocs.length - 1 ? '1px solid var(--border-subtle)' : 'none',
                    backgroundColor: idx % 2 === 0 ? 'var(--bg-surface)' : 'var(--bg-canvas)',
                  }}
                >
                  <td style={{ padding: 'var(--space-3) var(--space-4)' }}>
                    <span
                      className="mono-badge"
                      style={{ cursor: 'pointer' }}
                      onClick={() => setSelectedSubject(doc.subject_code)}
                      title={`Lọc chỉ xem môn ${doc.subject_code}`}
                    >
                      {doc.subject_code}
                    </span>
                  </td>
                  <td style={{ padding: 'var(--space-3) var(--space-4)' }}>
                    <div style={{ fontWeight: 600, color: 'var(--text-primary)' }}>{doc.exam_title}</div>
                    <div style={{ fontSize: '11px', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
                      {doc.filename}
                    </div>
                  </td>
                  <td style={{ padding: 'var(--space-3) var(--space-4)' }}>
                    <span style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-primary)' }}>
                      {doc.questions_count} câu
                    </span>
                  </td>
                  <td style={{ padding: 'var(--space-3) var(--space-4)' }}>
                    <span style={{ fontSize: '12px', fontFamily: 'var(--font-mono)', color: 'var(--text-secondary)' }}>
                      {doc.size_formatted}
                    </span>
                  </td>
                  <td style={{ padding: 'var(--space-3) var(--space-4)', fontSize: '12px', color: 'var(--text-muted)' }}>
                    {doc.created_at || 'Đã lưu trữ'}
                  </td>
                  <td style={{ padding: 'var(--space-3) var(--space-4)', textAlign: 'right' }}>
                    <div style={{ display: 'inline-flex', gap: '8px', alignItems: 'center' }}>
                      <a
                        href={doc.download_url}
                        style={{
                          display: 'inline-flex',
                          alignItems: 'center',
                          gap: '4px',
                          padding: '6px 12px',
                          fontSize: '12px',
                          fontWeight: 600,
                          backgroundColor: 'var(--primary)',
                          color: '#ffffff',
                          borderRadius: 'var(--radius-sm)',
                          textDecoration: 'none',
                        }}
                      >
                        <DownloadIcon size={13} />
                        <span>Tải file Word</span>
                      </a>
                      <button
                        type="button"
                        onClick={() => handleDelete(doc)}
                        style={{
                          display: 'inline-flex',
                          alignItems: 'center',
                          gap: '4px',
                          padding: '6px 10px',
                          fontSize: '12px',
                          fontWeight: 600,
                          backgroundColor: 'var(--bg-subtle)',
                          color: '#E53E3E',
                          border: '1px solid var(--border-subtle)',
                          borderRadius: 'var(--radius-sm)',
                          cursor: 'pointer',
                        }}
                        title="Xóa tài liệu này khỏi bộ nhớ"
                      >
                        <TrashIcon size={13} />
                        <span>Xóa</span>
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
};
