import type { HTMLAttributes } from "react";

import { cn } from "@/lib/cn";

export function Badge({ className, ...props }: HTMLAttributes<HTMLSpanElement>) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full border border-ink/10 bg-paper px-3 py-1 text-xs font-medium uppercase tracking-[0.18em] text-ink/70",
        className,
      )}
      {...props}
    />
  );
}
