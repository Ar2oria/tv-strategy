import { Navigate, type RouteObject } from "react-router-dom";

import { AppShell } from "./App";
import { AnalysisPage } from "./features/analysis/AnalysisPage";
import { SettingsPage } from "./features/settings/SettingsPage";
import { TasksPage } from "./features/tasks/TasksPage";

export const routes: RouteObject[] = [
  {
    path: "/",
    element: <AppShell />,
    children: [
      { index: true, element: <Navigate to="/analysis" replace /> },
      { path: "analysis", element: <AnalysisPage /> },
      { path: "tasks", element: <TasksPage /> },
      { path: "settings", element: <SettingsPage /> },
      { path: "*", element: <Navigate to="/analysis" replace /> },
    ],
  },
];
