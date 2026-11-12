import {
  LineChartOutlined,
  ScheduleOutlined,
  SettingOutlined,
} from "@ant-design/icons";
import { Layout, Menu } from "antd";
import { useState } from "react";
import { Link, Outlet, useLocation } from "react-router-dom";
import { Workspace } from "./features/workspace/Workspace";
import { WorkspaceTabsBar } from "./features/workspace/WorkspaceTabsBar";
import { isWorkspacePath, useWorkspaceTabs, type WorkspacePath } from "./features/workspace/useWorkspaceTabs";
import { workspacePage } from "./features/workspace/workspacePages";

const NAV_ITEMS = [
  { key: "/analysis", icon: <LineChartOutlined />, label: <Link to="/analysis">图表分析</Link> },
  { key: "/tasks", icon: <ScheduleOutlined />, label: <Link to="/tasks">Task 管理</Link> },
  {
    key: "/settings",
    icon: <SettingOutlined />,
    label: "系统设置",
    children: [
      {
        key: "/settings/data-sources",
        label: <Link to="/settings/data-sources">数据源配置</Link>,
      },
    ],
  },
];

/** Dark trading workspace with all primary navigation anchored on the left. */
export function AppShell() {
  const location = useLocation();
  const [collapsed, setCollapsed] = useState(false);
  const [openKeys, setOpenKeys] = useState<string[]>(["/settings"]);
  const workspace = useWorkspaceTabs(
    workspacePage(location.pathname as WorkspacePath),
  );
  const renderRedirect =
    workspace.tabs.length === 0 &&
    location.pathname !== "/blank" &&
    !isWorkspacePath(location.pathname);
  const selected = NAV_ITEMS.find((item) => location.pathname.startsWith(item.key));
  const selectedKey =
    location.pathname === "/settings/data-sources"
      ? "/settings/data-sources"
      : selected?.key;

  return (
    <Layout style={{ minHeight: "100vh", background: "#0d1117" }}>
      <Layout.Sider
        data-testid="app-sidebar"
        data-theme="dark"
        width={216}
        collapsedWidth={64}
        collapsible
        collapsed={collapsed}
        onCollapse={setCollapsed}
        onBreakpoint={setCollapsed}
        breakpoint="lg"
        trigger={null}
        style={{
          position: "sticky",
          top: 0,
          zIndex: 10,
          height: "100vh",
          overflow: "auto",
          background: "#131722",
          borderRight: "1px solid #2a2e39",
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 10,
            height: 64,
            padding: collapsed ? "0 20px" : "0 18px",
            borderBottom: "1px solid #2a2e39",
            color: "#d1d4dc",
          }}
        >
          <LineChartOutlined style={{ color: "#2962ff", fontSize: 22 }} />
          {collapsed ? null : (
            <div>
              <div style={{ fontSize: 16, fontWeight: 650, lineHeight: 1.3 }}>
                TV Strategy
              </div>
              <div style={{ color: "#9598a1", fontSize: 11, lineHeight: 1.5 }}>
                本地指标验证工作台
              </div>
            </div>
          )}
        </div>
        <Menu
          aria-label="主导航"
          theme="dark"
          mode="inline"
          selectedKeys={selectedKey === undefined ? [] : [selectedKey]}
          openKeys={openKeys}
          onOpenChange={setOpenKeys}
          items={NAV_ITEMS}
          style={{
            background: "transparent",
            borderInlineEnd: "none",
            padding: "8px 0",
          }}
        />
      </Layout.Sider>
      <Layout style={{ minWidth: 0, background: "#0d1117" }}>
        <Layout.Content
          className={
            location.pathname === "/analysis"
              ? "app-content app-content-analysis"
              : "app-content"
          }
        >
          {renderRedirect ? <Outlet /> : (
            <>
              <WorkspaceTabsBar {...workspace} />
              <Workspace {...workspace} />
            </>
          )}
        </Layout.Content>
      </Layout>
    </Layout>
  );
}

/** Backwards-compatible export used by the router and existing tests. */
export function App() {
  return <AppShell />;
}
