import React, { useEffect, useState, useRef, useMemo } from 'react';
import type { Subject, ExamItem, SubjectExamTypesResponse } from '../types';
import {
  ArrowRightIcon,
  BookIcon,
  CheckIcon,
  CookieIcon,
  CrossIcon,
  FileTextIcon,
  FolderIcon,
  GlobeIcon,
  RefreshIcon,
  SearchIcon,
  UserIcon,
  WarningIcon,
} from './icons';

interface Props {
  onStartJob: (
    subjectCode: string,
    examType: 'FE' | 'PE',
    limit: number,
    examIds?: number[],
    examTitles?: Record<string, string>
  ) => void;
  isLoading: boolean;
  initialOpenLogin?: boolean;
  loginTrigger?: number;
  isLoggedIn?: boolean;
  forumLoggedIn?: boolean;
  platform?: 'fuoverflow' | 'fuexam';
}

export const ScreenSelectSubject: React.FC<Props> = ({
  onStartJob,
  isLoading,
  initialOpenLogin,
  loginTrigger,
  isLoggedIn = true,
  forumLoggedIn: propForumLoggedIn,
  platform = 'fuoverflow',
}) => {
  // Single source of truth for forum auth state
  const forumLoggedIn = Boolean(propForumLoggedIn !== undefined ? propForumLoggedIn : isLoggedIn);
  const [manualLoggedIn, setManualLoggedIn] = useState<boolean>(false);
  const effectiveLoggedIn = forumLoggedIn || manualLoggedIn;

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
  const [subjectTypesMap, setSubjectTypesMap] = useState<Record<string, SubjectExamTypesResponse & { fallback?: boolean }>>({});

  // Modal statuses
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
  const [crawlConfig, setCrawlConfig] = useState<{
    fuexam_min_delay_seconds?: number;
    fuexam_max_concurrency?: number;
    delay_seconds?: [number, number];
    concurrency?: number;
  }>({});

  useEffect(() => {
    fetch('/api/settings')
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (data?.crawl) {
          setCrawlConfig(data.crawl);
        }
      })
      .catch(() => {});
  }, []);

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

  // Open modal when header login button or URL trigger is clicked
  useEffect(() => {
    if (loginTrigger && loginTrigger > 0 && !effectiveLoggedIn) {
      setShowCookieModal(true);
      setLoginModalMode('account');
    }
  }, [loginTrigger, effectiveLoggedIn]);

  // Debounce search query 250ms
  useEffect(() => {
    const handler = setTimeout(() => {
      setDebouncedQuery(searchQuery.trim());
    }, 250);
    return () => clearTimeout(handler);
  }, [searchQuery]);

  // Fetch subjects list when debouncedQuery or platform changes
  useEffect(() => {
    setIsSearching(true);
    setLookupMessage(null);
    const url = debouncedQuery
      ? `/api/subjects?platform=${platform}&q=${encodeURIComponent(debouncedQuery)}&limit=350`
      : `/api/subjects?platform=${platform}&limit=350`;

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
  }, [debouncedQuery, platform]);

  // Fetch available exam types (FE, RE, PE, B5) for active and selected subjects
  useEffect(() => {
    const codes = Array.from(new Set([...(activeCode ? [activeCode] : []), ...selectedCodes]));
    codes.forEach((code) => {
      const cacheKey = `${platform}:${code}`;
      if (subjectTypesMap[cacheKey]) return;
      fetch(`/api/subjects/${code}/exam-types?platform=${platform}`)
        .then((res) => {
          if (!res.ok) throw new Error(`HTTP ${res.status}`);
          return res.json();
        })
        .then((data: SubjectExamTypesResponse) => {
          setSubjectTypesMap((prev) => ({ ...prev, [cacheKey]: data }));
        })
        .catch(() => {
          // Fallback for mocked tests that only stub /exams without /exam-types
          setSubjectTypesMap((prev) => ({
            ...prev,
            [cacheKey]: {
              subject_code: code,
              platform,
              available_types: ['FE'],
              has_fe: true,
              has_pe: false,
              counts: { FE: 0, RE: 0, PE: 0, B5: 0 },
              fallback: true,
            },
          }));
        });
    });
  }, [activeCode, selectedCodes, platform, subjectTypesMap]);

  const codesForPeCheck = useMemo(() => {
    const set = new Set<string>();
    selectedCodes.forEach((c) => set.add(c));
    if (activeCode) set.add(activeCode);
    return Array.from(set);
  }, [selectedCodes, activeCode]);

  const showPeButton = useMemo(() => {
    if (codesForPeCheck.length === 0) return false;
    return codesForPeCheck.some((code) => Boolean(subjectTypesMap[`${platform}:${code}`]?.has_pe));
  }, [codesForPeCheck, subjectTypesMap, platform]);

  const activeHasPe = useMemo(() => {
    if (!activeCode) return false;
    return Boolean(subjectTypesMap[`${platform}:${activeCode}`]?.has_pe);
  }, [activeCode, subjectTypesMap, platform]);

  // Auto-select FE when only FE is available
  useEffect(() => {
    if (!showPeButton && examType === 'PE') {
      setExamType('FE');
    }
  }, [showPeButton, examType]);

  // Reset selected exam IDs when switching exam type or platform so counts never leak across types
  useEffect(() => {
    setSelectedExamIds({});
  }, [examType, platform]);

  // Fetch exams for activeCode
  useEffect(() => {
    if (!activeCode) {
      setExams([]);
      return;
    }
    setIsLoadingExams(true);
    fetch(`/api/subjects/${activeCode}/exams?platform=${platform}&type=${examType}`)
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((data: ExamItem[]) => {
        const list = data || [];
        setExams(list);

        // If /exam-types fell back (e.g. test mock without /exam-types), infer PE presence from payload
        const cacheKey = `${platform}:${activeCode}`;
        setSubjectTypesMap((prev) => {
          const cur = prev[cacheKey];
          if (cur?.fallback) {
            const hasPeInList = list.some((e) => (e.exam_type || '').toUpperCase() === 'PE');
            if (hasPeInList && !cur.has_pe) {
              return {
                ...prev,
                [cacheKey]: {
                  ...cur,
                  has_pe: true,
                  available_types: Array.from(new Set([...cur.available_types, 'PE'])),
                },
              };
            }
          }
          return prev;
        });

        const isFuexamPe = platform === 'fuexam' && examType === 'PE';
        const filteredForType = list.filter((e) => {
          const eType = (e.exam_type || 'FE').toUpperCase();
          if (examType === 'FE') {
            return eType !== 'PE' && e.is_valid_exam !== false;
          }
          return eType === 'PE' && e.is_valid_exam !== false;
        });
        const selectable = isFuexamPe ? [] : filteredForType;
        const count = selectable.length;
        let targetLimit = 1;
        if (count >= 4) {
          targetLimit = 4;
        } else if (count > 0) {
          targetLimit = count;
        } else {
          targetLimit = 1;
        }
        setLimit(targetLimit);

        // Auto select top targetLimit valid exams only
        const defaultSelected = count > 0 ? selectable.slice(0, targetLimit).map((e) => e.id) : [];
        setSelectedExamIds((prev) => ({ ...prev, [activeCode]: defaultSelected }));
      })
      .catch((err) => {
        console.error(`Failed to load exams for ${activeCode}:`, err);
        setExams([]);
      })
      .finally(() => {
        setIsLoadingExams(false);
      });
  }, [activeCode, examType, platform]);

  // Sync cookie modal state with login status from Extension
  useEffect(() => {
    if (isLoggedIn) {
      setShowCookieModal(false);
    }
  }, [isLoggedIn]);

  // Handle sync subjects button
  const handleSyncSubjects = async () => {
    setIsSyncing(true);
    setSyncMessage(null);
    try {
      const res = await fetch(`/api/subjects/sync?platform=${platform}`, { method: 'POST' });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setSyncMessage(`Đã cập nhật danh sách môn: ${data.total} môn (thêm ${data.added}, cập nhật ${data.updated}).`);
      if (data.last_synced_at) setLastSyncedAt(data.last_synced_at);
      // Refresh list
      const ref = await fetch(`/api/subjects?platform=${platform}&limit=100`);
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
        setManualLoggedIn(true);
        setShowCookieModal(false);
        setAccountPassword('');
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
        setManualLoggedIn(true);
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

  // Filtered visible and selectable exams according to selected examType
  const isFuexamPeUnsupported = platform === 'fuexam' && examType === 'PE';

  const visibleExams = useMemo(() => {
    if (isFuexamPeUnsupported) {
      return [];
    }
    return exams.filter((e) => {
      const eType = (e.exam_type || 'FE').toUpperCase();
      if (examType === 'FE') {
        return eType !== 'PE' && e.is_valid_exam !== false;
      }
      return eType === 'PE' && e.is_valid_exam !== false;
    });
  }, [exams, examType, isFuexamPeUnsupported]);

  const selectableExams = useMemo(
    () => visibleExams.filter((e) => e.is_valid_exam !== false),
    [visibleExams]
  );

  // Calculate summary counts (never count filtered or unsupported exams)
  const totalExamsSelected = isFuexamPeUnsupported
    ? 0
    : selectedCodes.reduce((sum, code) => {
        const chosen = selectedExamIds[code]?.length;
        if (chosen !== undefined) {
          return sum + chosen;
        }
        const typeInfo = subjectTypesMap[`${platform}:${code}`];
        const availCount = typeInfo?.counts?.[examType] ?? 0;
        return sum + Math.min(limit, availCount);
      }, 0);

  const isSubmittingRef = useRef<boolean>(false);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (isLoading || isSubmittingRef.current) return;
    if (selectedCodes.length === 0 || totalExamsSelected === 0) return;

    isSubmittingRef.current = true;
    setTimeout(() => {
      isSubmittingRef.current = false;
    }, 1200);

    const activeSubj = selectedCodes[0];
    const chosenIds = selectedExamIds[activeSubj];
    const examIds = chosenIds && chosenIds.length > 0 ? chosenIds : undefined;
    const examTitles: Record<string, string> = {};
    if (chosenIds && exams) {
      for (const tid of chosenIds) {
        const found = exams.find((e) => e.id === tid);
        if (found && found.title) {
          examTitles[String(tid)] = found.title;
        }
      }
    }
    // Launch for first/active subject or batch
    onStartJob(activeSubj, examType, limit, examIds, Object.keys(examTitles).length > 0 ? examTitles : undefined);
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

  const cleanSubjects = subjects.filter(
    (s) => s.code.toUpperCase() !== 'RSS' && s.name.toUpperCase() !== 'RSS' && s.code !== '-'
  );

  const displayedSubjects = filterSelectedOnly
    ? cleanSubjects.filter((s) => selectedCodes.includes(s.code))
    : cleanSubjects;

  return (
    <div className="select-subject-layout">
      {/* Left Column: Subjects and Exams List */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-5)' }}>
        {/* Card: Danh sách môn học */}
        <div className="card-paper">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 'var(--space-4)', flexWrap: 'wrap', gap: 'var(--space-3)' }}>
            <div>
              <h2 className="serif-title" style={{ fontSize: 'var(--text-2xl)', marginBottom: 'var(--space-1)', display: 'flex', alignItems: 'center' }}>
                <span className="step-badge">1</span> Chọn môn học cần biên soạn{' '}
                <span
                  style={{
                    fontSize: '12px',
                    fontWeight: 600,
                    marginLeft: '8px',
                    color: platform === 'fuexam' ? '#b45309' : 'var(--primary)',
                  }}
                >
                  [{platform === 'fuexam' ? 'fuexam' : 'FUOverflow'}]
                </span>
              </h2>
              <p style={{ color: 'var(--text-secondary)', fontSize: 'var(--text-sm)' }}>
                {platform === 'fuexam'
                  ? 'Dữ liệu 292 môn học từ fuexam.me. Chọn môn để quét đề thi trắc nghiệm.'
                  : 'Dữ liệu tổng hợp từ diễn đàn FUOverflow. Chọn môn để quét danh sách đề do sinh viên đăng trên diễn đàn.'}
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
                <RefreshIcon size={14} className={isSyncing ? 'spin' : ''} />
                <span>{isSyncing ? 'Đang cập nhật...' : 'Cập nhật danh sách môn'}</span>
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
              <span
                data-testid="subject-filter-count-label"
                style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: '11px',
                  fontWeight: 600,
                  color: 'var(--text-secondary)',
                  padding: '2px 8px',
                  backgroundColor: 'var(--bg-subtle)',
                  border: '1px solid var(--border-subtle)',
                  borderRadius: 'var(--radius-sm)',
                }}
              >
                {displayedSubjects.length} / 292 môn
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
                  display: 'inline-flex',
                  alignItems: 'center',
                }}
              >
                <CrossIcon size={12} />
              </button>
            )}
            {isSearching && (
              <span
                style={{
                  position: 'absolute',
                  right: '12px',
                  top: '50%',
                  transform: 'translateY(-50%)',
                  display: 'inline-flex',
                  alignItems: 'center',
                  color: 'var(--text-muted)',
                }}
              >
                <RefreshIcon size={13} className="spin" />
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
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: '6px',
                    }}
                  >
                    {isLookingUp ? (
                      'Đang tìm kiếm...'
                    ) : (
                      <>
                        <SearchIcon size={13} />
                        <span>Thử tìm mã "{searchQuery.trim()}" trên diễn đàn</span>
                      </>
                    )}
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
                    data-testid={`subject-row-${subject.code}`}
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
                        data-testid={`checkbox-subject-${subject.code}`}
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
                      <span style={{ fontSize: 'var(--text-sm)', color: 'var(--text-secondary)' }}>
                        {subject.name && subject.name.trim().toUpperCase() !== subject.code.trim().toUpperCase() ? subject.name : ''}
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
              <div style={{ marginBottom: '8px', display: 'flex', justifyContent: 'center' }}>
                <FolderIcon size={32} />
              </div>
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
                  Danh sách đề {examType} của môn {activeCode}{' '}
                  <span
                    style={{
                      fontSize: '12px',
                      fontWeight: 600,
                      color: platform === 'fuexam' ? '#b45309' : 'var(--primary)',
                    }}
                  >
                    [{platform === 'fuexam' ? 'fuexam' : 'FUOverflow'}]
                  </span>
                </h3>
                <p style={{ fontSize: 'var(--text-xs)', color: 'var(--text-secondary)' }}>
                  {platform === 'fuexam'
                    ? 'Đề thực tế được đồng bộ từ ngân hàng fuexam.me. Tích chọn các đề bạn muốn biên soạn.'
                    : 'Đề thực tế được đồng bộ từ diễn đàn FUOverflow. Tích chọn các đề bạn muốn biên soạn.'}
                </p>
              </div>

              {selectableExams.length > 0 && selectableExams.length < limit && (
                <div
                  style={{
                    padding: '4px 8px',
                    backgroundColor: 'var(--status-weak-bg)',
                    border: '1px solid var(--status-weak-border)',
                    borderRadius: 'var(--radius-sm)',
                    fontSize: '11px',
                    color: 'var(--status-weak-text)',
                    fontWeight: 600,
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: '4px',
                  }}
                >
                  <WarningIcon size={13} />
                  <span>Môn này chỉ có {selectableExams.length} đề {examType}</span>
                </div>
              )}
            </div>

            {isLoadingExams ? (
              <div style={{ padding: 'var(--space-4)', textAlign: 'center', color: 'var(--text-muted)', fontSize: 'var(--text-xs)' }}>
                Đang quét danh sách đề từ {platform === 'fuexam' ? 'fuexam.me' : 'diễn đàn'}...
              </div>
            ) : isFuexamPeUnsupported ? (
              <div
                data-testid="fuexam-pe-unsupported-notice"
                style={{
                  padding: 'var(--space-4)',
                  textAlign: 'center',
                  color: 'var(--text-secondary)',
                  fontSize: 'var(--text-xs)',
                  backgroundColor: 'var(--bg-subtle)',
                  border: '1px solid var(--border-subtle)',
                  borderRadius: 'var(--radius-sm)',
                }}
              >
                {activeHasPe
                  ? 'Nền tảng fuexam.me hiện chưa hỗ trợ tải và soạn đề PE (Thực hành).'
                  : `Môn ${activeCode} không có đề PE trên fuexam.me.`}
              </div>
            ) : visibleExams.length === 0 ? (
              <div style={{ padding: 'var(--space-4)', textAlign: 'center', color: 'var(--text-muted)', fontSize: 'var(--text-xs)' }}>
                Chưa tìm thấy đề {examType} nào cho môn {activeCode} trên {platform === 'fuexam' ? 'fuexam.me' : 'diễn đàn'}.
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
                {visibleExams.map((exam, index) => {
                  const isExamSelected = (selectedExamIds[activeCode] || []).includes(exam.id);
                  const isInvalid = exam.is_valid_exam === false;
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
                        cursor: isInvalid ? 'not-allowed' : 'pointer',
                        opacity: isInvalid ? 0.65 : 1,
                        fontSize: 'var(--text-sm)',
                      }}
                    >
                      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', flexWrap: 'wrap' }}>
                        <input
                          type="checkbox"
                          value={String(exam.id)}
                          data-testid={`checkbox-exam-${exam.id}`}
                          checked={isExamSelected && !isInvalid}
                          disabled={isInvalid}
                          onChange={() => {
                            if (!isInvalid) toggleExam(activeCode, exam.id);
                          }}
                          style={{ accentColor: 'var(--primary)', cursor: isInvalid ? 'not-allowed' : 'pointer' }}
                        />
                        <span style={{ fontWeight: 600, color: 'var(--text-primary)' }}>
                          #{index + 1} {exam.title}
                        </span>
                        {exam.warning && (
                          <span
                            data-testid={`warning-badge-${exam.id}`}
                            style={{
                              fontSize: '11px',
                              fontWeight: 600,
                              color: isInvalid ? '#b91c1c' : '#b45309',
                              backgroundColor: isInvalid ? 'rgba(239, 68, 68, 0.08)' : 'rgba(217, 119, 6, 0.08)',
                              border: `1px solid ${isInvalid ? 'rgba(239, 68, 68, 0.25)' : 'rgba(217, 119, 6, 0.25)'}`,
                              padding: '1px 6px',
                              borderRadius: '3px',
                            }}
                          >
                            {exam.warning}
                          </span>
                        )}
                      </div>

                      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)', fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>
                        {exam.term && (
                          <span style={{ fontFamily: 'var(--font-mono)', padding: '1px 4px', backgroundColor: 'var(--bg-surface)', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-sm)' }}>
                            {exam.term}
                          </span>
                        )}
                        {exam.question_count && exam.question_count > 0 ? (
                          <span>{exam.question_count} câu</span>
                        ) : (
                          <span style={{ fontStyle: 'italic', opacity: 0.75 }}>Số câu chưa rõ</span>
                        )}
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
            <div style={{ display: 'grid', gridTemplateColumns: showPeButton ? '1fr 1fr' : '1fr', gap: 'var(--space-2)' }}>
              <button
                type="button"
                data-testid="btn-exam-type-fe"
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
              {showPeButton && (
                <button
                  type="button"
                  data-testid="btn-exam-type-pe"
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
                    {platform === 'fuexam' ? 'Chưa hỗ trợ trên fuexam' : 'Tải file .pdf / .zip gốc'}
                  </div>
                </button>
              )}
            </div>
          </div>

          {/* PE Guidance Note (only when PE is available & selected) */}
          {showPeButton && examType === 'PE' && (
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
              <div style={{ fontWeight: 700, color: 'var(--text-primary)', marginBottom: '4px', display: 'flex', alignItems: 'center', gap: '6px' }}>
                <BookIcon size={14} />
                <span>{platform === 'fuexam' ? 'Trạng thái đề PE trên fuexam.me' : 'Quy tắc tải đề PE (Thực hành)'}</span>
              </div>
              {platform === 'fuexam'
                ? 'Nền tảng fuexam.me hiện chưa hỗ trợ tải và biên soạn đề PE (Thực hành).'
                : 'Đề PE là bài thi thực hành lập trình. DocxStacked chỉ tải trực tiếp tệp đề bài gốc (.pdf) và mã nguồn mẫu (.zip) về thư mục lưu trữ, không có ảnh từng câu, không gọi AI và không tạo tệp .docx.'}
            </div>
          )}

          {/* Limit Number Selector (adaptive to selectableExams.length) */}
          {(() => {
            const maxAvailable = selectableExams.length;
            const isLocked = maxAvailable <= 1;
            const canDecrease = !isLocked && limit > 1;
            const canIncrease = !isLocked && limit < Math.min(20, maxAvailable);

              const handleDecrease = () => {
                if (canDecrease) {
                  const next = limit - 1;
                  setLimit(next);
                  // Uncheck from bottom up: keep first `next` checked items in order of selectableExams list
                  const currentSelected = selectedExamIds[activeCode] || [];
                  const orderedSelected = selectableExams.filter((e) => currentSelected.includes(e.id)).map((e) => e.id);
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
                  const unselected = selectableExams.filter((e) => !currentSelected.includes(e.id));
                  const nextExam = unselected[0];
                  const nextSelected = nextExam
                    ? [...currentSelected, nextExam.id]
                    : selectableExams.slice(0, next).map((e) => e.id);
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
                  [activeCode]: selectableExams.slice(0, clamped).map((item) => item.id),
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
            })()}

          {/* Step 3: Tóm tắt kế hoạch & Bắt đầu */}
          <div style={{ marginTop: 'var(--space-4)', borderTop: '1px solid var(--border-subtle)', paddingTop: 'var(--space-4)' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 'var(--space-2)' }}>
              <h4 className="serif-title" style={{ fontSize: 'var(--text-base)', margin: 0, display: 'flex', alignItems: 'center' }}>
                <span className="step-badge">3</span> Kế hoạch & Bắt đầu
              </h4>
              {effectiveLoggedIn ? (
                <span style={{ fontSize: '11px', color: 'var(--status-confident-text)', fontWeight: 600, display: 'inline-flex', alignItems: 'center', gap: '4px' }}>
                  <span style={{ width: 8, height: 8, borderRadius: '50%', backgroundColor: '#2D6A4F', display: 'inline-block' }} />
                  <span>Đã kết nối {platform === 'fuexam' ? 'fuexam.me' : 'FUOverflow'}</span>
                </span>
              ) : (
                <span style={{ fontSize: '11px', color: 'var(--text-muted)', fontWeight: 500 }}>
                  Chưa kết nối phiên
                </span>
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
              <div style={{ fontWeight: 600, color: 'var(--text-primary)', marginBottom: '2px', display: 'flex', alignItems: 'center', gap: '6px' }}>
                <FileTextIcon size={14} />
                <span>
                  {selectedCodes.length} môn · {totalExamsSelected} đề {examType}
                  {examType === 'FE'
                    ? ` · tạo ${totalExamsSelected} file .docx`
                    : platform === 'fuexam'
                      ? ' · chưa hỗ trợ trên fuexam'
                      : ` · tải ${totalExamsSelected} file .pdf / .zip gốc`}
                </span>
              </div>
              <div style={{ color: 'var(--text-secondary)' }}>
                {selectedCodes.length > 0 ? `Đang chọn: ${selectedCodes.join(', ')}` : 'Chưa chọn môn học nào'}
              </div>
              {totalExamsSelected > 5 && (() => {
                const isFue = platform === 'fuexam';
                const delaySec = isFue
                  ? (crawlConfig.fuexam_min_delay_seconds ?? 0.4)
                  : (((crawlConfig.delay_seconds?.[0] ?? 1.5) + (crawlConfig.delay_seconds?.[1] ?? 4.0)) / 2);
                const conc = isFue ? (crawlConfig.fuexam_max_concurrency ?? 2) : (crawlConfig.concurrency ?? 1);
                const reqsPerExam = isFue ? 90 : 45;
                const estSeconds = (totalExamsSelected * reqsPerExam * (delaySec + 0.3)) / Math.max(1, conc);
                const estMinutes = Math.max(1, Math.round(estSeconds / 60));
                return (
                  <div
                    data-testid="estimated-duration"
                    style={{
                      marginTop: '6px',
                      padding: '4px 8px',
                      backgroundColor: 'rgba(37, 99, 235, 0.06)',
                      border: '1px solid rgba(37, 99, 235, 0.2)',
                      borderRadius: 'var(--radius-sm)',
                      color: 'var(--text-primary)',
                      fontSize: '11px',
                      fontWeight: 500,
                    }}
                  >
                    ⏱ Ước tính thời gian: <strong>~{estMinutes} phút</strong> ({totalExamsSelected} đề · giãn cách {delaySec}s · {conc} luồng)
                  </div>
                );
              })()}
              {selectableExams.length > 0 && selectableExams.length < limit && (
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
                    display: 'flex',
                    alignItems: 'center',
                    gap: '4px',
                  }}
                >
                  <WarningIcon size={12} />
                  <span>Môn {activeCode} chỉ có {selectableExams.length} đề (yêu cầu {limit} đề).</span>
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
            ) : !effectiveLoggedIn ? (
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
                  Cần phiên đăng nhập để biên soạn
                </button>
                <div style={{ fontSize: '11px', color: 'var(--text-muted)', textAlign: 'center', marginTop: '6px' }}>
                  Vui lòng đăng nhập phiên {platform === 'fuexam' ? 'fuexam.me' : 'FUOverflow'} để tiếp tục
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
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    gap: '8px',
                  }}
                >
                  {isLoading ? (
                    <>
                      <RefreshIcon size={16} className="spin" />
                      <span>Đang khởi tạo...</span>
                    </>
                  ) : totalExamsSelected === 0 ? (
                    'Chưa có đề để biên soạn'
                  ) : (
                    <>
                      <ArrowRightIcon size={16} />
                      <span>
                        {examType === 'FE'
                          ? `Bắt đầu soạn đề (${totalExamsSelected} đề)`
                          : `Bắt đầu tải đề PE (${totalExamsSelected} đề)`}
                      </span>
                    </>
                  )}
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
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: '4px',
                  }}
                >
                  <UserIcon size={12} />
                  <span>Tài khoản</span>
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
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: '4px',
                  }}
                >
                  <CookieIcon size={12} />
                  <span>Cookie (F12)</span>
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
                  <div style={{ color: 'var(--status-conflict-text)', fontSize: '12px', marginBottom: '10px', lineHeight: 1.4, display: 'flex', alignItems: 'center', gap: '6px' }}>
                    <WarningIcon size={13} />
                    <span>{accountError}</span>
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
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: '6px',
                    }}
                  >
                    {isLoggingInAccount ? (
                      <>
                        <RefreshIcon size={13} className="spin" />
                        <span>Đang đăng nhập...</span>
                      </>
                    ) : (
                      <>
                        <ArrowRightIcon size={14} />
                        <span>Đăng nhập ngay</span>
                      </>
                    )}
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
                  <div style={{ color: 'var(--status-conflict-text)', fontSize: '12px', marginTop: '6px', lineHeight: 1.4, display: 'flex', alignItems: 'center', gap: '6px' }}>
                    <WarningIcon size={13} />
                    <span>{cookieError}</span>
                  </div>
                )}
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '8px', marginTop: '14px' }}>
                  <a
                    href="https://fuoverflow.com/login/"
                    target="_blank"
                    rel="noopener noreferrer"
                    style={{ fontSize: '11px', color: 'var(--primary)', textDecoration: 'none', display: 'inline-flex', alignItems: 'center', gap: '4px' }}
                  >
                    <GlobeIcon size={13} />
                    <span>Mở trang FUOverflow</span>
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
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: '6px',
                      }}
                    >
                      {isSavingCookie ? (
                        <>
                          <RefreshIcon size={13} className="spin" />
                          <span>Đang kiểm tra...</span>
                        </>
                      ) : (
                        <>
                          <CheckIcon size={14} />
                          <span>Lưu & Xác thực</span>
                        </>
                      )}
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
