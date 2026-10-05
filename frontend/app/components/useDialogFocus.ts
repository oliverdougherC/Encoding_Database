"use client";

import { useEffect, useRef } from "react";

/** Keep keyboard navigation inside an open dialog and return to its trigger. */
export function useDialogFocus<T extends HTMLElement>(onClose: () => void) {
  const ref = useRef<T>(null);
  const close = useRef(onClose);
  useEffect(() => { close.current = onClose; }, [onClose]);
  useEffect(() => {
    const panel = ref.current;
    if (!panel) return;
    const trigger = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    panel.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") { event.preventDefault(); close.current(); }
      if (event.key !== "Tab") return;
      const targets = Array.from(panel.querySelectorAll<HTMLElement>("a[href],button:not(:disabled),input:not(:disabled),select:not(:disabled),textarea:not(:disabled),summary,[tabindex]"))
        .filter((element) => {
          if (element.tabIndex < 0 || element.closest("[hidden],[inert]")) return false;
          for (let ancestor: HTMLElement | null = element; ancestor && ancestor !== panel; ancestor = ancestor.parentElement) {
            if (getComputedStyle(ancestor).display === "none" || getComputedStyle(ancestor).visibility === "hidden") return false;
            if (ancestor.tagName === "DETAILS" && !ancestor.hasAttribute("open") && !ancestor.querySelector("summary")?.contains(element)) return false;
          }
          return true;
        });
      const first = targets[0], last = targets.at(-1);
      if (!first) { event.preventDefault(); panel.focus(); return; }
      if (!panel.contains(document.activeElement) || document.activeElement === panel) {
        event.preventDefault(); (event.shiftKey ? last : first)?.focus();
      } else if (event.shiftKey && document.activeElement === first) {
        event.preventDefault(); last?.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault(); first.focus();
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = previousOverflow;
      if (trigger?.isConnected) trigger.focus();
    };
  }, []);
  return ref;
}
