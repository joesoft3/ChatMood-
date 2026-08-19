"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { token, verifySession } from "@/lib/api";

/** Logged-in visitors skip the marketing page and land on the chat home. */
export default function LandingGate() {
  const router = useRouter();
  useEffect(() => {
    let cancelled = false;
    (async () => {
      if (!token.get()) return;
      const ok = await verifySession();
      if (!cancelled && ok) router.replace("/chat");
    })();
    return () => {
      cancelled = true;
    };
  }, [router]);
  return null;
}
