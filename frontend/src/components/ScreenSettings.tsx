import React, { useEffect, useState, useMemo } from 'react';
import type { AppSettings, AIProviderSetting } from '../types';

interface ScreenSettingsProps {
  onBack: () => void;
}

const PROVIDER_TEMPLATES: Record<string, { label: string; template: AIProviderSetting }> = {
  anthropic: {
    label: 'Anthropic (Claude 3.5)',
    template: {
      name: 'anthropic',
      model: 'claude-3-5-haiku-20241022',
      api_key_env: 'ANTHROPIC_API_KEY',
      base_url: null,
      enabled: true,
    },
  },
  gemini: {
    label: 'Google Gemini (2.5 Flash)',
    template: {
      name: 'gemini',
      model: 'gemini-2.5-flash',
      api_key_env: 'GEMINI_API_KEY',
      base_url: null,
      enabled: true,
    },
  },
  openai: {
    label: 'OpenAI (GPT-4o Mini)',
    template: {
      name: 'openai',
      model: 'gpt-4o-mini',
      api_key_env: 'OPENAI_API_KEY',
      base_url: 'https://api.openai.com/v1',
      enabled: true,
    },
  },
  openrouter: {
    label: 'OpenRouter (Đa mô hình)',
    template: {
      name: 'openrouter',
      model: 'anthropic/claude-3.5-haiku',
      api_key_env: 'OPENROUTER_API_KEY',
      base_url: 'https://openrouter.ai/api/v1',
      enabled: true,
    },
  },
  groq: {
    label: 'Groq (Llama 3.2 Vision)',
    template: {
      name: 'groq',
      model: 'llama-3.2-11b-vision-preview',
      api_key_env: 'GROQ_API_KEY',
      base_url: 'https://api.groq.com/openai/v1',
      enabled: true,
    },
  },
  ollama: {
    label: 'Ollama (Chạy offline nội bộ)',
    template: {
      name: 'ollama',
      model: 'llama3.2-vision',
      api_key_env: 'OLLAMA_API_KEY',
      base_url: 'http://localhost:11434/v1',
      enabled: true,
    },
  },
  custom: {
    label: 'Tùy chỉnh (OpenAI-compatible)',
    template: {
      name: 'custom_ai',
      model: '',
      api_key_env: 'CUSTOM_AI_API_KEY',
      base_url: '',
      enabled: true,
    },
  },
};

