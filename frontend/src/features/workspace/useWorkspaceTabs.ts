import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import {
  useLocation,
  useNavigate,
  type NavigateFunction,
} from "react-router-dom";

export const WORKSPACE_TITLES = {
  "/analysis": "图表分析",
  "/tasks": "Task 管理",
  "/settings/data-sources": "数据源配置",
} as const;

export type WorkspacePath = keyof typeof WORKSPACE_TITLES;

export interface WorkspaceTab {
  key: WorkspacePath;
  title: string;
  content: ReactNode;
}

export interface WorkspaceTabsResult {
  tabs: readonly WorkspaceTab[];
  activeKey: string;
  closeTab: (key: WorkspacePath) => void;
  navigate: NavigateFunction;
}

export function isWorkspacePath(pathname: string): pathname is WorkspacePath {
  return pathname in WORKSPACE_TITLES;
}

/** Own route-backed tabs without ever recreating an existing page outlet. */
export function useWorkspaceTabs(outlet: ReactNode): WorkspaceTabsResult {
  const location = useLocation();
  const navigate = useNavigate();
  const [tabs, setTabs] = useState<WorkspaceTab[]>(() =>
    isWorkspacePath(location.pathname)
      ? [
          {
            key: location.pathname,
            title: WORKSPACE_TITLES[location.pathname],
            content: outlet,
          },
        ]
      : [],
  );

  const closingRef = useRef(false);

  useEffect(() => {
    if (closingRef.current) {
      closingRef.current = false;
      return;
    }
    if (!isWorkspacePath(location.pathname)) {
      return;
    }
    const pathname = location.pathname;
    setTabs((current) =>
      current.some((tab) => tab.key === pathname)
        ? current
        : [
            ...current,
            { key: pathname, title: WORKSPACE_TITLES[pathname], content: outlet },
          ],
    );
  }, [location.pathname, outlet]);

  const closeTab = useCallback(
    (key: WorkspacePath): void => {
      const index = tabs.findIndex((tab) => tab.key === key);
      if (index < 0) {
        return;
      }
      const next = tabs.filter((tab) => tab.key !== key);
      closingRef.current = true;
      setTabs(next);
      if (location.pathname === key) {
        navigate(next[index - 1]?.key ?? next[index]?.key ?? "/blank");
      }
    },
    [location.pathname, navigate, tabs],
  );

  return { tabs, activeKey: location.pathname, closeTab, navigate };
}
