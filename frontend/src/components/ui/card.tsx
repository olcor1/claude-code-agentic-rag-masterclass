import type { HTMLAttributes } from "react";

import { cn } from "@/lib/cn";

export function Card({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn("rounded-[28px] border border-ink/10 bg-white/70 p-5 shadow-panel backdrop-blur", className)}
      {...props}
    />
  );
}
