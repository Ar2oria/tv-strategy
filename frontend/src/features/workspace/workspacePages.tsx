import type { ReactNode } from "react";

import { AnalysisPage } from "../analysis/AnalysisPage";
import { AnalysisSessionProvider } from "../analysis/AnalysisSession";
import { SettingsPage } from "../settings/SettingsPage";
import { TasksPage } from "../tasks/TasksPage";
import type { WorkspacePath } from "./useWorkspaceTabs";

/** Resolve page content only when a route is first opened, never on activation. */
export function workspacePage(pathname: WorkspacePath): ReactNode {
  switch (pathname) {
    case "/analysis":
      return (
        <AnalysisSessionProvider>
          <AnalysisPage />
        </AnalysisSessionProvider>
      );
    case "/tasks":
      return <TasksPage />;
    case "/settings/data-sources":
      return <SettingsPage />;
  }
}
