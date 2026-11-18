import React, { useState, useEffect } from 'react';

export interface ConfirmOptions {
  title?: string;
  message: string;
  confirmText?: string;
  cancelText?: string;
  isDanger?: boolean;
}

export interface AlertOptions {
  title?: string;
  message: string;
  buttonText?: string;
  type?: 'info' | 'error' | 'success';
}

type ModalState =
  | {
      type: 'confirm';
      options: ConfirmOptions;
      resolve: (val: boolean) => void;
    }
  | {
      type: 'alert';
      options: AlertOptions;
      resolve: () => void;
    }
  | null;

let modalListener: ((state: ModalState) => void) | null = null;

export function confirmModal(options: ConfirmOptions | string): Promise<boolean> {
  const opts: ConfirmOptions = typeof options === 'string' ? { message: options } : options;
  return new Promise<boolean>((resolve) => {
    if (modalListener) {
      modalListener({
        type: 'confirm',
        options: opts,
        resolve,
      });
    } else {
      // Fallback
      resolve(true);
    }
  });
}

export function alertModal(options: AlertOptions | string): Promise<void> {
  const opts: AlertOptions = typeof options === 'string' ? { message: options } : options;
  return new Promise<void>((resolve) => {
    if (modalListener) {
      modalListener({
        type: 'alert',
        options: opts,
        resolve,
      });
    } else {
      resolve();
    }
  });
}

export const GlobalModalHost: React.FC = () => {
  const [modal, setModal] = useState<ModalState>(null);

  useEffect(() => {
    modalListener = setModal;
    return () => {
      modalListener = null;
    };
  }, []);

  if (!modal) return null;

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        backgroundColor: 'rgba(0, 0, 0, 0.65)',
        backdropFilter: 'blur(3px)',
        zIndex: 99999,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '16px',
        animation: 'fadeIn 0.15s ease',
      }}
      role="dialog"
      aria-modal="true"
    >
      <div
        style={{
          backgroundColor: 'var(--bg-surface, #1e293b)',
          border: '1px solid var(--border-subtle, #334155)',
          borderRadius: 'var(--radius-lg, 10px)',
          padding: '20px 24px',
          maxWidth: '460px',
          width: '100%',
          boxShadow: '0 20px 25px -5px rgba(0, 0, 0, 0.5), 0 8px 10px -6px rgba(0, 0, 0, 0.5)',
          color: 'var(--text-primary, #f8fafc)',
        }}
      >
        <h3
          style={{
            margin: '0 0 10px 0',
            fontSize: '15px',
            fontWeight: 700,
            color:
              modal.type === 'confirm' && modal.options.isDanger
                ? '#f87171'
                : 'var(--text-primary, #f8fafc)',
          }}
        >
          {modal.options.title || (modal.type === 'confirm' ? 'Xác nhận thao tác' : 'Thông báo')}
        </h3>

        <div
          style={{
            fontSize: '13px',
            lineHeight: 1.5,
            color: 'var(--text-secondary, #cbd5e1)',
            marginBottom: '20px',
            whiteSpace: 'pre-wrap',
          }}
        >
          {modal.options.message}
        </div>

        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px' }}>
          {modal.type === 'confirm' ? (
            <>
              <button
                type="button"
                onClick={() => {
                  modal.resolve(false);
                  setModal(null);
                }}
                style={{
                  padding: '7px 16px',
                  backgroundColor: 'transparent',
                  border: '1px solid var(--border-subtle, #475569)',
                  color: 'var(--text-secondary, #cbd5e1)',
                  borderRadius: '6px',
                  fontSize: '13px',
                  fontWeight: 500,
                  cursor: 'pointer',
                }}
              >
                {modal.options.cancelText || 'Huỷ bỏ'}
              </button>
              <button
                type="button"
                onClick={() => {
                  modal.resolve(true);
                  setModal(null);
                }}
                style={{
                  padding: '7px 16px',
                  backgroundColor: modal.options.isDanger ? '#dc2626' : 'var(--primary, #2563eb)',
                  border: 'none',
                  color: '#ffffff',
                  borderRadius: '6px',
                  fontSize: '13px',
                  fontWeight: 600,
                  cursor: 'pointer',
                }}
              >
                {modal.options.confirmText || 'Xác nhận'}
              </button>
            </>
          ) : (
            <button
              type="button"
              onClick={() => {
                modal.resolve();
                setModal(null);
              }}
              style={{
                padding: '7px 20px',
                backgroundColor: 'var(--primary, #2563eb)',
                border: 'none',
                color: '#ffffff',
                borderRadius: '6px',
                fontSize: '13px',
                fontWeight: 600,
                cursor: 'pointer',
              }}
            >
              {modal.options.buttonText || 'Đóng'}
            </button>
          )}
        </div>
      </div>
    </div>
  );
};
