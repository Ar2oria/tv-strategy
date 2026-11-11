import "antd/dist/reset.css";
import "./styles.css";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ConfigProvider, theme as antdTheme } from "antd";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { RouterProvider, createBrowserRouter } from "react-router-dom";

import { routes } from "./router";

const rootElement = document.getElementById("root");
if (rootElement === null) {
  throw new Error("Application root element is missing");
}

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, refetchOnWindowFocus: false },
  },
});

const applicationTheme = {
  algorithm: antdTheme.darkAlgorithm,
  token: {
    colorPrimary: "#2962ff",
    colorBgBase: "#0d1117",
    colorBgContainer: "#131722",
    colorBgElevated: "#1e222d",
    colorText: "#d1d4dc",
    colorTextSecondary: "#9598a1",
    colorBorder: "#2a2e39",
    colorBorderSecondary: "#1e222d",
    borderRadius: 4,
    controlHeight: 32,
  },
  components: {
    Layout: {
      bodyBg: "#0d1117",
      headerBg: "#131722",
      siderBg: "#131722",
    },
    Menu: {
      darkItemBg: "#131722",
      darkItemColor: "#9598a1",
      darkItemHoverBg: "#1e222d",
      darkItemSelectedBg: "#1e293b",
      darkItemSelectedColor: "#ffffff",
    },
  },
};

createRoot(rootElement).render(
  <StrictMode>
    <ConfigProvider theme={applicationTheme}>
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={createBrowserRouter(routes)} />
      </QueryClientProvider>
    </ConfigProvider>
  </StrictMode>,
);
