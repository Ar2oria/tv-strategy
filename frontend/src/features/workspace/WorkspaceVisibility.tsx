import { createContext, useContext, type ReactNode } from "react";

const WorkspaceVisibilityContext = createContext(true);

export function WorkspaceVisibilityProvider({
  active,
  children,
}: {
  active: boolean;
  children: ReactNode;
}) {
  return (
    <WorkspaceVisibilityContext.Provider value={active}>
      {children}
    </WorkspaceVisibilityContext.Provider>
  );
}

/** True when no workspace is present, or when this page's tab is active. */
export function useWorkspaceVisibility(): boolean {
  return useContext(WorkspaceVisibilityContext);
}
