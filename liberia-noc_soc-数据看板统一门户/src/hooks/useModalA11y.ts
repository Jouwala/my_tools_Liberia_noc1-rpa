// ============================================================================
// useModalA11y —— 模态框可访问性（焦点陷阱 + Esc 关闭 + 返回焦点）
// ----------------------------------------------------------------------------
// 背景（2026-10-02 a11y 补齐）：主门户此前只有零星 aria-label，模态框没有
// role="dialog"/aria-modal，键盘用户 Tab 会跑到模态框背后的页面上，Esc 也不关。
// 本 hook 把「模态框该有的键盘行为」收敛到一处，供各弹窗复用。
//
// 做了什么：
//   1. 打开时把焦点移进对话框（首个可聚焦元素，或 closeButtonRef）；
//   2. Tab / Shift+Tab 在对话框内循环（焦点陷阱），不会漏到背景；
//   3. Esc 触发 onClose；
//   4. 关闭后把焦点还给打开它的那个元素（返回焦点）。
//
// 用法：
//   const modalRef = useModalA11y<HTMLDivElement>({ isOpen, onClose });
//   <div ref={modalRef} role="dialog" aria-modal="true" aria-labelledby=... >
// ============================================================================

import { useEffect, useRef, type RefObject } from 'react';

const FOCUSABLE = [
  'a[href]',
  'button:not([disabled])',
  'textarea:not([disabled])',
  'input:not([disabled]):not([type="hidden"])',
  'select:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(',');

export interface UseModalA11yOptions {
  isOpen: boolean;
  onClose: () => void;
  /** 打开时优先聚焦的元素；缺省聚焦容器内第一个可聚焦元素 */
  initialFocusRef?: RefObject<HTMLElement | null>;
}

export function useModalA11y<T extends HTMLElement = HTMLElement>(
  options: UseModalA11yOptions
): RefObject<T | null> {
  const { isOpen, onClose, initialFocusRef } = options;
  const containerRef = useRef<T | null>(null);
  // 记住打开模态框前的焦点元素，关闭时还回去
  const previouslyFocused = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!isOpen) return;

    previouslyFocused.current = (document.activeElement as HTMLElement) ?? null;

    const getFocusable = (): HTMLElement[] => {
      const root = containerRef.current;
      if (!root) return [];
      // 显式断言为 HTMLElement[]：本项目的 tsconfig lib 下 querySelectorAll 的泛型
      // 返回被推断为 unknown[]，不转换的话 .filter 回调里 el 是 unknown（tsc 报 TS2322）。
      const nodes = Array.from(root.querySelectorAll(FOCUSABLE)) as HTMLElement[];
      return nodes.filter(
        (el) => !el.hasAttribute('disabled') && el.offsetParent !== null
      );
    };

    // 1) 打开后把焦点移入对话框（延迟一拍，等 DOM 渲染完成）
    const focusTarget = initialFocusRef?.current ?? getFocusable()[0] ?? containerRef.current;
    const raf = window.requestAnimationFrame(() => focusTarget?.focus?.());

    // 2) 键盘：Esc 关闭；Tab 循环（焦点陷阱）
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation();
        onClose();
        return;
      }
      if (e.key !== 'Tab') return;
      const focusable = getFocusable();
      if (focusable.length === 0) {
        e.preventDefault();
        containerRef.current?.focus?.();
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      const active = document.activeElement as HTMLElement | null;
      if (e.shiftKey) {
        if (active === first || !containerRef.current?.contains(active)) {
          e.preventDefault();
          last.focus();
        }
      } else if (active === last) {
        e.preventDefault();
        first.focus();
      }
    };
    document.addEventListener('keydown', onKeyDown, true);

    return () => {
      window.cancelAnimationFrame(raf);
      document.removeEventListener('keydown', onKeyDown, true);
      // 4) 关闭后焦点归还
      previouslyFocused.current?.focus?.();
    };
  }, [isOpen, onClose, initialFocusRef]);

  return containerRef;
}
