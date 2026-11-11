import type { NavigateFunction } from "react-router-dom";

import type { WorkspacePath, WorkspaceTab } from "./useWorkspaceTabs";

interface WorkspaceTabsBarProps {
  tabs: readonly WorkspaceTab[];
  activeKey: string;
  closeTab: (key: WorkspacePath) => void;
  navigate: NavigateFunction;
}

/** Native tab bar; page content stays in Workspace's cached sections. */
export function WorkspaceTabsBar({
  tabs,
  activeKey,
  closeTab,
  navigate,
}: WorkspaceTabsBarProps) {
  if (tabs.length === 0) {
    return null;
  }
  return (
    <div className="workspace-tabs" role="tablist" aria-label="已打开页面">
      {tabs.map((tab) => {
        const active = tab.key === activeKey;
        return (
          <span
            key={tab.key}
            className={`workspace-tab-shell${active ? " workspace-tab-active" : ""}`}
          >
            <button
              type="button"
              role="tab"
              className="workspace-tab"
              aria-selected={active}
              onClick={() => navigate(tab.key)}
            >
              {tab.title}
            </button>
            <button
              type="button"
              className="workspace-tab-close"
              aria-label={`关闭 ${tab.title}`}
              onClick={() => closeTab(tab.key)}
            >
              ×
            </button>
          </span>
        );
      })}
    </div>
  );
}
