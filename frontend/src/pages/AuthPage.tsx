import { useState, type FormEvent } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useAuth } from "@/hooks/use-auth";

export function AuthPage() {
  const { error, loginWithPassword, registerWithPassword } = useAuth();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setIsSubmitting(true);
    try {
      if (mode === "login") {
        await loginWithPassword(email, password);
      } else {
        await registerWithPassword(email, password);
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <main className="relative min-h-screen overflow-hidden bg-paper px-6 py-10 text-ink">
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_top_left,_rgba(214,140,69,0.28),_transparent_30%),radial-gradient(circle_at_bottom_right,_rgba(37,84,72,0.28),_transparent_35%)]" />
      <div className="relative mx-auto grid min-h-[calc(100vh-5rem)] max-w-6xl gap-8 lg:grid-cols-[1.1fr_0.9fr]">
        <section className="flex flex-col justify-between rounded-[36px] border border-ink/10 bg-ink px-8 py-10 text-paper shadow-panel">
          <div className="space-y-6">
            <Badge className="border-paper/15 bg-paper/10 text-paper/75">Module 1 / Local RAG</Badge>
            <h1 className="max-w-xl text-5xl font-semibold leading-tight">
              Build a grounded chat workspace around your own documents.
            </h1>
            <p className="max-w-xl text-base text-paper/72">
              FastAPI streams the answer, PostgreSQL keeps the memory, pgvector ranks the chunks, and your local
              OpenAI-compatible endpoint closes the loop.
            </p>
          </div>
          <div className="grid gap-3 text-sm text-paper/70 sm:grid-cols-3">
            <div>JWT auth</div>
            <div>pgvector retrieval</div>
            <div>LangSmith traces</div>
          </div>
        </section>

        <Card className="flex items-center justify-center p-8">
          <form className="w-full max-w-md space-y-5" onSubmit={submit}>
            <div className="space-y-2">
              <Badge>{mode === "login" ? "Sign in" : "Create account"}</Badge>
              <h2 className="text-3xl font-semibold">Operator access</h2>
              <p className="text-sm text-ink/65">Use email and password to enter the local RAG workspace.</p>
            </div>

            <div className="grid grid-cols-2 gap-3 rounded-full border border-ink/10 bg-paper p-1">
              <button
                className={`rounded-full px-4 py-2 text-sm ${mode === "login" ? "bg-ink text-paper" : "text-ink/65"}`}
                type="button"
                onClick={() => setMode("login")}
              >
                Sign in
              </button>
              <button
                className={`rounded-full px-4 py-2 text-sm ${mode === "register" ? "bg-ink text-paper" : "text-ink/65"}`}
                type="button"
                onClick={() => setMode("register")}
              >
                Register
              </button>
            </div>

            <label className="block space-y-2">
              <span className="text-sm font-medium">Email</span>
              <Input type="email" value={email} onChange={(event) => setEmail(event.target.value)} required />
            </label>

            <label className="block space-y-2">
              <span className="text-sm font-medium">Password</span>
              <Input
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                minLength={8}
                required
              />
            </label>

            {error ? <p className="text-sm text-berry">{error}</p> : null}

            <Button className="w-full" disabled={isSubmitting} type="submit">
              {isSubmitting ? "Working..." : mode === "login" ? "Enter workspace" : "Create workspace user"}
            </Button>
          </form>
        </Card>
      </div>
    </main>
  );
}
