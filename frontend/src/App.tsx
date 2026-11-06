import { Layout, Menu, Typography } from "antd";
import { Link, Outlet, useLocation } from "react-router-dom";

const NAV_ITEMS = [
  { key: "/analysis", label: <Link to="/analysis">图表分析</Link> },
  { key: "/tasks", label: <Link to="/tasks">Task 管理</Link> },
  { key: "/settings", label: <Link to="/settings">系统设置</Link> },
];

/** Application shell: navigation plus the routed page content. */
export function AppShell() {
  const location = useLocation();
  const selected = NAV_ITEMS.find((item) => location.pathname.startsWith(item.key));

  return (
    <Layout style={{ minHeight: "100vh" }}>
      <Layout.Header
        style={{
          display: "flex",
          alignItems: "center",
          gap: 24,
          background: "#fcfcfb",
          borderBottom: "1px solid #e8e7e3",
          paddingInline: 16,
        }}
      >
        <Typography.Text strong style={{ fontSize: 16, whiteSpace: "nowrap" }}>
          本地指标验证
        </Typography.Text>
        <Menu
          mode="horizontal"
          selectedKeys={selected === undefined ? [] : [selected.key]}
          items={NAV_ITEMS}
          style={{ flex: 1, minWidth: 0, borderBottom: "none", background: "transparent" }}
        />
      </Layout.Header>
      <Layout.Content style={{ padding: 16 }}>
        <Outlet />
      </Layout.Content>
    </Layout>
  );
}

/** Backwards-compatible export used by the router and existing tests. */
export function App() {
  return <AppShell />;
}
