import { Empty } from "antd";
import type { NavigateFunction } from "react-router-dom";

import type { WorkspacePath, WorkspaceTab } from "./useWorkspaceTabs";
import { WorkspaceVisibilityProvider } from "./WorkspaceVisibility";

export interface WorkspaceProps {
  tabs: readonly WorkspaceTab[];
  activeKey: string;
  closeTab: (key: WorkspacePath) => void;
  navigate: NavigateFunction;
}

/** Cached pages stay mounted while only the active section is visible. */
export function Workspace({ tabs, activeKey }: WorkspaceProps) {
  return (
    <div style={{ minWidth: 0 }}>
      {activeKey === "/blank" ? (
        <Empty description="暂无打开的页面" />
      ) : (
        tabs.map((tab) => (
          <WorkspaceVisibilityProvider
            key={tab.key}
            active={tab.key === activeKey}
          >
            <section
              hidden={tab.key !== activeKey}
              data-testid={`workspace-page-${tab.key}`}
            >
              {tab.content}
            </section>
          </WorkspaceVisibilityProvider>
        ))
      )}
    </div>
  );
}