export const ScreenSettings: React.FC<ScreenSettingsProps> = ({ onBack }) => {
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [initialSettingsJson, setInitialSettingsJson] = useState<string>('');
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [isSaving, setIsSaving] = useState<boolean>(false);
  const [notification, setNotification] = useState<{ type: 'success' | 'error'; message: string } | null>(null);

  // Per-provider testing status
  const [testingStatus, setTestingStatus] = useState<Record<string, { loading: boolean; message?: string; success?: boolean }>>({});

  // Local write-only API key state for inputs
  const [apiKeysInput, setApiKeysInput] = useState<Record<string, string>>({});

  // Dynamic models cache per provider
  const [availableModels, setAvailableModels] = useState<Record<string, Array<{ id: string; name: string }>>>({});
  const [loadingModels, setLoadingModels] = useState<Record<string, boolean>>({});

  // Template dropdown selector
  const [selectedTemplateKey, setSelectedTemplateKey] = useState<string>('openrouter');

  // Navigation tab: 'basic' | 'ai' | 'advanced'
  const [activeSection, setActiveSection] = useState<'basic' | 'ai' | 'advanced'>('basic');

  useEffect(() => {
    fetchSettings();
  }, []);

  const fetchSettings = async () => {
    setIsLoading(true);
    setNotification(null);
    try {
      const resp = await fetch('/api/settings');
      if (!resp.ok) {
        throw new Error(`Tải cài đặt thất bại: HTTP ${resp.status}`);
      }
      const data: AppSettings = await resp.json();
      setSettings(data);
      setInitialSettingsJson(JSON.stringify(data));
      // Pre-fetch models for existing providers
      data.ai?.providers?.forEach((p) => {
        fetchProviderModels(p.name);
      });
    } catch (err: any) {
      setNotification({ type: 'error', message: err.message || 'Không thể kết nối máy chủ API' });
    } finally {
      setIsLoading(false);
    }
  };

  const fetchProviderModels = async (providerName: string, force = false) => {
    if (!force && availableModels[providerName]) return;
    setLoadingModels((prev) => ({ ...prev, [providerName]: true }));
    try {
      const resp = await fetch(`/api/settings/providers/${encodeURIComponent(providerName)}/models`);
      if (resp.ok) {
        const data = await resp.json();
        setAvailableModels((prev) => ({ ...prev, [providerName]: data.models || [] }));
      }
    } catch (err) {
      console.debug(`Failed to fetch models for ${providerName}:`, err);
    } finally {
      setLoadingModels((prev) => ({ ...prev, [providerName]: false }));
    }
  };

  // Detect unsaved changes
  const hasUnsavedChanges = useMemo(() => {
    if (!settings || !initialSettingsJson) return false;
    const settingsChanged = JSON.stringify(settings) !== initialSettingsJson;
    const keysEntered = Object.values(apiKeysInput).some((k) => k && k.trim().length > 0);
    return settingsChanged || keysEntered;
  }, [settings, initialSettingsJson, apiKeysInput]);

  // Window beforeunload warning
  useEffect(() => {
    const handleBeforeUnload = (e: BeforeUnloadEvent) => {
      if (hasUnsavedChanges) {
        e.preventDefault();
        e.returnValue = 'Bạn có thay đổi chưa lưu. Bạn có chắc muốn rời đi?';
      }
    };
    window.addEventListener('beforeunload', handleBeforeUnload);
    return () => window.removeEventListener('beforeunload', handleBeforeUnload);
  }, [hasUnsavedChanges]);

  const handleSave = async () => {
    if (!settings) return;
    setIsSaving(true);
    setNotification(null);

    // Prepare payload with any newly entered API keys
    const payload = JSON.parse(JSON.stringify(settings));
    if (payload.ai && payload.ai.providers) {
      payload.ai.providers = payload.ai.providers.map((p: AIProviderSetting) => {
        const enteredKey = apiKeysInput[p.name];
        if (enteredKey && enteredKey.trim().length > 0) {
          return { ...p, api_key: enteredKey.trim() };
        }
        return p;
      });
    }

    try {
      const resp = await fetch('/api/settings', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });

      if (!resp.ok) {
        const errorData = await resp.json().catch(() => ({}));
        throw new Error(errorData.detail || `Lưu thất bại: HTTP ${resp.status}`);
      }

      const updatedData: AppSettings = await resp.json();
      setSettings(updatedData);
      setInitialSettingsJson(JSON.stringify(updatedData));
      setApiKeysInput({}); // Clear write-only inputs after successful save
      setNotification({ type: 'success', message: 'Đã lưu cấu hình thành công! Cài đặt có hiệu lực ngay lập tức cho các job mới.' });
    } catch (err: any) {
      setNotification({ type: 'error', message: err.message || 'Lỗi khi lưu cài đặt' });
    } finally {
      setIsSaving(false);
    }
  };

  const handleDiscardChanges = () => {
    if (!initialSettingsJson) return;
    setSettings(JSON.parse(initialSettingsJson));
    setApiKeysInput({});
    setNotification(null);
  };

  const handleReset = async () => {
    if (!window.confirm('Bạn có chắc muốn đặt lại toàn bộ cài đặt về mặc định từ config.yaml?')) {
      return;
    }
    setIsSaving(true);
    setNotification(null);
    try {
      const resp = await fetch('/api/settings/reset', { method: 'POST' });
      if (!resp.ok) {
        throw new Error('Đặt lại thất bại');
      }
      const defaultData: AppSettings = await resp.json();
      setSettings(defaultData);
      setInitialSettingsJson(JSON.stringify(defaultData));
      setApiKeysInput({});
      setNotification({ type: 'success', message: 'Đã khôi phục cài đặt mặc định thành công.' });
    } catch (err: any) {
      setNotification({ type: 'error', message: err.message || 'Lỗi khi đặt lại cài đặt' });
    } finally {
      setIsSaving(false);
    }
  };

  const handleTestConnection = async (provider: AIProviderSetting) => {
    setTestingStatus((prev) => ({ ...prev, [provider.name]: { loading: true } }));
    try {
      const enteredKey = apiKeysInput[provider.name];
      const bodyPayload: any = {
        model: provider.model,
        api_key_env: provider.api_key_env,
        base_url: provider.base_url,
      };
      if (enteredKey && enteredKey.trim().length > 0) {
        bodyPayload.api_key = enteredKey.trim();
      }

      const resp = await fetch(`/api/settings/test-connection/${encodeURIComponent(provider.name)}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(bodyPayload),
      });
      const data = await resp.json();
      setTestingStatus((prev) => ({
        ...prev,
        [provider.name]: {
          loading: false,
          success: data.success,
          message: data.message,
        },
      }));
    } catch (err: any) {
      setTestingStatus((prev) => ({
        ...prev,
        [provider.name]: {
          loading: false,
          success: false,
          message: err.message || 'Lỗi kết nối tới endpoint test',
        },
      }));
    }
  };

  const moveProvider = (index: number, direction: 'up' | 'down') => {
    if (!settings) return;
    const providers = [...settings.ai.providers];
    const targetIdx = direction === 'up' ? index - 1 : index + 1;
    if (targetIdx < 0 || targetIdx >= providers.length) return;

    const temp = providers[index];
    providers[index] = providers[targetIdx];
    providers[targetIdx] = temp;

    setSettings({
      ...settings,
      ai: { ...settings.ai, providers },
    });
  };

  const toggleProviderEnabled = (index: number) => {
    if (!settings) return;
    const providers = [...settings.ai.providers];
    const cur = providers[index];
    providers[index] = { ...cur, enabled: !(cur.enabled ?? true) };
    setSettings({
      ...settings,
      ai: { ...settings.ai, providers },
    });
  };

  const deleteProvider = (index: number) => {
    if (!settings) return;
    const target = settings.ai.providers[index];
    if (!window.confirm(`Bạn có chắc muốn xoá nhà cung cấp "${target.name}"?`)) return;

    const providers = settings.ai.providers.filter((_, idx) => idx !== index);
    setSettings({
      ...settings,
      ai: { ...settings.ai, providers },
    });
  };

  const addProviderFromTemplate = () => {
    if (!settings) return;
    const t = PROVIDER_TEMPLATES[selectedTemplateKey];
    if (!t) return;

    // Generate unique name if already exists
    let newName = t.template.name;
    let count = 1;
    while (settings.ai.providers.some((p) => p.name.toLowerCase() === newName.toLowerCase())) {
      newName = `${t.template.name}_${++count}`;
    }

    const newProvider: AIProviderSetting = {
      ...t.template,
      name: newName,
    };

    setSettings({
      ...settings,
      ai: {
        ...settings.ai,
        providers: [...settings.ai.providers, newProvider],
      },
    });

    fetchProviderModels(newName);
  };

  // Voting algorithm presets
  const applyVotingPreset = (preset: 'strict' | 'balanced' | 'relaxed') => {
    if (!settings) return;
    let patch = {};
    if (preset === 'strict') {
      patch = {
        confident_min_ratio: 0.8,
        confident_min_voters: 3,
        multi_choice_threshold: 0.6,
      };
    } else if (preset === 'balanced') {
      patch = {
        confident_min_ratio: 0.7,
        confident_min_voters: 2,
        multi_choice_threshold: 0.5,
      };
    } else if (preset === 'relaxed') {
      patch = {
        confident_min_ratio: 0.6,
        confident_min_voters: 1,
        multi_choice_threshold: 0.4,
      };
    }
    setSettings({
      ...settings,
      voting: { ...settings.voting, ...patch },
    });
  };

  if (isLoading || !settings) {
    return (
      <div style={{ padding: 'var(--space-8)', textAlign: 'center', color: 'var(--text-secondary)' }}>
        <p style={{ fontFamily: 'var(--font-mono)' }}>Đang nạp bảng cài đặt từ máy chủ...</p>
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-6)', paddingBottom: hasUnsavedChanges ? '80px' : 'var(--space-10)' }}>
      {/* Header & Controls */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', borderBottom: '1px solid var(--border-subtle)', paddingBottom: 'var(--space-4)' }}>
        <div>
          <button
            onClick={onBack}
            style={{
              background: 'none',
              border: 'none',
              padding: '0',
              color: 'var(--primary)',
              cursor: 'pointer',
              fontSize: 'var(--text-sm)',
              fontWeight: 600,
              display: 'flex',
              alignItems: 'center',
              gap: 'var(--space-1)',
              marginBottom: 'var(--space-2)',
            }}
          >
            ← Quay lại màn hình chính
          </button>
          <h1 style={{ fontFamily: 'var(--font-serif)', fontSize: 'var(--text-2xl)', fontWeight: 700, margin: 0, color: 'var(--text-primary)' }}>
            Cài đặt hệ thống
          </h1>
          <p style={{ fontSize: 'var(--text-sm)', color: 'var(--text-secondary)', margin: 'var(--space-1) 0 0 0' }}>
            Tuỳ chỉnh quy tắc xuất file Word, mô hình Vision AI, thuật toán bỏ phiếu và tốc độ cào. Cài đặt được lưu vào cơ sở dữ liệu và chụp ảnh riêng cho từng job.
          </p>
        </div>

        <div style={{ display: 'flex', gap: 'var(--space-3)' }}>
          <button
            onClick={handleReset}
            disabled={isSaving}
            style={{
              padding: 'var(--space-2) var(--space-4)',
              border: '1px solid var(--border-strong)',
              backgroundColor: 'var(--bg-surface)',
              color: 'var(--text-secondary)',
              borderRadius: 'var(--radius-sm)',
              cursor: 'pointer',
              fontSize: 'var(--text-sm)',
              fontWeight: 500,
            }}
          >
            Đặt lại mặc định
          </button>
          <button
            onClick={handleSave}
            disabled={isSaving}
            style={{
              padding: 'var(--space-2) var(--space-5)',
              border: '1px solid var(--primary)',
              backgroundColor: 'var(--primary)',
              color: '#FFFFFF',
              borderRadius: 'var(--radius-sm)',
              cursor: 'pointer',
              fontSize: 'var(--text-sm)',
              fontWeight: 600,
            }}
          >
            {isSaving ? 'Đang lưu...' : 'Lưu cài đặt'}
          </button>
        </div>
      </div>

      {/* Notification Toast */}
      {notification && (
        <div
          style={{
            padding: 'var(--space-3) var(--space-4)',
            borderRadius: 'var(--radius-sm)',
            border: notification.type === 'success' ? '1px solid var(--status-confident-border)' : '1px solid var(--status-conflict-border)',
            backgroundColor: notification.type === 'success' ? 'var(--status-confident-bg)' : 'var(--status-conflict-bg)',
            color: notification.type === 'success' ? 'var(--status-confident-text)' : 'var(--status-conflict-text)',
            fontSize: 'var(--text-sm)',
          }}
        >
          {notification.message}
        </div>
      )}

      {/* Settings Navigation Tabs */}
      <div
        style={{
          display: 'flex',
          gap: 'var(--space-2)',
          borderBottom: '1px solid var(--border-subtle)',
          paddingBottom: 'var(--space-2)',
          flexWrap: 'wrap',
        }}
      >
        <button
          type="button"
          onClick={() => setActiveSection('basic')}
          style={{
            padding: '8px 16px',
            fontSize: 'var(--text-sm)',
            fontWeight: activeSection === 'basic' ? 700 : 500,
            backgroundColor: activeSection === 'basic' ? 'var(--primary)' : 'var(--bg-surface)',
            color: activeSection === 'basic' ? '#FFFFFF' : 'var(--text-secondary)',
            border: `1px solid ${activeSection === 'basic' ? 'var(--primary)' : 'var(--border-strong)'}`,
            borderRadius: 'var(--radius-sm)',
            cursor: 'pointer',
            display: 'inline-flex',
            alignItems: 'center',
            gap: '6px',
            minHeight: '38px',
          }}
        >
          <span>📁</span>
          <span>1. Cơ bản (Xuất file Word)</span>
        </button>

        <button
          type="button"
          onClick={() => setActiveSection('ai')}
          style={{
            padding: '8px 16px',
            fontSize: 'var(--text-sm)',
            fontWeight: activeSection === 'ai' ? 700 : 500,
            backgroundColor: activeSection === 'ai' ? 'var(--primary)' : 'var(--bg-surface)',
            color: activeSection === 'ai' ? '#FFFFFF' : 'var(--text-secondary)',
            border: `1px solid ${activeSection === 'ai' ? 'var(--primary)' : 'var(--border-strong)'}`,
            borderRadius: 'var(--radius-sm)',
            cursor: 'pointer',
            display: 'inline-flex',
            alignItems: 'center',
            gap: '6px',
            minHeight: '38px',
          }}
        >
          <span>🤖</span>
          <span>2. Trí tuệ nhân tạo (AI Engine)</span>
        </button>

        <button
          type="button"
          onClick={() => setActiveSection('advanced')}
          style={{
            padding: '8px 16px',
            fontSize: 'var(--text-sm)',
            fontWeight: activeSection === 'advanced' ? 700 : 500,
            backgroundColor: activeSection === 'advanced' ? 'var(--primary)' : 'var(--bg-surface)',
            color: activeSection === 'advanced' ? '#FFFFFF' : 'var(--text-secondary)',
            border: `1px solid ${activeSection === 'advanced' ? 'var(--primary)' : 'var(--border-strong)'}`,
            borderRadius: 'var(--radius-sm)',
            cursor: 'pointer',
            display: 'inline-flex',
            alignItems: 'center',
            gap: '6px',
            minHeight: '38px',
          }}
        >
          <span>⚡</span>
          <span>3. Nâng cao (Voting & Thu thập)</span>
        </button>
      </div>

      <div style={{ fontSize: '12px', color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: '6px' }}>
        <span>💡</span>
        <span>Cài đặt được lưu vào cơ sở dữ liệu và tự động áp dụng cho các phiên biên soạn tiếp theo.</span>
      </div>

      {/* Group 1: Xuất file Word */}
      {activeSection === 'basic' && (
      <div style={{ backgroundColor: 'var(--bg-surface)', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-md)', padding: 'var(--space-5)' }}>
        <h2 style={{ fontFamily: 'var(--font-serif)', fontSize: 'var(--text-lg)', fontWeight: 700, margin: '0 0 var(--space-4) 0', color: 'var(--text-primary)' }}>
          1. Xuất file Word (.docx)
        </h2>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 'var(--space-4)' }}>
          <div>
            <label style={{ display: 'block', fontSize: 'var(--text-xs)', fontWeight: 600, color: 'var(--text-secondary)', marginBottom: 'var(--space-1)' }}>
              Định dạng dòng đáp án
            </label>
            <select
              value={settings.export.answer_format}
              onChange={(e) => setSettings({ ...settings, export: { ...settings.export, answer_format: e.target.value as any } })}
              style={{ width: '100%', padding: 'var(--space-2)', border: '1px solid var(--border-strong)', borderRadius: 'var(--radius-sm)', backgroundColor: 'var(--bg-surface)', color: 'var(--text-primary)' }}
            >
              <option value="letter_keyword">Chữ cái + Từ khoá (Ví dụ: B. Classes and objects) [Khuyên dùng]</option>
              <option value="letter">Chỉ chữ cái đáp án (Ví dụ: B)</option>
            </select>
            <span style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>Từ khoá được AI trích xuất ngắn gọn từ ảnh câu hỏi.</span>
          </div>

          <div>
            <label style={{ display: 'block', fontSize: 'var(--text-xs)', fontWeight: 600, color: 'var(--text-secondary)', marginBottom: 'var(--space-1)' }}>
              Chiều rộng tối đa của ảnh trong Word (cm)
            </label>
            <input
              type="number"
              step="0.1"
              min="5"
              max="25"
              value={settings.export.image_width_cm}
              onChange={(e) => setSettings({ ...settings, export: { ...settings.export, image_width_cm: parseFloat(e.target.value) || 16.51 } })}
              style={{ width: '100%', padding: 'var(--space-2)', border: '1px solid var(--border-strong)', borderRadius: 'var(--radius-sm)', backgroundColor: 'var(--bg-surface)', color: 'var(--text-primary)' }}
            />
            <span style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>Chuẩn 16.51 cm (vừa vặn lề 2.54 cm trên khổ Letter chuẩn Word).</span>
          </div>

          <div>
            <label style={{ display: 'block', fontSize: 'var(--text-xs)', fontWeight: 600, color: 'var(--text-secondary)', marginBottom: 'var(--space-1)' }}>
              Độ phóng ảnh (%)
            </label>
            <input
              type="number"
              step="5"
              min="50"
              max="200"
              value={settings.export.image_zoom_percent ?? 100}
              onChange={(e) => setSettings({ ...settings, export: { ...settings.export, image_zoom_percent: parseInt(e.target.value, 10) || 100 } })}
              style={{ width: '100%', padding: 'var(--space-2)', border: '1px solid var(--border-strong)', borderRadius: 'var(--radius-sm)', backgroundColor: 'var(--bg-surface)', color: 'var(--text-primary)' }}
            />
            <span style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>Mặc định 100% (giữ nguyên kích thước 120 dpi gốc).</span>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-2)', justifyContent: 'center' }}>
            <label style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', cursor: 'pointer', fontSize: 'var(--text-sm)', color: 'var(--text-primary)' }}>
              <input
                type="checkbox"
                checked={settings.export.merge}
                onChange={(e) => setSettings({ ...settings, export: { ...settings.export, merge: e.target.checked } })}
              />
              Gộp tất cả đề đã cào vào 1 file Word duy nhất (ngắt trang giữa các đề)
            </label>

            <label style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', cursor: 'pointer', fontSize: 'var(--text-sm)', color: 'var(--text-primary)' }}>
              <input
                type="checkbox"
                checked={settings.export.highlight_low_confidence}
                onChange={(e) => setSettings({ ...settings, export: { ...settings.export, highlight_low_confidence: e.target.checked } })}
              />
              Thêm ghi chú nhỏ <i>(cần kiểm tra lại)</i> cho câu hỏi có đáp án tranh chấp hoặc chưa chắc chắn
            </label>
          </div>
        </div>
      </div>
      )}

      {/* Group 2: AI Vision Multi-provider */}
      {activeSection === 'ai' && (
      <div style={{ backgroundColor: 'var(--bg-surface)', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-md)', padding: 'var(--space-5)' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 'var(--space-4)' }}>
          <h2 style={{ fontFamily: 'var(--font-serif)', fontSize: 'var(--text-lg)', fontWeight: 700, margin: 0, color: 'var(--text-primary)' }}>
            2. Trí tuệ nhân tạo (Vision AI)
          </h2>
          <label style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', cursor: 'pointer', fontSize: 'var(--text-sm)', fontWeight: 600, color: 'var(--text-primary)' }}>
            <input
              type="checkbox"
              checked={settings.ai.enabled}
              onChange={(e) => setSettings({ ...settings, ai: { ...settings.ai, enabled: e.target.checked } })}
            />
            Bật tính năng AI giải đề
          </label>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 'var(--space-4)', marginBottom: 'var(--space-5)' }}>
          <div>
            <label style={{ display: 'block', fontSize: 'var(--text-xs)', fontWeight: 600, color: 'var(--text-secondary)', marginBottom: 'var(--space-1)' }}>
              Trần lượt gọi API mỗi job
            </label>
            <input
              type="number"
              min="1"
              max="500"
              value={settings.ai.max_ai_calls}
              onChange={(e) => setSettings({ ...settings, ai: { ...settings.ai, max_ai_calls: parseInt(e.target.value) || 300 } })}
              style={{ width: '100%', padding: 'var(--space-2)', border: '1px solid var(--border-strong)', borderRadius: 'var(--radius-sm)', backgroundColor: 'var(--bg-surface)', color: 'var(--text-primary)' }}
            />
            <span style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>Mặc định 300 lượt gọi (đủ cho 6-7 đề 40 câu).</span>
          </div>

          <div>
            <label style={{ display: 'block', fontSize: 'var(--text-xs)', fontWeight: 600, color: 'var(--text-secondary)', marginBottom: 'var(--space-1)' }}>
              Thời gian chờ backoff khi gặp 429 (giây)
            </label>
            <input
              type="number"
              step="0.5"
              min="0.5"
              value={settings.ai.backoff_seconds}
              onChange={(e) => setSettings({ ...settings, ai: { ...settings.ai, backoff_seconds: parseFloat(e.target.value) || 2.0 } })}
              style={{ width: '100%', padding: 'var(--space-2)', border: '1px solid var(--border-strong)', borderRadius: 'var(--radius-sm)', backgroundColor: 'var(--bg-surface)', color: 'var(--text-primary)' }}
            />
          </div>

          <div style={{ display: 'flex', alignItems: 'center', paddingTop: 'var(--space-4)' }}>
            <label style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', cursor: 'pointer', fontSize: 'var(--text-sm)', color: 'var(--text-primary)' }}>
              <input
                type="checkbox"
                checked={settings.ai.ensemble}
                onChange={(e) => setSettings({ ...settings, ai: { ...settings.ai, ensemble: e.target.checked } })}
              />
              Bầu cử phối hợp (Ensemble: 2 provider cùng độc lập bỏ phiếu)
            </label>
          </div>
        </div>

        {/* Providers Section */}
        <div style={{ borderTop: '1px solid var(--border-subtle)', paddingTop: 'var(--space-4)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 'var(--space-3)' }}>
            <div>
              <span style={{ fontSize: 'var(--text-sm)', fontWeight: 700, color: 'var(--text-primary)' }}>
                Danh sách nhà cung cấp (Thứ tự ưu tiên từ trên xuống dưới):
              </span>
              <p style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)', margin: 0 }}>
                Hệ thống tự động chuyển tiếp sang provider kế tiếp nếu gặp 429 hoặc lỗi mạng.
              </p>
            </div>

            {/* Add Provider Template Selector */}
            <div style={{ display: 'flex', gap: 'var(--space-2)', alignItems: 'center' }}>
              <select
                value={selectedTemplateKey}
                onChange={(e) => setSelectedTemplateKey(e.target.value)}
                style={{ padding: 'var(--space-1) var(--space-2)', fontSize: 'var(--text-xs)', border: '1px solid var(--border-strong)', borderRadius: 'var(--radius-sm)', backgroundColor: 'var(--bg-surface)', color: 'var(--text-primary)' }}
              >
                {Object.entries(PROVIDER_TEMPLATES).map(([key, item]) => (
                  <option key={key} value={key}>{item.label}</option>
                ))}
              </select>
              <button
                type="button"
                onClick={addProviderFromTemplate}
                style={{
                  padding: 'var(--space-1) var(--space-3)',
                  fontSize: 'var(--text-xs)',
                  fontWeight: 600,
                  backgroundColor: 'var(--primary)',
                  color: '#FFFFFF',
                  border: 'none',
                  borderRadius: 'var(--radius-sm)',
                  cursor: 'pointer',
                }}
              >
                + Thêm nhà cung cấp
              </button>
            </div>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
            {settings.ai.providers.map((p, idx) => {
              const testState = testingStatus[p.name];
              const isEnabled = p.enabled ?? true;
              const modelsList = availableModels[p.name] || [];
              const isLoadingCurrentModels = loadingModels[p.name] || false;

              return (
                <div
                  key={p.name}
                  style={{
                    border: '1px solid var(--border-subtle)',
                    borderRadius: 'var(--radius-sm)',
                    padding: 'var(--space-3) var(--space-4)',
                    backgroundColor: isEnabled ? 'var(--bg-subtle)' : 'var(--bg-canvas)',
                    opacity: isEnabled ? 1 : 0.65,
                    display: 'flex',
                    flexDirection: 'column',
                    gap: 'var(--space-2)',
                    transition: 'opacity var(--transition-fast)',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}>
                      <span style={{ fontFamily: 'var(--font-mono)', fontSize: 'var(--text-xs)', padding: '2px 6px', backgroundColor: 'var(--bg-surface)', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-sm)' }}>
                        #{idx + 1}
                      </span>
                      <strong style={{ fontSize: 'var(--text-sm)', textTransform: 'uppercase', color: 'var(--text-primary)' }}>
                        {p.name}
                      </strong>

                      {/* Enable/Disable Toggle */}
                      <button
                        type="button"
                        onClick={() => toggleProviderEnabled(idx)}
                        style={{
                          fontSize: '11px',
                          padding: '2px 8px',
                          borderRadius: '12px',
                          border: 'none',
                          cursor: 'pointer',
                          backgroundColor: isEnabled ? 'var(--status-confident-bg)' : 'var(--status-nodata-bg)',
                          color: isEnabled ? 'var(--status-confident-text)' : 'var(--status-nodata-text)',
                          fontWeight: 600,
                        }}
                      >
                        {isEnabled ? '● Đang bật' : '○ Đã tắt'}
                      </button>

                      {/* Key Source Indicator */}
                      <span
                        style={{
                          fontSize: '11px',
                          padding: '2px 8px',
                          borderRadius: '12px',
                          backgroundColor: p.has_api_key ? 'var(--ink-blue-subtle)' : 'var(--status-conflict-bg)',
                          color: p.has_api_key ? 'var(--ink-blue)' : 'var(--status-conflict-text)',
                          fontWeight: 500,
                        }}
                      >
                        {p.has_api_key
                          ? `✓ ${p.key_source || 'Đã cấu hình'}`
                          : '✕ Chưa có khoá'}
                      </span>
                    </div>

                    <div style={{ display: 'flex', gap: 'var(--space-1)', alignItems: 'center' }}>
                      <button
                        onClick={() => moveProvider(idx, 'up')}
                        disabled={idx === 0}
                        style={{ padding: '2px 8px', fontSize: 'var(--text-xs)', cursor: idx === 0 ? 'not-allowed' : 'pointer' }}
                        title="Đẩy lên ưu tiên cao hơn"
                      >
                        ▲
                      </button>
                      <button
                        onClick={() => moveProvider(idx, 'down')}
                        disabled={idx === settings.ai.providers.length - 1}
                        style={{ padding: '2px 8px', fontSize: 'var(--text-xs)', cursor: idx === settings.ai.providers.length - 1 ? 'not-allowed' : 'pointer' }}
                        title="Đẩy xuống ưu tiên thấp hơn"
                      >
                        ▼
                      </button>
                      <button
                        onClick={() => deleteProvider(idx)}
                        style={{ padding: '2px 8px', fontSize: 'var(--text-xs)', color: 'var(--primary)', cursor: 'pointer', marginLeft: '4px' }}
                        title="Xoá nhà cung cấp này"
                      >
                        🗑️
                      </button>
                    </div>
                  </div>

                  {/* Provider Settings Grid */}
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 'var(--space-3)' }}>
                    {/* Model Combobox (Dropdown + Text input) */}
                    <div>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 'var(--space-1)' }}>
                        <label style={{ fontSize: 'var(--text-xs)', color: 'var(--text-secondary)', fontWeight: 600 }}>
                          Mô hình (Model Vision):
                        </label>
                        <button
                          type="button"
                          onClick={() => fetchProviderModels(p.name, true)}
                          disabled={isLoadingCurrentModels}
                          style={{
                            background: 'none',
                            border: 'none',
                            fontSize: '11px',
                            color: 'var(--primary)',
                            cursor: 'pointer',
                            padding: 0,
                          }}
                        >
                          {isLoadingCurrentModels ? '⏳' : '🔄 Làm mới'}
                        </button>
                      </div>

                      {modelsList.length > 0 ? (
                        <select
                          value={p.model}
                          onChange={(e) => {
                            const updated = [...settings.ai.providers];
                            updated[idx] = { ...updated[idx], model: e.target.value };
                            setSettings({ ...settings, ai: { ...settings.ai, providers: updated } });
                          }}
                          style={{
                            width: '100%',
                            padding: 'var(--space-1) var(--space-2)',
                            fontSize: 'var(--text-xs)',
                            fontFamily: 'var(--font-mono)',
                            border: '1px solid var(--border-strong)',
                            borderRadius: 'var(--radius-sm)',
                            backgroundColor: 'var(--bg-surface)',
                            color: 'var(--text-primary)',
                          }}
                        >
                          {/* If current model is custom and not in list, preserve it */}
                          {!modelsList.some((m) => m.id === p.model) && p.model && (
                            <option value={p.model}>{p.model} (Tuỳ chỉnh)</option>
                          )}
                          {modelsList.map((m) => (
                            <option key={m.id} value={m.id}>
                              {m.name || m.id}
                            </option>
                          ))}
                        </select>
                      ) : (
                        <input
                          type="text"
                          value={p.model}
                          placeholder="Nhập tên model vision..."
                          onChange={(e) => {
                            const updated = [...settings.ai.providers];
                            updated[idx] = { ...updated[idx], model: e.target.value };
                            setSettings({ ...settings, ai: { ...settings.ai, providers: updated } });
                          }}
                          style={{ width: '100%', padding: 'var(--space-1) var(--space-2)', fontSize: 'var(--text-xs)', fontFamily: 'var(--font-mono)', border: '1px solid var(--border-strong)', borderRadius: 'var(--radius-sm)' }}
                        />
                      )}
                    </div>

                    {/* Base URL (if custom, openrouter, ollama, or openai) */}
                    {(p.base_url !== null || p.name.includes('openai') || p.name.includes('openrouter') || p.name.includes('ollama') || p.name.includes('custom')) && (
                      <div>
                        <label style={{ display: 'block', fontSize: 'var(--text-xs)', color: 'var(--text-secondary)', fontWeight: 600, marginBottom: 'var(--space-1)' }}>
                          Base URL (Điểm cuối API):
                        </label>
                        <input
                          type="text"
                          value={p.base_url || ''}
                          placeholder="https://..."
                          onChange={(e) => {
                            const updated = [...settings.ai.providers];
                            updated[idx] = { ...updated[idx], base_url: e.target.value };
                            setSettings({ ...settings, ai: { ...settings.ai, providers: updated } });
                          }}
                          style={{ width: '100%', padding: 'var(--space-1) var(--space-2)', fontSize: 'var(--text-xs)', fontFamily: 'var(--font-mono)', border: '1px solid var(--border-strong)', borderRadius: 'var(--radius-sm)', backgroundColor: 'var(--bg-surface)', color: 'var(--text-primary)' }}
                        />
                      </div>
                    )}

                    {/* API Key write-only input */}
                    <div>
                      <label style={{ display: 'block', fontSize: 'var(--text-xs)', color: 'var(--text-secondary)', fontWeight: 600, marginBottom: 'var(--space-1)' }}>
                        Nhập khoá API mới ({p.api_key_env}):
                      </label>
                      <input
                        type="password"
                        placeholder={p.has_api_key ? '•••••••• (đã cấu hình — để trống nếu giữ nguyên)' : 'Dán khoá API vào đây...'}
                        value={apiKeysInput[p.name] || ''}
                        onChange={(e) => setApiKeysInput({ ...apiKeysInput, [p.name]: e.target.value })}
                        style={{ width: '100%', padding: 'var(--space-1) var(--space-2)', fontSize: 'var(--text-xs)', fontFamily: 'var(--font-mono)', border: '1px solid var(--border-strong)', borderRadius: 'var(--radius-sm)', backgroundColor: 'var(--bg-surface)', color: 'var(--text-primary)' }}
                      />
                    </div>
                  </div>

                  {/* Test Connection Action */}
                  <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)', marginTop: 'var(--space-1)' }}>
                    <button
                      type="button"
                      onClick={() => handleTestConnection(p)}
                      disabled={testState?.loading}
                      style={{
                        padding: 'var(--space-1) var(--space-3)',
                        fontSize: 'var(--text-xs)',
                        fontWeight: 600,
                        backgroundColor: 'var(--bg-surface)',
                        border: '1px solid var(--border-strong)',
                        borderRadius: 'var(--radius-sm)',
                        cursor: 'pointer',
                        color: 'var(--text-primary)',
                      }}
                    >
                      {testState?.loading ? 'Đang gửi ảnh kiểm tra...' : '⚡ Thử đọc ảnh (Vision test)'}
                    </button>
                    {testState && !testState.loading && (
                      <span
                        style={{
                          fontSize: 'var(--text-xs)',
                          color: testState.success ? 'var(--status-confident-text)' : 'var(--status-conflict-text)',
                          fontWeight: 500,
                        }}
                      >
                        {testState.message}
                      </span>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>
      )}

      {/* Group 3 & 4: Nâng cao (Thuật toán bỏ phiếu & Crawler) */}
      {activeSection === 'advanced' && (
      <>
      {/* Group 3: Thuật toán bỏ phiếu */}
      <div style={{ backgroundColor: 'var(--bg-surface)', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-md)', padding: 'var(--space-5)' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 'var(--space-4)' }}>
          <div>
            <h2 style={{ fontFamily: 'var(--font-serif)', fontSize: 'var(--text-lg)', fontWeight: 700, margin: 0, color: 'var(--text-primary)' }}>
              3. Thuật toán bỏ phiếu & Ngưỡng câu chưa chắc chắn
            </h2>
            <p style={{ fontSize: 'var(--text-xs)', color: 'var(--text-secondary)', margin: '4px 0 0 0' }}>
              Xác định độ tin cậy của đáp án theo số đông cộng đồng và kiểm tra chéo với AI.
            </p>
          </div>

          {/* Preset Buttons */}
          <div style={{ display: 'flex', gap: '6px', alignItems: 'center' }}>
            <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>Cấu hình mẫu:</span>
            <button
              type="button"
              onClick={() => applyVotingPreset('strict')}
              style={{ padding: '2px 8px', fontSize: '11px', border: '1px solid var(--border-strong)', borderRadius: 'var(--radius-sm)', backgroundColor: 'var(--bg-surface)', cursor: 'pointer', color: 'var(--text-primary)' }}
            >
              🛡️ Chặt chẽ
            </button>
            <button
              type="button"
              onClick={() => applyVotingPreset('balanced')}
              style={{ padding: '2px 8px', fontSize: '11px', border: '1px solid var(--primary)', borderRadius: 'var(--radius-sm)', backgroundColor: 'var(--primary-subtle)', color: 'var(--primary)', fontWeight: 600, cursor: 'pointer' }}
            >
              ⚖️ Cân bằng (Chuẩn)
            </button>
            <button
              type="button"
              onClick={() => applyVotingPreset('relaxed')}
              style={{ padding: '2px 8px', fontSize: '11px', border: '1px solid var(--border-strong)', borderRadius: 'var(--radius-sm)', backgroundColor: 'var(--bg-surface)', cursor: 'pointer', color: 'var(--text-primary)' }}
            >
              🍃 Thông thoáng
            </button>
          </div>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 'var(--space-4)' }}>
          <div>
            <label style={{ display: 'block', fontSize: 'var(--text-xs)', fontWeight: 600, color: 'var(--text-secondary)', marginBottom: 'var(--space-1)' }}>
              Tỷ lệ đồng thuận để tự tin (Confident Ratio)
            </label>
            <input
              type="number"
              step="0.05"
              min="0.5"
              max="1.0"
              value={settings.voting.confident_min_ratio}
              onChange={(e) => setSettings({ ...settings, voting: { ...settings.voting, confident_min_ratio: parseFloat(e.target.value) || 0.7 } })}
              style={{ width: '100%', padding: 'var(--space-2)', border: '1px solid var(--border-strong)', borderRadius: 'var(--radius-sm)', backgroundColor: 'var(--bg-surface)', color: 'var(--text-primary)' }}
            />
            <span style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>Mặc định 0.70 (đáp án đạt ≥ 70% tổng điểm người bỏ phiếu).</span>
          </div>

          <div>
            <label style={{ display: 'block', fontSize: 'var(--text-xs)', fontWeight: 600, color: 'var(--text-secondary)', marginBottom: 'var(--space-1)' }}>
              Số người bỏ phiếu độc lập tối thiểu
            </label>
            <input
              type="number"
              min="1"
              max="10"
              value={settings.voting.confident_min_voters}
              onChange={(e) => setSettings({ ...settings, voting: { ...settings.voting, confident_min_voters: parseInt(e.target.value) || 2 } })}
              style={{ width: '100%', padding: 'var(--space-2)', border: '1px solid var(--border-strong)', borderRadius: 'var(--radius-sm)', backgroundColor: 'var(--bg-surface)', color: 'var(--text-primary)' }}
            />
            <span style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>Mặc định 2 người độc lập (AI tính là 1 nguồn).</span>
          </div>

          <div>
            <label style={{ display: 'block', fontSize: 'var(--text-xs)', fontWeight: 600, color: 'var(--text-secondary)', marginBottom: 'var(--space-1)' }}>
              Ngưỡng tính câu nhiều đáp án (Multi-choice)
            </label>
            <input
              type="number"
              step="0.05"
              min="0.2"
              max="0.9"
              value={settings.voting.multi_choice_threshold}
              onChange={(e) => setSettings({ ...settings, voting: { ...settings.voting, multi_choice_threshold: parseFloat(e.target.value) || 0.5 } })}
              style={{ width: '100%', padding: 'var(--space-2)', border: '1px solid var(--border-strong)', borderRadius: 'var(--radius-sm)', backgroundColor: 'var(--bg-surface)', color: 'var(--text-primary)' }}
            />
            <span style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>Mặc định 0.50 (phương án có điểm ≥ 50% tổng trọng số).</span>
          </div>

          <div>
            <label style={{ display: 'block', fontSize: 'var(--text-xs)', fontWeight: 600, color: 'var(--text-secondary)', marginBottom: 'var(--space-1)' }}>
              Trọng số phiếu của AI (AI Weight)
            </label>
            <input
              type="number"
              step="0.1"
              min="0.1"
              max="5.0"
              value={settings.voting.ai_weight}
              onChange={(e) => setSettings({ ...settings, voting: { ...settings.voting, ai_weight: parseFloat(e.target.value) || 1.0 } })}
              style={{ width: '100%', padding: 'var(--space-2)', border: '1px solid var(--border-strong)', borderRadius: 'var(--radius-sm)', backgroundColor: 'var(--bg-surface)', color: 'var(--text-primary)' }}
            />
            <span style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>Mặc định 1.0 (tương đương 1 người bỏ phiếu độc lập).</span>
          </div>
        </div>
      </div>

      {/* Group 4: Tốc độ cào (Crawler) */}
      <div style={{ backgroundColor: 'var(--bg-surface)', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-md)', padding: 'var(--space-5)' }}>
        <h2 style={{ fontFamily: 'var(--font-serif)', fontSize: 'var(--text-lg)', fontWeight: 700, margin: '0 0 var(--space-4) 0', color: 'var(--text-primary)' }}>
          4. Cấu hình cào dữ liệu (Crawler)
        </h2>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 'var(--space-4)' }}>
          <div>
            <label style={{ display: 'block', fontSize: 'var(--text-xs)', fontWeight: 600, color: 'var(--text-secondary)', marginBottom: 'var(--space-1)' }}>
              Thời gian trễ tối thiểu (giây)
            </label>
            <input
              type="number"
              step="0.1"
              min="1.5"
              value={settings.crawl.delay_seconds[0]}
              onChange={(e) => {
                const val = parseFloat(e.target.value) || 1.5;
                setSettings({ ...settings, crawl: { ...settings.crawl, delay_seconds: [val, settings.crawl.delay_seconds[1]] } });
              }}
              style={{ width: '100%', padding: 'var(--space-2)', border: '1px solid var(--border-strong)', borderRadius: 'var(--radius-sm)', backgroundColor: 'var(--bg-surface)', color: 'var(--text-primary)' }}
            />
            <span style={{ fontSize: 'var(--text-xs)', color: 'var(--primary)', fontWeight: 500 }}>
              * Giới hạn tối thiểu cứng: ≥ 1.5s (chống chặn bot)
            </span>
          </div>

          <div>
            <label style={{ display: 'block', fontSize: 'var(--text-xs)', fontWeight: 600, color: 'var(--text-secondary)', marginBottom: 'var(--space-1)' }}>
              Thời gian trễ tối đa (giây)
            </label>
            <input
              type="number"
              step="0.5"
              min="1.5"
              value={settings.crawl.delay_seconds[1]}
              onChange={(e) => {
                const val = parseFloat(e.target.value) || 4.0;
                setSettings({ ...settings, crawl: { ...settings.crawl, delay_seconds: [settings.crawl.delay_seconds[0], val] } });
              }}
              style={{ width: '100%', padding: 'var(--space-2)', border: '1px solid var(--border-strong)', borderRadius: 'var(--radius-sm)', backgroundColor: 'var(--bg-surface)', color: 'var(--text-primary)' }}
            />
            <span style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>Thời gian trễ ngẫu nhiên để an toàn.</span>
          </div>

          <div>
            <label style={{ display: 'block', fontSize: 'var(--text-xs)', fontWeight: 600, color: 'var(--text-secondary)', marginBottom: 'var(--space-1)' }}>
              Số luồng cào đồng thời (Concurrency: 1-2)
            </label>
            <input
              type="number"
              min="1"
              max="2"
              value={settings.crawl.concurrency}
              onChange={(e) => {
                const val = Math.min(2, Math.max(1, parseInt(e.target.value) || 1));
                setSettings({ ...settings, crawl: { ...settings.crawl, concurrency: val } });
              }}
              style={{ width: '100%', padding: 'var(--space-2)', border: '1px solid var(--border-strong)', borderRadius: 'var(--radius-sm)', backgroundColor: 'var(--bg-surface)', color: 'var(--text-primary)' }}
            />
            {settings.crawl.concurrency > 1 ? (
              <span style={{ fontSize: '11px', color: 'var(--status-weak-text)', fontWeight: 600, display: 'block', marginTop: '4px' }}>
                ⚠️ Tăng lên 2 luồng có thể làm tăng nguy cơ bị FUOverflow / Cloudflare chặn tạm thời. Nên duy trì 1 luồng.
              </span>
            ) : (
              <span style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>Mặc định 1 luồng an toàn tuyệt đối.</span>
            )}
          </div>

          <div style={{ display: 'flex', alignItems: 'center', paddingTop: 'var(--space-4)' }}>
            <label style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', cursor: 'pointer', fontSize: 'var(--text-sm)', color: 'var(--text-primary)' }}>
              <input
                type="checkbox"
                checked={settings.crawl.headless}
                onChange={(e) => setSettings({ ...settings, crawl: { ...settings.crawl, headless: e.target.checked } })}
              />
              Chạy trình duyệt ẩn (Headless mode)
            </label>
          </div>
        </div>
      </div>
      </>
      )}

      {/* Sticky Bottom Save Bar (Appears when unsaved changes exist) */}
      {hasUnsavedChanges && (
        <div
          style={{
            position: 'fixed',
            bottom: '0',
            left: '0',
            right: '0',
            backgroundColor: 'var(--bg-surface)',
            borderTop: '2px solid var(--primary)',
            padding: 'var(--space-3) var(--space-6)',
            boxShadow: '0 -4px 12px rgba(0, 0, 0, 0.15)',
            zIndex: 100,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}>
            <span style={{ fontSize: '18px' }}>⚠️</span>
            <span style={{ fontSize: 'var(--text-sm)', fontWeight: 600, color: 'var(--text-primary)' }}>
              Bạn có thay đổi cài đặt chưa lưu!
            </span>
          </div>

          <div style={{ display: 'flex', gap: 'var(--space-3)' }}>
            <button
              type="button"
              onClick={handleDiscardChanges}
              disabled={isSaving}
              style={{
                padding: 'var(--space-2) var(--space-4)',
                backgroundColor: 'var(--bg-canvas)',
                border: '1px solid var(--border-strong)',
                borderRadius: 'var(--radius-sm)',
                fontSize: 'var(--text-sm)',
                fontWeight: 500,
                color: 'var(--text-secondary)',
                cursor: 'pointer',
              }}
            >
              Huỷ bỏ thay đổi
            </button>
            <button
              type="button"
              onClick={handleSave}
              disabled={isSaving}
              style={{
                padding: 'var(--space-2) var(--space-5)',
                backgroundColor: 'var(--primary)',
                border: '1px solid var(--primary)',
                borderRadius: 'var(--radius-sm)',
                fontSize: 'var(--text-sm)',
                fontWeight: 600,
                color: '#FFFFFF',
                cursor: 'pointer',
              }}
            >
              {isSaving ? 'Đang lưu...' : 'Lưu cài đặt ngay'}
            </button>
          </div>
        </div>
      )}
    </div>
  );
};
