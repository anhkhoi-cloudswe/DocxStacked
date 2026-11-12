import React, { useEffect, useState } from 'react';
import type { Subject, ExamItem, AuthStatus } from '../types';

interface Props {
  onStartJob: (subjectCode: string, examType: 'FE' | 'PE', limit: number) => void;
  isLoading: boolean;
  initialOpenLogin?: boolean;
}

export const ScreenSelectSubject: React.FC<Props> = ({ onStartJob, isLoading, initialOpenLogin }) => {
  // Subjects list & search
  const [subjects, setSubjects] = useState<Subject[]>([]);
  const [totalSubjects, setTotalSubjects] = useState<number>(0);
  const [lastSyncedAt, setLastSyncedAt] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [debouncedQuery, setDebouncedQuery] = useState<string>('');
  const [isSearching, setIsSearching] = useState<boolean>(false);
  const [isSyncing, setIsSyncing] = useState<boolean>(false);
  const [syncMessage, setSyncMessage] = useState<string | null>(null);
  const [lookupMessage, setLookupMessage] = useState<string | null>(null);
  const [isLookingUp, setIsLookingUp] = useState<boolean>(false);

  // Selection state
  const [selectedCodes, setSelectedCodes] = useState<string[]>([]);
  const [activeCode, setActiveCode] = useState<string>('');
  const [examType, setExamType] = useState<'FE' | 'PE'>('FE');
  const [limit, setLimit] = useState<number>(4);

  // Exams for active subject
  const [exams, setExams] = useState<ExamItem[]>([]);
  const [isLoadingExams, setIsLoadingExams] = useState<boolean>(false);
  const [selectedExamIds, setSelectedExamIds] = useState<Record<string, number[]>>({});

  // System statuses
  const [authStatus, setAuthStatus] = useState<AuthStatus | null>(null);
  const [showCookieModal, setShowCookieModal] = useState<boolean>(Boolean(initialOpenLogin));
  const [loginModalMode, setLoginModalMode] = useState<'account' | 'cookie'>('account');
  const [accountUsername, setAccountUsername] = useState<string>('');
  const [accountPassword, setAccountPassword] = useState<string>('');
  const [isLoggingInAccount, setIsLoggingInAccount] = useState<boolean>(false);
  const [accountError, setAccountError] = useState<string | null>(null);
  const [cookieInput, setCookieInput] = useState<string>('');
  const [cookieError, setCookieError] = useState<string | null>(null);
  const [isSavingCookie, setIsSavingCookie] = useState<boolean>(false);
  const [filterSelectedOnly, setFilterSelectedOnly] = useState<boolean>(false);

  // Close modal on Escape key
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && showCookieModal) {
        setShowCookieModal(false);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [showCookieModal]);

  // Debounce search query 250ms
  useEffect(() => {
    const handler = setTimeout(() => {
      setDebouncedQuery(searchQuery.trim());
    }, 250);
    return () => clearTimeout(handler);
  }, [searchQuery]);

  // Fetch subjects list when debouncedQuery changes
  useEffect(() => {
    setIsSearching(true);
    setLookupMessage(null);
    const url = debouncedQuery
      ? `/api/subjects?q=${encodeURIComponent(debouncedQuery)}&limit=100`
      : `/api/subjects?limit=100`;

    fetch(url)
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((data: { items: Subject[]; total: number; last_synced_at?: string }) => {
        setSubjects(data.items || []);
        setTotalSubjects(data.total || 0);
        if (data.last_synced_at) {
          setLastSyncedAt(data.last_synced_at);
        }
      })
      .catch((err) => {
        console.error('Failed to load subjects:', err);
      })
      .finally(() => {
        setIsSearching(false);
      });
  }, [debouncedQuery]);

  // Fetch exams for activeCode
  useEffect(() => {
    if (!activeCode) return;
    setIsLoadingExams(true);
    fetch(`/api/subjects/${activeCode}/exams?type=${examType}`)
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((data: ExamItem[]) => {
        const list = data || [];
        setExams(list);
        const count = list.length;
        let targetLimit = 1;
        if (count >= 4) {
          targetLimit = 4;
        } else if (count > 0) {
          targetLimit = count;
        } else {
          targetLimit = 1;
        }
        setLimit(targetLimit);

        // Auto select top targetLimit exams if none selected yet or reset to targetLimit
        const defaultSelected = list.slice(0, targetLimit).map((e) => e.id);
        setSelectedExamIds((prev) => ({ ...prev, [activeCode]: defaultSelected }));
      })
      .catch((err) => {
        console.error(`Failed to load exams for ${activeCode}:`, err);
        setExams([]);
      })
      .finally(() => {
        setIsLoadingExams(false);
      });
  }, [activeCode, examType]);

  // Check auth & AI statuses on mount
  const checkAuth = () => {
    fetch('/api/auth/status')
      .then((res) => (res.ok ? res.json() : { logged_in: false }))
      .then((data: AuthStatus) => setAuthStatus(data))
      .catch(() => setAuthStatus({ logged_in: false }));
  };

  useEffect(() => {
    checkAuth();
  }, []);

  // Periodic real-time background sync every 20 seconds (auto-checks auth status and updates exam list)
  useEffect(() => {
    const timer = setInterval(() => {
      checkAuth();
      if (activeCode) {
        fetch(`/api/subjects/${activeCode}/exams?type=${examType}`)
          .then((res) => (res.ok ? res.json() : null))
          .then((data: ExamItem[] | null) => {
            if (data && data.length > 0) {
              setExams(data);
            }
          })
          .catch(() => {});
      }
    }, 20000);
    return () => clearInterval(timer);
  }, [activeCode, examType]);

  // Handle sync subjects button
  const handleSyncSubjects = async () => {
    setIsSyncing(true);
    setSyncMessage(null);
    try {
      const res = await fetch('/api/subjects/sync', { method: 'POST' });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setSyncMessage(`Đã cập nhật danh sách môn: ${data.total} môn (thêm ${data.added}, cập nhật ${data.updated}).`);
      if (data.last_synced_at) setLastSyncedAt(data.last_synced_at);
      // Refresh list
      const ref = await fetch('/api/subjects?limit=100');
      const refData = await ref.json();
      setSubjects(refData.items || []);
      setTotalSubjects(refData.total || 0);
    } catch (err: any) {
      setSyncMessage('Cập nhật thất bại. Vui lòng kiểm tra kết nối mạng.');
    } finally {
      setIsSyncing(false);
    }
  };

  // Handle lookup subject by code on forum
  const handleLookupSubject = async () => {
    if (!debouncedQuery) return;
    setIsLookingUp(true);
    setLookupMessage(null);
    try {
      const res = await fetch('/api/subjects/lookup', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ code: debouncedQuery }),
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || `Không tìm thấy môn "${debouncedQuery}" trên diễn đàn FUOverflow.`);
      }

      const newSubject: Subject = await res.json();
      setSubjects((prev) => [newSubject, ...prev.filter((s) => s.code !== newSubject.code)]);
      if (!selectedCodes.includes(newSubject.code)) {
        setSelectedCodes((prev) => [...prev, newSubject.code]);
      }
      setActiveCode(newSubject.code);
      setLookupMessage(`Tìm thấy môn: ${newSubject.code} — ${newSubject.name}. Đã tự động thêm và chọn.`);
    } catch (err: any) {
      setLookupMessage(err.message || `Không tìm thấy môn "${debouncedQuery}".`);
    } finally {
      setIsLookingUp(false);
    }
  };

  // Toggle subject selection checkbox
  const toggleSubject = (code: string) => {
    setSelectedCodes((prev) => {
      const exists = prev.includes(code);
      const next = exists ? prev.filter((c) => c !== code) : [...prev, code];
      if (!exists) {
        setActiveCode(code);
      } else if (activeCode === code && next.length > 0) {
        setActiveCode(next[0]);
      }
      return next;
    });
  };

  // Remove subject
  const removeSubject = (code: string) => {
    setSelectedCodes((prev) => {
      const next = prev.filter((c) => c !== code);
      if (activeCode === code && next.length > 0) {
        setActiveCode(next[0]);
      }
      return next;
    });
  };

  // Toggle exam selection checkbox
  const toggleExam = (subjectCode: string, examId: number) => {
    setSelectedExamIds((prev) => {
      const current = prev[subjectCode] || [];
      const updated = current.includes(examId)
        ? current.filter((id) => id !== examId)
        : [...current, examId];

      // Two-way sync: automatically sync stepper limit with checked count
      if (subjectCode === activeCode) {
        setLimit(Math.max(1, updated.length));
      }
      return { ...prev, [subjectCode]: updated };
    });
  };

  // Open FUOverflow in a new tab so user can log in with their existing browser
  const handleOpenFuOverflow = () => {
    window.open('https://fuoverflow.com/login/', '_blank', 'noopener,noreferrer');
    // Show cookie modal after a short delay so user knows what to do next
    setTimeout(() => setShowCookieModal(true), 800);
  };

  // Login with account credentials (username & password) directly
  const handleLoginWithAccount = async () => {
    if (!accountUsername.trim() || !accountPassword.trim()) {
      setAccountError('Vui lòng nhập đầy đủ tên đăng nhập và mật khẩu.');
      return;
    }
    setIsLoggingInAccount(true);
    setAccountError(null);
    try {
      const res = await fetch('/api/auth/login-account', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          username: accountUsername.trim(),
          password: accountPassword.trim(),
        }),
      });
      const data = await res.json();
      if (data.logged_in) {
        setAuthStatus({ logged_in: true, username: accountUsername.trim() });
        setShowCookieModal(false);
        setAccountPassword('');
        checkAuth();
      } else {
        setAccountError(data.message || 'Đăng nhập không thành công.');
      }
    } catch (err: any) {
      setAccountError('Lỗi kết nối máy chủ: ' + err.message);
    } finally {
      setIsLoggingInAccount(false);
    }
  };

  // Save cookie manually
  const handleSaveCookie = async () => {
    if (!cookieInput.trim()) {
      setCookieError('Vui lòng dán chuỗi cookie (xf_user / xf_session).');
      return;
    }
    setIsSavingCookie(true);
    setCookieError(null);
    try {
      const res = await fetch('/api/auth/cookies', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ cookie_string: cookieInput.trim() }),
      });
      const data = await res.json();
      if (data.logged_in) {
        setAuthStatus({ logged_in: true, username: 'Thành viên FUOverflow' });
        setShowCookieModal(false);
        setCookieInput('');
      } else {
        setCookieError(data.message || 'Cookie không hợp lệ hoặc đã hết hạn.');
      }
    } catch (err: any) {
      setCookieError('Lỗi kết nối khi gửi cookie: ' + err.message);
    } finally {
      setIsSavingCookie(false);
    }
  };

  // Calculate summary counts
  const totalExamsSelected = selectedCodes.reduce((sum, code) => {
    const chosen = selectedExamIds[code]?.length;
    return sum + (chosen !== undefined ? chosen : Math.min(limit, exams.length || limit));
  }, 0);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (selectedCodes.length === 0) return;
    // Launch for first/active subject or batch
    onStartJob(selectedCodes[0], examType, limit);
  };

  const formattedSyncTime = lastSyncedAt
    ? new Date(lastSyncedAt).toLocaleString('vi-VN', {
        day: '2-digit',
        month: '2-digit',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
      })
    : null;

  const displayedSubjects = filterSelectedOnly
    ? subjects.filter((s) => selectedCodes.includes(s.code))
    : subjects;

  return (
    <div className="select-subject-layout">
      {/* Left Column: Subjects and Exams List */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-5)' }}>
        {/* Card: Danh sách môn học */}
        <div className="card-paper">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 'var(--space-4)', flexWrap: 'wrap', gap: 'var(--space-3)' }}>
            <div>
              <h2 className="serif-title" style={{ fontSize: 'var(--text-2xl)', marginBottom: 'var(--space-1)', display: 'flex', alignItems: 'center' }}>
                <span className="step-badge">1</span> Chọn môn học cần biên soạn
              </h2>
              <p style={{ color: 'var(--text-secondary)', fontSize: 'var(--text-sm)' }}>
                Dữ liệu tổng hợp từ diễn đàn FUOverflow. Chọn môn để quét danh sách đề do sinh viên đăng trên diễn đàn.
              </p>
            </div>

            {/* Sync Button & Stats */}
            <div style={{ textAlign: 'right' }}>
              <button
                type="button"
                onClick={handleSyncSubjects}
                disabled={isSyncing}
                aria-label="Cập nhật danh sách môn học từ diễn đàn"
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '6px',
                  padding: '6px 12px',
                  fontSize: 'var(--text-xs)',
                  fontWeight: 600,
                  backgroundColor: 'var(--bg-canvas)',
                  border: '1px solid var(--border-strong)',
                  borderRadius: 'var(--radius-sm)',
                  color: 'var(--text-primary)',
                  cursor: isSyncing ? 'not-allowed' : 'pointer',
                  minHeight: '34px',
                }}
              >
                <span style={{ display: 'inline-block', transform: isSyncing ? 'rotate(360deg)' : 'none', transition: 'transform 1s linear' }}>
                  🔄
                </span>
                {isSyncing ? 'Đang cập nhật...' : 'Cập nhật danh sách môn'}
              </button>
              <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '4px' }}>
                {totalSubjects > 0 && `${totalSubjects} môn học`}
                {formattedSyncTime && ` · Cập nhật: ${formattedSyncTime}`}
              </div>
            </div>
          </div>

          {syncMessage && (
            <div
              role="status"
              style={{
                padding: 'var(--space-2) var(--space-3)',
                backgroundColor: 'var(--status-confident-bg)',
                border: '1px solid var(--status-confident-border)',
                borderRadius: 'var(--radius-sm)',
                color: 'var(--status-confident-text)',
                fontSize: 'var(--text-xs)',
                marginBottom: 'var(--space-3)',
              }}
            >
              {syncMessage}
            </div>
          )}

          {/* Quick Toolbar: Summary and Filter by Selected */}
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              marginBottom: 'var(--space-3)',
              gap: 'var(--space-2)',
              flexWrap: 'wrap',
              fontSize: 'var(--text-xs)',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', flexWrap: 'wrap' }}>
              <span style={{ fontWeight: 600, color: 'var(--text-primary)' }}>
                Đã chọn: <strong style={{ color: 'var(--primary)' }}>{selectedCodes.length}</strong> môn
              </span>
              <div style={{ display: 'inline-flex', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-subtle)', overflow: 'hidden' }}>
                <button
                  type="button"
                  onClick={() => setFilterSelectedOnly(false)}
                  style={{
                    padding: '3px 8px',
                    fontSize: '11px',
                    fontWeight: !filterSelectedOnly ? 600 : 400,
                    backgroundColor: !filterSelectedOnly ? 'var(--primary)' : 'var(--bg-canvas)',
                    color: !filterSelectedOnly ? '#fff' : 'var(--text-secondary)',
                    border: 'none',
                    cursor: 'pointer',
                  }}
                >
                  Tất cả môn ({totalSubjects || subjects.length})
                </button>
                <button
                  type="button"
                  onClick={() => setFilterSelectedOnly(true)}
                  style={{
                    padding: '3px 8px',
                    fontSize: '11px',
                    fontWeight: filterSelectedOnly ? 600 : 400,
                    backgroundColor: filterSelectedOnly ? 'var(--primary)' : 'var(--bg-canvas)',
                    color: filterSelectedOnly ? '#fff' : 'var(--text-secondary)',
                    border: 'none',
                    borderLeft: '1px solid var(--border-subtle)',
                    cursor: 'pointer',
                  }}
                >
                  Chỉ hiện đã chọn ({selectedCodes.length})
                </button>
              </div>
            </div>

            {selectedCodes.length > 0 && (
              <button
                type="button"
                onClick={() => {
                  setSelectedCodes([]);
                  setActiveCode('');
                }}
                style={{
                  background: 'none',
                  border: 'none',
                  color: 'var(--text-muted)',
                  fontSize: '11px',
                  cursor: 'pointer',
                  textDecoration: 'underline',
                }}
              >
                Bỏ chọn tất cả
              </button>
            )}
          </div>

          {/* Search Box */}
          <div style={{ position: 'relative', marginBottom: 'var(--space-3)' }}>
            <input
              type="text"
              placeholder="Tìm theo mã môn (vd CSD202, PRN212) hoặc tên tiếng Việt..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              aria-label="Tìm kiếm môn học"
              style={{
                width: '100%',
                padding: 'var(--space-2) var(--space-3)',
                paddingRight: searchQuery ? '60px' : isSearching ? '40px' : 'var(--space-3)',
                backgroundColor: 'var(--bg-canvas)',
                border: '1px solid var(--border-strong)',
                borderRadius: 'var(--radius-sm)',
                fontFamily: 'var(--font-sans)',
                fontSize: 'var(--text-sm)',
                color: 'var(--text-primary)',
              }}
            />
            {searchQuery && (
              <button
                type="button"
                onClick={() => setSearchQuery('')}
                aria-label="Xóa nội dung tìm kiếm"
                style={{
                  position: 'absolute',
                  right: isSearching ? '34px' : '10px',
                  top: '50%',
                  transform: 'translateY(-50%)',
                  background: 'none',
                  border: 'none',
                  color: 'var(--text-muted)',
                  cursor: 'pointer',
                  fontSize: '14px',
                  padding: '4px',
                }}
              >
                ✕
              </button>
            )}
            {isSearching && (
              <span
                style={{
                  position: 'absolute',
                  right: '12px',
                  top: '50%',
                  transform: 'translateY(-50%)',
                  fontSize: 'var(--text-xs)',
                  color: 'var(--text-muted)',
                }}
              >
                ⏳
              </span>
            )}
          </div>

          {lookupMessage && (
            <div
              style={{
                padding: 'var(--space-2) var(--space-3)',
                backgroundColor: lookupMessage.includes('Tìm thấy') ? 'var(--status-confident-bg)' : 'var(--status-conflict-bg)',
                border: `1px solid ${lookupMessage.includes('Tìm thấy') ? 'var(--status-confident-border)' : 'var(--status-conflict-border)'}`,
                borderRadius: 'var(--radius-sm)',
                color: lookupMessage.includes('Tìm thấy') ? 'var(--status-confident-text)' : 'var(--status-conflict-text)',
                fontSize: 'var(--text-xs)',
                marginBottom: 'var(--space-3)',
              }}
            >
              {lookupMessage}
            </div>
          )}

          {/* Subjects Table List */}
          <div
            style={{
              border: '1px solid var(--border-subtle)',
              borderRadius: 'var(--radius-sm)',
              maxHeight: '320px',
              overflowY: 'auto',
            }}
          >
            {displayedSubjects.length === 0 ? (
              <div style={{ padding: 'var(--space-6)', textAlign: 'center', color: 'var(--text-secondary)' }}>
                <p style={{ marginBottom: 'var(--space-3)', fontSize: 'var(--text-sm)' }}>
                  {filterSelectedOnly
                    ? 'Bạn chưa tích chọn môn học nào. Hãy nhấp tab "Tất cả môn" ở trên để chọn môn.'
                    : `Không tìm thấy môn "${searchQuery}" trong danh mục đã lưu.`}
                </p>
                {!filterSelectedOnly && searchQuery.trim().length >= 2 && (
                  <button
                    type="button"
                    onClick={handleLookupSubject}
                    disabled={isLookingUp}
                    style={{
                      padding: 'var(--space-2) var(--space-4)',
                      backgroundColor: 'var(--primary)',
                      color: '#FFFFFF',
                      border: 'none',
                      borderRadius: 'var(--radius-sm)',
                      fontSize: 'var(--text-xs)',
                      fontWeight: 600,
                      cursor: isLookingUp ? 'not-allowed' : 'pointer',
                    }}
                  >
                    {isLookingUp ? 'Đang tìm kiếm...' : `🔍 Thử tìm mã "${searchQuery.trim()}" trên diễn đàn`}
                  </button>
                )}
              </div>
            ) : (
              displayedSubjects.map((subject) => {
                const isChecked = selectedCodes.includes(subject.code);
                const isActive = subject.code === activeCode;
                return (
                  <div
                    key={subject.code}
                    onClick={() => setActiveCode(subject.code)}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      padding: 'var(--space-2) var(--space-3)',
                      borderBottom: '1px solid var(--border-subtle)',
                      backgroundColor: isActive ? 'var(--bg-subtle)' : 'transparent',
                      borderLeft: isActive ? '4px solid var(--primary)' : '4px solid transparent',
                      cursor: 'pointer',
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)' }}>
                      <input
                        type="checkbox"
                        checked={isChecked}
                        onChange={(e) => {
                          e.stopPropagation();
                          toggleSubject(subject.code);
                        }}
                        style={{ cursor: 'pointer', accentColor: 'var(--primary)', width: '16px', height: '16px' }}
                      />
                      <span
                        style={{
                          fontFamily: 'var(--font-mono)',
                          fontWeight: 700,
                          fontSize: 'var(--text-sm)',
                          padding: '2px 6px',
                          backgroundColor: isChecked ? 'var(--primary-subtle)' : 'var(--bg-canvas)',
                          color: isChecked ? 'var(--primary)' : 'var(--text-primary)',
                          border: '1px solid var(--border-subtle)',
                          borderRadius: 'var(--radius-sm)',
                        }}
                      >
                        {subject.code}
                      </span>
                      <span style={{ fontSize: 'var(--text-sm)', color: 'var(--text-primary)' }}>
                        {subject.name}
                      </span>
                    </div>

                    <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}>
                      <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                        {isActive ? 'Đang xem đề' : ''}
                      </span>
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </div>

        {/* Card: Danh sách đề thực tế của môn đang chọn */}
        <div className="card-paper">
          {!activeCode ? (
            <div style={{ textAlign: 'center', padding: 'var(--space-6) var(--space-4)', color: 'var(--text-muted)' }}>
              <div style={{ fontSize: '28px', marginBottom: '8px' }}>📂</div>
              <div style={{ fontWeight: 600, fontSize: 'var(--text-sm)', color: 'var(--text-secondary)' }}>
                Chưa chọn môn học nào
              </div>
              <div style={{ fontSize: 'var(--text-xs)', marginTop: '4px' }}>
                Vui lòng nhấp vào một môn học ở danh sách phía trên để xem các đề thi.
              </div>
            </div>
          ) : (
            <>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 'var(--space-3)' }}>
              <div>
                <h3 className="serif-title" style={{ fontSize: 'var(--text-lg)' }}>
                  Danh sách đề {examType} của môn {activeCode}
                </h3>
                <p style={{ fontSize: 'var(--text-xs)', color: 'var(--text-secondary)' }}>
                  Đề thực tế được đồng bộ từ diễn đàn FUOverflow. Tích chọn các đề bạn muốn biên soạn.
                </p>
              </div>

              {exams.length > 0 && exams.length < limit && (
                <div
                  style={{
                    padding: '4px 8px',
                    backgroundColor: 'var(--status-weak-bg)',
                    border: '1px solid var(--status-weak-border)',
                    borderRadius: 'var(--radius-sm)',
                    fontSize: '11px',
                    color: 'var(--status-weak-text)',
                    fontWeight: 600,
                  }}
                >
                  ⚠️ Môn này chỉ có {exams.length} đề {examType}
                </div>
              )}
            </div>

            {isLoadingExams ? (
              <div style={{ padding: 'var(--space-4)', textAlign: 'center', color: 'var(--text-muted)', fontSize: 'var(--text-xs)' }}>
                Đang quét danh sách đề từ diễn đàn...
              </div>
            ) : exams.length === 0 ? (
              <div style={{ padding: 'var(--space-4)', textAlign: 'center', color: 'var(--text-muted)', fontSize: 'var(--text-xs)' }}>
                Chưa tìm thấy đề {examType} nào cho môn {activeCode} trên diễn đàn.
              </div>
            ) : (
              <div
                style={{
                  display: 'flex',
                  flexDirection: 'column',
                  gap: 'var(--space-2)',
                  maxHeight: '260px',
                  overflowY: 'auto',
                }}
              >
                {exams.map((exam, index) => {
                  const isExamSelected = (selectedExamIds[activeCode] || []).includes(exam.id);
                  return (
                    <label
                      key={exam.id}
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        padding: 'var(--space-2) var(--space-3)',
                        border: '1px solid var(--border-subtle)',
                        borderRadius: 'var(--radius-sm)',
                        backgroundColor: isExamSelected ? 'var(--bg-subtle)' : 'var(--bg-canvas)',
                        cursor: 'pointer',
                        fontSize: 'var(--text-sm)',
                      }}
                    >
                      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}>
                        <input
                          type="checkbox"
                          checked={isExamSelected}
                          onChange={() => toggleExam(activeCode, exam.id)}
                          style={{ accentColor: 'var(--primary)', cursor: 'pointer' }}
                        />
                        <span style={{ fontWeight: 600, color: 'var(--text-primary)' }}>
                          #{index + 1} {exam.title}
                        </span>
                      </div>

                      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)', fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>
                        {exam.term && (
                          <span style={{ fontFamily: 'var(--font-mono)', padding: '1px 4px', backgroundColor: 'var(--bg-surface)', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-sm)' }}>
                            {exam.term}
                          </span>
                        )}
                        {exam.question_count > 0 && <span>{exam.question_count} câu</span>}
                      </div>
                    </label>
                  );
                })}
              </div>
            )}
          </>
        )}
      </div>
      </div>

      {/* Right Column: Configuration & Status Panel */}
      <div className="card-paper" style={{ position: 'sticky', top: 'var(--space-4)' }}>
        <h3
          className="serif-title"
          style={{ fontSize: 'var(--text-lg)', marginBottom: 'var(--space-4)', borderBottom: '1px solid var(--border-subtle)', paddingBottom: 'var(--space-2)', display: 'flex', alignItems: 'center' }}
        >
          <span className="step-badge">2</span> Phân loại & Số lượng đề
        </h3>

        <form onSubmit={handleSubmit}>
          {/* Selected Subjects List */}
          <div style={{ marginBottom: 'var(--space-4)' }}>
            <label style={{ display: 'block', fontSize: 'var(--text-xs)', color: 'var(--text-secondary)', marginBottom: 'var(--space-1)' }}>
              Môn đã chọn ({selectedCodes.length})
            </label>
            {selectedCodes.length === 0 ? (
              <div style={{ fontSize: 'var(--text-xs)', color: 'var(--status-conflict-text)', padding: 'var(--space-2)', backgroundColor: 'var(--status-conflict-bg)', borderRadius: 'var(--radius-sm)' }}>
                Chưa chọn môn nào. Hãy tích chọn ít nhất 1 môn ở danh sách bên trái.
              </div>
            ) : (
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', maxHeight: '110px', overflowY: 'auto' }}>
                {selectedCodes.map((code) => (
                  <span
                    key={code}
                    onClick={() => setActiveCode(code)}
                    style={{
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: '4px',
                      padding: '3px 8px',
                      backgroundColor: code === activeCode ? 'var(--primary-subtle)' : 'var(--bg-subtle)',
                      border: `1px solid ${code === activeCode ? 'var(--primary)' : 'var(--border-strong)'}`,
                      borderRadius: 'var(--radius-sm)',
                      fontFamily: 'var(--font-mono)',
                      fontSize: 'var(--text-xs)',
                      fontWeight: 600,
                      color: code === activeCode ? 'var(--primary)' : 'var(--text-primary)',
                      cursor: 'pointer',
                    }}
                  >
                    {code}
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        removeSubject(code);
                      }}
                      style={{
                        background: 'none',
                        border: 'none',
                        color: 'var(--text-muted)',
                        cursor: 'pointer',
                        padding: '0 2px',
                        fontSize: '12px',
                        fontWeight: 700,
                      }}
                    >
                      ×
                    </button>
                  </span>
                ))}
              </div>
            )}
          </div>

          {/* Exam Type Selector (FE vs PE) */}
          <div style={{ marginBottom: 'var(--space-4)' }}>
            <label style={{ display: 'block', fontSize: 'var(--text-xs)', color: 'var(--text-secondary)', marginBottom: 'var(--space-1)' }}>
              Phân loại đề thi
            </label>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 'var(--space-2)' }}>
              <button
                type="button"
                onClick={() => setExamType('FE')}
                style={{
                  padding: 'var(--space-2) var(--space-3)',
                  textAlign: 'left',
                  backgroundColor: examType === 'FE' ? 'var(--primary-subtle)' : 'var(--bg-canvas)',
                  color: examType === 'FE' ? 'var(--primary)' : 'var(--text-primary)',
                  border: `2px solid ${examType === 'FE' ? 'var(--primary)' : 'var(--border-subtle)'}`,
                  borderRadius: 'var(--radius-sm)',
                  cursor: 'pointer',
                }}
              >
                <div style={{ fontWeight: 700, fontSize: 'var(--text-sm)' }}>Đề FE (Lý thuyết)</div>
                <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '2px' }}>
                  Ảnh câu hỏi + AI & Word
                </div>
              </button>
              <button
                type="button"
                onClick={() => setExamType('PE')}
                style={{
                  padding: 'var(--space-2) var(--space-3)',
                  textAlign: 'left',
                  backgroundColor: examType === 'PE' ? 'var(--primary-subtle)' : 'var(--bg-canvas)',
                  color: examType === 'PE' ? 'var(--primary)' : 'var(--text-primary)',
                  border: `2px solid ${examType === 'PE' ? 'var(--primary)' : 'var(--border-subtle)'}`,
                  borderRadius: 'var(--radius-sm)',
                  cursor: 'pointer',
                }}
              >
                <div style={{ fontWeight: 700, fontSize: 'var(--text-sm)' }}>Đề PE (Thực hành)</div>
                <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '2px' }}>
                  Tải file .pdf / .zip gốc
                </div>
              </button>
            </div>
          </div>

          {/* PE Explanation Card */}
          {examType === 'PE' ? (
            <div
              style={{
                padding: 'var(--space-3)',
                backgroundColor: 'var(--bg-subtle)',
                border: '1px solid var(--border-subtle)',
                borderRadius: 'var(--radius-sm)',
                marginBottom: 'var(--space-4)',
                fontSize: 'var(--text-xs)',
                color: 'var(--text-secondary)',
                lineHeight: 'var(--leading-relaxed)',
              }}
            >
              <div style={{ fontWeight: 700, color: 'var(--text-primary)', marginBottom: '4px' }}>
                📘 Quy tắc tải đề PE (Thực hành)
              </div>
              Đề PE là bài thi thực hành lập trình. DocxStacked chỉ tải trực tiếp tệp đề bài gốc (.pdf) và mã nguồn mẫu (.zip) về thư mục lưu trữ, không có ảnh từng câu, không gọi AI và không tạo tệp .docx.
            </div>
          ) : (
            /* Limit Number Selector (adaptive to exams.length) for FE */
            (() => {
              const maxAvailable = exams.length;
              const isLocked = maxAvailable <= 1;
              const canDecrease = !isLocked && limit > 1;
              const canIncrease = !isLocked && limit < Math.min(20, maxAvailable);

              const handleDecrease = () => {
                if (canDecrease) {
                  const next = limit - 1;
                  setLimit(next);
                  // Uncheck from bottom up: keep first `next` checked items in order of exams list
                  const currentSelected = selectedExamIds[activeCode] || [];
                  const orderedSelected = exams.filter((e) => currentSelected.includes(e.id)).map((e) => e.id);
                  const nextSelected = orderedSelected.slice(0, next);
                  setSelectedExamIds((prev) => ({
                    ...prev,
                    [activeCode]: nextSelected,
                  }));
                }
              };

              const handleIncrease = () => {
                if (canIncrease) {
                  const next = limit + 1;
                  setLimit(next);
                  // Check next available exam from top down
                  const currentSelected = selectedExamIds[activeCode] || [];
                  const unselected = exams.filter((e) => !currentSelected.includes(e.id));
                  const nextExam = unselected[0];
                  const nextSelected = nextExam
                    ? [...currentSelected, nextExam.id]
                    : exams.slice(0, next).map((e) => e.id);
                  setSelectedExamIds((prev) => ({
                    ...prev,
                    [activeCode]: nextSelected,
                  }));
                }
              };

              const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
                if (isLocked) return;
                const val = Number(e.target.value) || 1;
                const clamped = Math.min(Math.min(20, maxAvailable), Math.max(1, val));
                setLimit(clamped);
                setSelectedExamIds((prev) => ({
                  ...prev,
                  [activeCode]: exams.slice(0, clamped).map((item) => item.id),
                }));
              };

              let badgeText = '';
              if (maxAvailable === 0) {
                badgeText = '0 đề (chưa có)';
              } else if (maxAvailable === 1) {
                badgeText = '1 đề duy nhất';
              } else if (limit === 4 && maxAvailable >= 4) {
                badgeText = '4 đề (chuẩn)';
              } else {
                badgeText = `${limit} / ${maxAvailable} đề`;
              }

              return (
                <div style={{ marginBottom: 'var(--space-4)' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 'var(--space-1)' }}>
                    <label style={{ fontSize: 'var(--text-xs)', color: 'var(--text-secondary)' }}>
                      Số đề mới nhất mỗi môn
                    </label>
                    <span
                      style={{
                        fontSize: '11px',
                        fontFamily: 'var(--font-mono)',
                        padding: '1px 6px',
                        backgroundColor: limit === 4 && maxAvailable >= 4 ? 'var(--status-confident-bg)' : 'var(--bg-subtle)',
                        color: limit === 4 && maxAvailable >= 4 ? 'var(--status-confident-text)' : 'var(--text-muted)',
                        borderRadius: 'var(--radius-sm)',
                        border: '1px solid var(--border-subtle)',
                      }}
                    >
                      {badgeText}
                    </span>
                  </div>

                  <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}>
                    <button
                      type="button"
                      disabled={!canDecrease}
                      onClick={handleDecrease}
                      style={{
                        width: '36px',
                        height: '36px',
                        backgroundColor: !canDecrease ? 'var(--bg-subtle)' : 'var(--bg-canvas)',
                        border: '1px solid var(--border-strong)',
                        borderRadius: 'var(--radius-sm)',
                        fontWeight: 700,
                        fontSize: '16px',
                        color: !canDecrease ? 'var(--text-muted)' : 'var(--text-primary)',
                        cursor: !canDecrease ? 'not-allowed' : 'pointer',
                        opacity: !canDecrease ? 0.45 : 1,
                      }}
                      title={!canDecrease ? (isLocked ? 'Môn này chỉ có 1 đề duy nhất' : 'Đã đạt số đề tối thiểu (1 đề)') : 'Giảm 1 đề'}
                    >
                      -
                    </button>
                    <input
                      type="number"
                      min={1}
                      max={Math.max(1, maxAvailable)}
                      value={limit}
                      disabled={isLocked}
                      onChange={handleInputChange}
                      style={{
                        flex: 1,
                        textAlign: 'center',
                        padding: 'var(--space-2)',
                        backgroundColor: isLocked ? 'var(--bg-subtle)' : 'var(--bg-canvas)',
                        border: '1px solid var(--border-strong)',
                        borderRadius: 'var(--radius-sm)',
                        fontFamily: 'var(--font-mono)',
                        fontSize: 'var(--text-base)',
                        fontWeight: 600,
                        color: isLocked ? 'var(--text-muted)' : 'var(--text-primary)',
                        cursor: isLocked ? 'not-allowed' : 'text',
                      }}
                    />
                    <button
                      type="button"
                      disabled={!canIncrease}
                      onClick={handleIncrease}
                      style={{
                        width: '36px',
                        height: '36px',
                        backgroundColor: !canIncrease ? 'var(--bg-subtle)' : 'var(--bg-canvas)',
                        border: '1px solid var(--border-strong)',
                        borderRadius: 'var(--radius-sm)',
                        fontWeight: 700,
                        fontSize: '16px',
                        color: !canIncrease ? 'var(--text-muted)' : 'var(--text-primary)',
                        cursor: !canIncrease ? 'not-allowed' : 'pointer',
                        opacity: !canIncrease ? 0.45 : 1,
                      }}
                      title={!canIncrease ? (isLocked ? 'Môn này chỉ có 1 đề duy nhất' : `Đã đạt số đề tối đa (${maxAvailable} đề)`) : 'Tăng 1 đề'}
                    >
                      +
                    </button>
                  </div>
                </div>
              );
            })()
          )}

          {/* Step 3: Tóm tắt kế hoạch & Bắt đầu */}
          <div style={{ marginTop: 'var(--space-4)', borderTop: '1px solid var(--border-subtle)', paddingTop: 'var(--space-4)' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 'var(--space-2)' }}>
              <h4 className="serif-title" style={{ fontSize: 'var(--text-base)', margin: 0, display: 'flex', alignItems: 'center' }}>
                <span className="step-badge">3</span> Kế hoạch & Bắt đầu
              </h4>
              {authStatus?.logged_in ? (
                <span style={{ fontSize: '11px', color: 'var(--status-confident-text)', fontWeight: 600 }}>
                  🟢 {authStatus.username || 'Đã đăng nhập'}
                </span>
              ) : (
                <button
                  type="button"
                  onClick={() => { setShowCookieModal(true); setLoginModalMode('account'); }}
                  style={{
                    background: 'none',
                    border: 'none',
                    fontSize: '11px',
                    fontWeight: 600,
                    color: 'var(--primary)',
                    cursor: 'pointer',
                    textDecoration: 'underline',
                  }}
                >
                  🔑 Đăng nhập
                </button>
              )}
            </div>

            {/* Summary Box */}
            <div
              style={{
                padding: 'var(--space-3)',
                backgroundColor: 'var(--bg-subtle)',
                border: '1px solid var(--border-subtle)',
                borderRadius: 'var(--radius-sm)',
                marginBottom: 'var(--space-3)',
                fontSize: 'var(--text-xs)',
              }}
            >
              <div style={{ fontWeight: 600, color: 'var(--text-primary)', marginBottom: '2px' }}>
                📋 {selectedCodes.length} môn · {totalExamsSelected} đề {examType} · tạo {examType === 'FE' ? totalExamsSelected : 0} file .docx
              </div>
              <div style={{ color: 'var(--text-secondary)' }}>
                {selectedCodes.length > 0 ? `Đang chọn: ${selectedCodes.join(', ')}` : 'Chưa chọn môn học nào'}
              </div>
              {exams.length > 0 && exams.length < limit && (
                <div
                  style={{
                    marginTop: '6px',
                    padding: '3px 6px',
                    backgroundColor: 'var(--status-weak-bg)',
                    border: '1px solid var(--status-weak-border)',
                    borderRadius: 'var(--radius-sm)',
                    color: 'var(--status-weak-text)',
                    fontWeight: 600,
                    fontSize: '11px',
                  }}
                >
                  ⚠️ Môn {activeCode} chỉ có {exams.length} đề (yêu cầu {limit} đề).
                </div>
              )}
            </div>

            {/* Condition-aware CTA Action */}
            {selectedCodes.length === 0 ? (
              <div>
                <button
                  type="button"
                  disabled
                  className="btn-primary"
                  style={{
                    width: '100%',
                    padding: 'var(--space-3)',
                    fontSize: 'var(--text-sm)',
                    cursor: 'not-allowed',
                    opacity: 0.6,
                  }}
                >
                  Chưa chọn môn học
                </button>
                <div style={{ fontSize: '11px', color: 'var(--text-muted)', textAlign: 'center', marginTop: '6px' }}>
                  Vui lòng tích chọn ít nhất 1 môn ở Bước 1 bên trái
                </div>
              </div>
            ) : !authStatus?.logged_in ? (
              <div>
                <button
                  type="button"
                  onClick={() => { setShowCookieModal(true); setLoginModalMode('account'); }}
                  className="btn-primary"
                  style={{
                    width: '100%',
                    padding: 'var(--space-3)',
                    fontSize: 'var(--text-sm)',
                    backgroundColor: '#9A3412',
                    cursor: 'pointer',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    gap: '8px',
                  }}
                >
                  🔑 Đăng nhập để bắt đầu biên soạn
                </button>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: '6px', fontSize: '11px' }}>
                  <span style={{ color: 'var(--text-muted)' }}>Cần tài khoản FUOverflow để tải đề</span>
                  <button
                    type="button"
                    onClick={handleOpenFuOverflow}
                    style={{ background: 'none', border: 'none', color: 'var(--ink-blue)', cursor: 'pointer', textDecoration: 'underline' }}
                  >
                    Mở web ↗
                  </button>
                </div>
              </div>
            ) : (
              <div>
                <button
                  type="submit"
                  className="btn-primary"
                  disabled={isLoading || totalExamsSelected === 0}
                  style={{
                    width: '100%',
                    padding: 'var(--space-3)',
                    fontSize: 'var(--text-base)',
                    cursor: isLoading || totalExamsSelected === 0 ? 'not-allowed' : 'pointer',
                    opacity: isLoading || totalExamsSelected === 0 ? 0.6 : 1,
                  }}
                >
                  {isLoading
                    ? '⏳ Đang khởi tạo...'
                    : totalExamsSelected === 0
                    ? 'Chưa có đề để biên soạn'
                    : `🚀 Bắt đầu biên soạn (${totalExamsSelected} đề)`}
                </button>
              </div>
            )}
          </div>
        </form>
      </div>

      {/* Cookie Import Modal */}
      {showCookieModal && (
        <div
          role="dialog"
          aria-modal="true"
          style={{
            position: 'fixed',
            inset: 0,
            backgroundColor: 'rgba(0, 0, 0, 0.55)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 9999,
            padding: '16px',
          }}
          onClick={() => setShowCookieModal(false)}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            style={{
              backgroundColor: 'var(--bg-surface)',
              border: '1px solid var(--border-strong)',
              borderRadius: 'var(--radius-md)',
              padding: '24px',
              maxWidth: '500px',
              width: '100%',
              boxShadow: 'var(--shadow-lg)',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '12px' }}>
              <h3 style={{ margin: 0, fontSize: '16px', fontWeight: 700 }}>
                Đăng nhập FUOverflow
              </h3>
              <div style={{ display: 'flex', gap: '4px', backgroundColor: 'var(--bg-subtle)', padding: '2px', borderRadius: 'var(--radius-sm)' }}>
                <button
                  type="button"
                  onClick={() => setLoginModalMode('account')}
                  style={{
                    padding: '3px 8px',
                    fontSize: '11px',
                    fontWeight: loginModalMode === 'account' ? 600 : 400,
                    backgroundColor: loginModalMode === 'account' ? 'var(--bg-surface)' : 'transparent',
                    border: 'none',
                    borderRadius: 'var(--radius-sm)',
                    cursor: 'pointer',
                    color: loginModalMode === 'account' ? 'var(--primary)' : 'var(--text-secondary)',
                    boxShadow: loginModalMode === 'account' ? '0 1px 2px rgba(0,0,0,0.1)' : 'none',
                  }}
                >
                  🔑 Tài khoản
                </button>
                <button
                  type="button"
                  onClick={() => setLoginModalMode('cookie')}
                  style={{
                    padding: '3px 8px',
                    fontSize: '11px',
                    fontWeight: loginModalMode === 'cookie' ? 600 : 400,
                    backgroundColor: loginModalMode === 'cookie' ? 'var(--bg-surface)' : 'transparent',
                    border: 'none',
                    borderRadius: 'var(--radius-sm)',
                    cursor: 'pointer',
                    color: loginModalMode === 'cookie' ? 'var(--primary)' : 'var(--text-secondary)',
                    boxShadow: loginModalMode === 'cookie' ? '0 1px 2px rgba(0,0,0,0.1)' : 'none',
                  }}
                >
                  🍪 Cookie (F12)
                </button>
              </div>
            </div>

            {loginModalMode === 'account' ? (
              /* Mode 1: Direct Account Login */
              <div>
                <p style={{ margin: '0 0 12px', fontSize: '12px', color: 'var(--text-secondary)' }}>
                  Hệ thống sẽ tự động chạy trình duyệt nền để đăng nhập vào FUOverflow và lưu phiên làm việc an toàn trên máy bạn.
                </p>

                <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', marginBottom: '12px' }}>
                  <div>
                    <label style={{ display: 'block', fontSize: '11px', fontWeight: 600, marginBottom: '4px', color: 'var(--text-secondary)' }}>
                      Tên tài khoản hoặc Email:
                    </label>
                    <input
                      type="text"
                      autoFocus
                      value={accountUsername}
                      onChange={(e) => setAccountUsername(e.target.value)}
                      placeholder="Nhập tên hoặc email"
                      style={{
                        width: '100%',
                        padding: '8px 10px',
                        fontSize: '12px',
                        backgroundColor: 'var(--bg-canvas)',
                        border: '1px solid var(--border-strong)',
                        borderRadius: 'var(--radius-sm)',
                        color: 'var(--text-primary)',
                        boxSizing: 'border-box',
                      }}
                    />
                  </div>

                  <div>
                    <label style={{ display: 'block', fontSize: '11px', fontWeight: 600, marginBottom: '4px', color: 'var(--text-secondary)' }}>
                      Mật khẩu:
                    </label>
                    <input
                      type="password"
                      value={accountPassword}
                      onChange={(e) => setAccountPassword(e.target.value)}
                      onKeyDown={(e) => { if (e.key === 'Enter') handleLoginWithAccount(); }}
                      placeholder="Nhập mật khẩu diễn đàn..."
                      style={{
                        width: '100%',
                        padding: '8px 10px',
                        fontSize: '12px',
                        backgroundColor: 'var(--bg-canvas)',
                        border: '1px solid var(--border-strong)',
                        borderRadius: 'var(--radius-sm)',
                        color: 'var(--text-primary)',
                        boxSizing: 'border-box',
                      }}
                    />
                  </div>
                </div>

                {accountError && (
                  <div style={{ color: 'var(--status-conflict-text)', fontSize: '12px', marginBottom: '10px', lineHeight: 1.4 }}>
                    ⚠️ {accountError}
                  </div>
                )}

                <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px', marginTop: '14px' }}>
                  <button
                    type="button"
                    onClick={() => { setShowCookieModal(false); setAccountError(null); }}
                    style={{
                      padding: '6px 12px',
                      backgroundColor: 'transparent',
                      border: '1px solid var(--border-subtle)',
                      borderRadius: 'var(--radius-sm)',
                      fontSize: '12px',
                      cursor: 'pointer',
                      color: 'var(--text-primary)',
                    }}
                  >
                    Đóng
                  </button>
                  <button
                    type="button"
                    onClick={handleLoginWithAccount}
                    disabled={isLoggingInAccount}
                    style={{
                      padding: '6px 16px',
                      backgroundColor: 'var(--primary)',
                      color: '#FFFFFF',
                      border: 'none',
                      borderRadius: 'var(--radius-sm)',
                      fontSize: '12px',
                      fontWeight: 600,
                      cursor: isLoggingInAccount ? 'not-allowed' : 'pointer',
                      opacity: isLoggingInAccount ? 0.7 : 1,
                    }}
                  >
                    {isLoggingInAccount ? '⏳ Đang đăng nhập...' : '🚀 Đăng nhập ngay'}
                  </button>
                </div>
              </div>
            ) : (
              /* Mode 2: Paste Cookie */
              <div>
                <p style={{ margin: '0 0 12px', fontSize: '12px', color: 'var(--text-secondary)' }}>
                  Dán cookie đã có từ trình duyệt (dành cho người không muốn nhập mật khẩu):
                </p>

                {/* Step-by-step guide */}
                <div
                  style={{
                    display: 'flex',
                    flexDirection: 'column',
                    gap: '6px',
                    marginBottom: '12px',
                    padding: '8px 10px',
                    backgroundColor: 'var(--bg-subtle)',
                    borderRadius: 'var(--radius-sm)',
                    border: '1px solid var(--border-subtle)',
                    fontSize: '11px',
                    lineHeight: 1.5,
                  }}
                >
                  <div><strong>1:</strong> Vào FUOverflow trong Chrome và đăng nhập.</div>
                  <div>
                    <strong>2:</strong> Nhấn <kbd style={{ padding: '1px 4px', border: '1px solid var(--border-strong)', borderRadius: '3px', fontSize: '10px' }}>F12</kbd> → <strong>Application</strong> → <strong>Cookies</strong> → <strong>fuoverflow.com</strong>
                  </div>
                  <div><strong>3:</strong> Copy giá trị <code>xf_user</code> và <code>xf_session</code> dán vào dưới:</div>
                </div>

                <input
                  type="password"
                  value={cookieInput}
                  onChange={(e) => setCookieInput(e.target.value)}
                  onKeyDown={(e) => { if (e.key === 'Enter') handleSaveCookie(); }}
                  placeholder="Dán xf_user=...; xf_session=... vào đây..."
                  style={{
                    width: '100%',
                    padding: '8px 10px',
                    fontFamily: 'var(--font-mono)',
                    fontSize: '12px',
                    backgroundColor: 'var(--bg-canvas)',
                    border: `1px solid ${cookieError ? 'var(--status-conflict-border)' : 'var(--border-strong)'}`,
                    borderRadius: 'var(--radius-sm)',
                    color: 'var(--text-primary)',
                    boxSizing: 'border-box',
                  }}
                />
                {cookieError && (
                  <div style={{ color: 'var(--status-conflict-text)', fontSize: '12px', marginTop: '6px', lineHeight: 1.4 }}>
                    ⚠️ {cookieError}
                  </div>
                )}
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '8px', marginTop: '14px' }}>
                  <a
                    href="https://fuoverflow.com/login/"
                    target="_blank"
                    rel="noopener noreferrer"
                    style={{ fontSize: '11px', color: 'var(--primary)', textDecoration: 'none' }}
                  >
                    🌐 Mở FUOverflow ↗
                  </a>
                  <div style={{ display: 'flex', gap: '8px' }}>
                    <button
                      type="button"
                      onClick={() => { setShowCookieModal(false); setCookieError(null); setCookieInput(''); }}
                      style={{
                        padding: '6px 12px',
                        backgroundColor: 'transparent',
                        border: '1px solid var(--border-subtle)',
                        borderRadius: 'var(--radius-sm)',
                        fontSize: '12px',
                        cursor: 'pointer',
                        color: 'var(--text-primary)',
                      }}
                    >
                      Đóng
                    </button>
                    <button
                      type="button"
                      onClick={handleSaveCookie}
                      disabled={isSavingCookie}
                      style={{
                        padding: '6px 16px',
                        backgroundColor: 'var(--primary)',
                        color: '#FFFFFF',
                        border: 'none',
                        borderRadius: 'var(--radius-sm)',
                        fontSize: '12px',
                        fontWeight: 600,
                        cursor: isSavingCookie ? 'not-allowed' : 'pointer',
                        opacity: isSavingCookie ? 0.7 : 1,
                      }}
                    >
                      {isSavingCookie ? '⏳ Đang kiểm tra...' : '✅ Lưu & Xác thực'}
                    </button>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};
