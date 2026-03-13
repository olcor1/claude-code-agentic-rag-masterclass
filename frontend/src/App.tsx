import { AuthProvider, useAuth } from "@/hooks/use-auth";
import { AuthPage } from "@/pages/AuthPage";
import { DashboardPage } from "@/pages/DashboardPage";

function AppShell() {
  const { isReady, token } = useAuth();

  if (!isReady) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-paper text-ink">
        <div className="rounded-full border border-ink/10 px-5 py-3 text-sm uppercase tracking-[0.2em] text-ink/55">
          Loading workspace
        </div>
      </main>
    );
  }

  return token ? <DashboardPage /> : <AuthPage />;
}

export default function App() {
  return (
    <AuthProvider>
      <AppShell />
    </AuthProvider>
  );
}
